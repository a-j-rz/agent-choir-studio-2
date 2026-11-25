"""Epistemic Horizons: shared concept lineages + one figure profile -> a compiled Horizon (E1).

A *lineage* is one concept through time: an ordered list of era-specific *senses*, each with
the traditions it reached and from when. A *profile* says where one figure stood: a horizon
year, the traditions it stood in, and reviewed exceptions. Compiling is deterministic set
arithmetic — no model, no judgement:

  available   a sense with an available_in entry in one of the figure's traditions, dated at
              or before the horizon year — then exceptions override (include true / false)
  per lineage available_sense = the last available sense in list order (or null)
              each unavailable sense is split by date, not by tradition:
              beyond    = its earliest available_in year is after the horizon year — it did
                          not exist anywhere yet; list order, bridge_distance 1..n
              unreached = it already existed somewhere, but not for this figure; list order
              (Why by date: under a tradition-based split, a figure whose only tradition is
              greco-roman would see every modern sense as "unreached" — beyond would be empty
              and bridge distance would never be computed.)
  breach (global, by stems) = stem sequences of every beyond/unreached sense's terms minus
              stem sequences of every available sense's terms. A term is matched as the
              sequence of stems retrieval.bm25.analyse gives it — the same tokeniser and
              stemmer as BM25 — so "habits" is cancelled by "habit". Acronym plurals do not
              stem to their singulars ("SSRIs" -> ssris), and digits are dropped ("DSM-5"
              -> dsm): those belong in the content, not in a matcher rule.

find_breaches(text, compiled) reports every breach stem sequence found contiguously in a text.

The compiled file is what is reviewed and committed; sources_sha256 makes it detectably stale.
"""

import hashlib
import json
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from retrieval.bm25 import analyse


SCHEMA_VERSION = "1"  # lineage, profile and traditions files
COMPILED_SCHEMA_VERSION = "2"  # 2: breach_stems, available_stems; matching by stems
COMPILER_VERSION = "2"
HORIZONS_DIR = Path(__file__).resolve().parent.parent / "horizons"
LCC_CLASSES = frozenset("ABCDEFGHJKLMNPQRSTUVZ")  # Library of Congress main classes


class HorizonError(Exception):
    """A Horizon source file or set of files is invalid. The message lists every problem."""


def _not_zero(year: int) -> int:
    if year == 0:
        raise ValueError("year 0 does not exist; use -1 for 1 BCE and 1 for 1 CE")
    return year


Year = Annotated[int, AfterValidator(_not_zero)]  # BCE negative: -50 is 50 BCE
Confidence = Literal["high", "medium", "low"]


def term_stems(term: str) -> tuple[str, ...]:
    """The term as BM25 sees it: its sequence of stems. Matching is on these."""
    return tuple(stem for _, stem in analyse(term))


def norm_term(term: str) -> str:
    """Terms compare trimmed and case-insensitive; a multi-word term stays one term."""
    return term.strip().lower()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Tradition(_Frozen):
    tradition_id: str
    label: str


class TraditionList(_Frozen):
    schema_version: Literal["1"]
    traditions: list[Tradition]


class AvailableIn(_Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    tradition: str
    from_: Year = Field(alias="from")
    precision: Literal["exact", "circa", "decade", "century"]


class Source(_Frozen):
    citation: str
    note: str


class Sense(_Frozen):
    sense_id: str
    label: str
    summary: str
    available_in: list[AvailableIn] = Field(min_length=1)
    prerequisites: list[str]
    terms: list[str]
    markers: list[str]
    hazards: list[str]
    sources: list[Source] = Field(min_length=1)
    confidence: Confidence

    @model_validator(mode="after")
    def _no_duplicate_terms(self):
        seen, dupes = set(), []
        for term in self.terms:
            key = norm_term(term)
            if not key:
                raise ValueError(f"{self.sense_id}: empty term")
            if re.search(r"\d", term):
                raise ValueError(f"{self.sense_id}: term {term!r} contains a digit; the "
                                 "tokeniser drops digits, so it would match without them")
            if not term_stems(term):
                raise ValueError(f"{self.sense_id}: term {term!r} yields no stems, "
                                 "so it could never match")
            if key in seen:
                dupes.append(term)
            seen.add(key)
        if dupes:
            raise ValueError(f"{self.sense_id}: duplicate terms {dupes}")
        return self


class Lineage(_Frozen):
    schema_version: Literal["1"]
    lineage_id: str
    label: str
    lcc_class: str
    wikidata: str | None
    senses: list[Sense] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self):
        if self.lcc_class not in LCC_CLASSES:
            raise ValueError(f"lcc_class {self.lcc_class!r} is not a Library of Congress main "
                             f"class ({' '.join(sorted(LCC_CLASSES))})")
        if self.wikidata is not None and not re.fullmatch(r"Q\d+", self.wikidata):
            raise ValueError(f"wikidata {self.wikidata!r} is not a Q-id")
        bad = [s.sense_id for s in self.senses
               if not s.sense_id.startswith(f"{self.lineage_id}.")]
        if bad:
            raise ValueError(f"sense_id(s) {bad} do not start with '{self.lineage_id}.'")
        return self


class Lived(_Frozen):
    born: Year
    died: Year

    @model_validator(mode="after")
    def _order(self):
        if self.born > self.died:
            raise ValueError(f"born {self.born} is after died {self.died}")
        return self


class ProfileTradition(_Frozen):
    tradition: str
    basis: str
    confidence: Confidence


class HorizonException(_Frozen):
    sense_id: str
    include: bool
    basis: str
    confidence: Confidence


class Profile(_Frozen):
    schema_version: Literal["1"]
    figure_id: str
    lived: Lived
    horizon_year: Year
    horizon_year_basis: str
    milieu: str
    traditions: list[ProfileTradition] = Field(min_length=1)
    exceptions: list[HorizonException]
    oracle_epoch: str = Field(min_length=1)


def _parse(model, path: Path, root: Path):
    try:
        return model.model_validate_json(path.read_bytes())
    except ValidationError as error:
        raise HorizonError(f"{path.relative_to(root).as_posix()}: {error}") from None


def source_paths(root: Path, figure_id: str) -> list[Path]:
    """Every file a compile reads, in sorted relative-path order."""
    paths = [root / "traditions.json", root / "profiles" / f"{figure_id}.json",
             *(root / "lineages").glob("*.json")]
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def sources_hash(root: Path, paths: list[Path]) -> str:
    """SHA-256 over 'sha256  relative/path' lines (sha256sum's format), sorted by path."""
    lines = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  "
                    f"{p.relative_to(root).as_posix()}\n" for p in paths)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def load(root: Path, figure_id: str):
    """(traditions, lineages, profile, sources_sha256), parsed and cross-validated."""
    root = Path(root)
    profile_path = root / "profiles" / f"{figure_id}.json"
    for required in (root / "traditions.json", profile_path):
        if not required.is_file():
            raise HorizonError(f"missing {required.relative_to(root).as_posix()}")
    paths = source_paths(root, figure_id)
    traditions = _parse(TraditionList, root / "traditions.json", root)
    profile = _parse(Profile, profile_path, root)
    lineages = []
    for path in paths:
        if path.parent.name == "lineages":
            lineage = _parse(Lineage, path, root)
            if path.stem != lineage.lineage_id:
                raise HorizonError(f"{path.name}: file name must be {lineage.lineage_id}.json")
            lineages.append(lineage)
    if profile.figure_id != figure_id:
        raise HorizonError(f"profile figure_id {profile.figure_id!r} != file name {figure_id!r}")
    validate_set(traditions, lineages, profile)
    return traditions, lineages, profile, sources_hash(root, paths)


def validate_set(traditions, lineages, profile) -> None:
    """Cross-file checks. Collects every problem, then raises once listing them all."""
    problems = []
    tradition_ids = [t.tradition_id for t in traditions.traditions]
    known_traditions = set(tradition_ids)
    if len(known_traditions) != len(tradition_ids):
        problems.append("duplicate tradition_id in traditions.json")

    lineage_ids = [lin.lineage_id for lin in lineages]
    for dup in sorted({i for i in lineage_ids if lineage_ids.count(i) > 1}):
        problems.append(f"duplicate lineage_id {dup!r}")
    sense_ids = [s.sense_id for lin in lineages for s in lin.senses]
    known_senses = set(sense_ids)
    for dup in sorted({i for i in sense_ids if sense_ids.count(i) > 1}):
        problems.append(f"duplicate sense_id {dup!r}")

    for lineage in lineages:
        for sense in lineage.senses:
            for prereq in sense.prerequisites:
                if prereq not in known_senses:
                    problems.append(f"{sense.sense_id}: prerequisite {prereq!r} does not exist")
            for entry in sense.available_in:
                if entry.tradition not in known_traditions:
                    problems.append(f"{sense.sense_id}: unknown tradition {entry.tradition!r}")

    for entry in profile.traditions:
        if entry.tradition not in known_traditions:
            problems.append(f"profile {profile.figure_id}: unknown tradition {entry.tradition!r}")
    excepted = [e.sense_id for e in profile.exceptions]
    for exc in excepted:
        if exc not in known_senses:
            problems.append(f"profile {profile.figure_id}: exception names unknown sense {exc!r}")
    for dup in sorted({i for i in excepted if excepted.count(i) > 1}):
        problems.append(f"profile {profile.figure_id}: more than one exception for {dup!r}")

    if problems:
        raise HorizonError("; ".join(problems))


def compile_horizon(traditions, lineages, profile, sources_sha256) -> dict:
    """The compiled Horizon as a plain dict. Deterministic: same inputs, same output."""
    mine = {t.tradition for t in profile.traditions}
    exceptions = {e.sense_id: e.include for e in profile.exceptions}

    def availability(sense):
        """(available, via) for one sense: 'tradition', 'exception', or None."""
        if sense.sense_id in exceptions:
            return exceptions[sense.sense_id], ("exception" if exceptions[sense.sense_id] else None)
        ok = any(a.tradition in mine and a.from_ <= profile.horizon_year
                 for a in sense.available_in)
        return ok, ("tradition" if ok else None)

    def not_yet_anywhere(sense):
        return min(a.from_ for a in sense.available_in) > profile.horizon_year

    records = []
    available, candidates = {}, {}  # stems -> {"terms": set, "lineages": set}

    def add(index, sense, lineage_id):
        for term in sense.terms:
            entry = index.setdefault(term_stems(term), {"terms": set(), "lineages": set()})
            entry["terms"].add(norm_term(term))
            entry["lineages"].add(lineage_id)

    for lineage in sorted(lineages, key=lambda lin: lin.lineage_id):
        status = [availability(s) for s in lineage.senses]
        last = max((i for i, (ok, _) in enumerate(status) if ok), default=-1)
        beyond, unreached, markers = [], [], []
        for sense, (ok, _) in zip(lineage.senses, status):
            if ok:
                add(available, sense, lineage.lineage_id)
                continue
            add(candidates, sense, lineage.lineage_id)
            markers += [m for m in sense.markers if m not in markers]
            item = {"sense_id": sense.sense_id, "label": sense.label,
                    "terms": list(sense.terms), "markers": list(sense.markers)}
            if not_yet_anywhere(sense):
                beyond.append({**item, "bridge_distance": len(beyond) + 1})
            else:
                unreached.append(item)
        available_sense = None
        if last >= 0:
            sense = lineage.senses[last]
            available_sense = {"sense_id": sense.sense_id, "label": sense.label,
                               "via": status[last][1]}
        records.append({"lineage_id": lineage.lineage_id, "label": lineage.label,
                        "lcc_class": lineage.lcc_class, "wikidata": lineage.wikidata,
                        "available_sense": available_sense, "beyond": beyond,
                        "unreached": unreached, "breach_markers": markers})

    def entries(index, keys):
        return [{"stems": list(k), "terms": sorted(index[k]["terms"]),
                 "lineages": sorted(index[k]["lineages"])} for k in sorted(keys)]

    breach = set(candidates) - set(available)
    return {"schema_version": COMPILED_SCHEMA_VERSION, "compiler_version": COMPILER_VERSION,
            "figure_id": profile.figure_id, "horizon_year": profile.horizon_year,
            "oracle_epoch": profile.oracle_epoch, "sources_sha256": sources_sha256,
            "lineages": records,
            "breach_terms": sorted({t for k in breach for t in candidates[k]["terms"]}),
            "breach_stems": entries(candidates, breach),
            "available_stems": entries(available, available)}


def find_breaches(text: str, compiled: dict) -> list[dict]:
    """Every breach stem sequence occurring contiguously in the text, as BM25 tokenises it.

    Where matches overlap, the longest wins, then the earliest ("mobile phone" is not also
    counted as "phone" at the same place). Output sorted by start_token. Deterministic.
    """
    tokens = analyse(text)
    stems = [stem for _, stem in tokens]
    found = []
    for entry in compiled["breach_stems"]:
        seq, n = entry["stems"], len(entry["stems"])
        for start in range(len(stems) - n + 1):
            if stems[start:start + n] == seq:
                found.append((n, start, entry))
    taken, hits = set(), []
    for n, start, entry in sorted(found, key=lambda f: (-f[0], f[1], f[2]["stems"])):
        span = set(range(start, start + n))
        if span & taken:
            continue
        taken |= span
        hits.append({"stems": entry["stems"],
                     "matched_surface": " ".join(s for s, _ in tokens[start:start + n]),
                     "lineages": entry["lineages"], "start_token": start})
    return sorted(hits, key=lambda h: h["start_token"])


def render(compiled: dict) -> str:
    return json.dumps(compiled, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def compiled_path(root: Path, figure_id: str) -> Path:
    return Path(root) / "compiled" / f"{figure_id}.json"


def build(root: Path, figure_id: str) -> str:
    """Load, validate and compile one figure; return the rendered file text."""
    return render(compile_horizon(*load(root, figure_id)))


def check(root: Path, figure_id: str) -> list[str]:
    """Differences between the committed compiled file and a fresh compile; [] if current."""
    path = compiled_path(root, figure_id)
    if not path.is_file():
        return [f"no compiled file at {path.relative_to(Path(root)).as_posix()}"]
    fresh_text = build(root, figure_id)
    committed_text = path.read_text(encoding="utf-8")
    if fresh_text == committed_text:
        return []
    fresh, committed = json.loads(fresh_text), json.loads(committed_text)
    keys = sorted(set(fresh) | set(committed), key=lambda k: (k != "sources_sha256", k))
    differing = [k for k in keys if fresh.get(k) != committed.get(k)]
    return differing or ["formatting differs (same content)"]

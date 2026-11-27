"""Chunk clean Darwin texts from repository root, with no model calls."""
import hashlib
import json
from pathlib import Path
import re
from collections import Counter

BASE = Path('corpora/charles_darwin')
ABBREVIATIONS = set()
INITIALS = re.compile(r'^(?:[A-Z]\.)+$')
# Independent of the configuration used to select boundaries.
END_ABBREVIATIONS = frozenset(('Mr','Mrs','Dr','Prof','Rev','St','Capt','Hon','etc','vol','p','pp','viz','cf','i.e','e.g'))

def words(text):
    return len(text.split())

def split_section(text, maximum):
    if words(text) <= maximum:
        return [text]
    boundaries = [match.start() for match in re.finditer(r"\n\n", text)]
    if not boundaries:
        # A capital after terminal punctuation is a sentence boundary here.
        boundaries = [match.start() for match in re.finditer(
            r'''(?<=[.!?])\s+(?=["'\[]?[A-Z])''', text)
            if not (text[:match.start()].endswith('.') and
                    (text[:match.start()].split()[-1][:-1] in ABBREVIATIONS or
                     INITIALS.fullmatch(text[:match.start()].split()[-1])))]
    if not boundaries:
        # Last resort: just after a semicolon followed by whitespace.
        boundaries = [match.end() for match in re.finditer(r";(?=\s)", text)]
    if not boundaries:
        raise ValueError("A sentence exceeds max_words with no semicolon; "
                         "no permitted split boundary")
    midpoint = words(text) / 2
    cut = min(boundaries, key=lambda pos: (abs(words(text[:pos]) - midpoint), pos))
    return (split_section(text[:cut].strip(), maximum)
            + split_section(text[cut:].strip(), maximum))

def sections(clean):
    unit=label=None; section=0; title=None; body=[]
    for line in clean.splitlines():
        if line.startswith('[['):
            if body and any(body): yield unit,label,section,title,'\n'.join(body).strip()
            body=[]
            m=re.fullmatch(r'\[\[(unit|section) (.+?) \| (.+)\]\]',line)
            if not m: raise ValueError('Invalid structural marker')
            if m[1]=='unit': unit,label=m[2],m[3]; section=0; title=None
            else:
                if int(m[2])!=section+1: raise ValueError('Section sequence')
                section=int(m[2]); title=m[3]
        else: body.append(line)
    if body and any(body): yield unit,label,section,title,'\n'.join(body).strip()

def main():
    config=json.loads((BASE/'chunking.json').read_text()); manifest=json.loads((BASE/'manifest.json').read_text())
    ABBREVIATIONS.update(config['abbreviations']); chunks=[]; splits=[]; cuts=[]; counts=Counter(); work_counts=Counter(); hashes={}; section_count=0
    for name,work,provenance in zip(('origin','descent'),('On the Origin of Species','The Descent of Man'),manifest['source_provenance']):
        raw=(BASE/f'data/clean/{name}.txt').read_bytes(); clean=raw.decode('utf-8'); hashes[name]=hashlib.sha256(raw).hexdigest()
        for unit,label,section,title,text in sections(clean):
            section_count+=1; code=unit.split('-')[1]; code={'sketch':'sk','intro':'in','preface':'pr','supplement':'su'}.get(code,code); base=f'cd-{name[0]}-{code}-{section:02d}'
            try: pieces=split_section(text,config['max_words'])
            except ValueError as e: raise ValueError(f'{base}: {e}') from e
            if ' '.join(text.split())!=' '.join(' '.join(pieces).split()): raise ValueError(f'Text changed: {base}')
            if len(pieces)>1: splits.append({'section_id':base,'parts':len(pieces)})
            offset=0; period='1872' if name=='origin' else ('1876' if code=='su' else '1874')
            for i,piece in enumerate(pieces,1):
                cid=base if len(pieces)==1 else f'{base}-p{i}'
                if i<len(pieces) and (piece.split()[-1].removesuffix('.') in END_ABBREVIATIONS or INITIALS.fullmatch(piece.split()[-1])): raise ValueError(f'Abbreviation at chunk end: {cid}: {piece.split()[-1]}')
                if not text.startswith(piece,offset): raise ValueError(f'Offset mismatch {cid}')
                offset+=len(piece)
                if i<len(pieces):
                    m=re.match(r'\s+',text[offset:]); gap=m[0] if m else ''; offset+=len(gap)
                    if '\n\n' not in gap:
                        kind='sentence' if piece[-1] in '.!?' else 'semicolon'
                        cuts.append({'chunk_id':cid,'kind':kind,'left':piece.split()[-12:],'right':pieces[i].split()[:12]})
                chunks.append(dict(schema_version=1,chunk_id=cid,figure_id=manifest['figure_id'],work=work,book=unit,section=section,part=None if len(pieces)==1 else i,parts_total=len(pieces),locator=f'{name.title()} ({period}), {label}'+(f' — {title}' if section else ''),text=piece,word_count=words(piece),period=period,genre='Scientific treatise',translator=None,source=provenance['gutenberg_number'],source_sha256=provenance['sha256']))
                counts[unit]+=1; work_counts[work]+=1
    payload=''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in chunks); sizes=sorted(c['word_count'] for c in chunks); n=len(sizes); median=(sizes[(n-1)//2]+sizes[n//2])/2
    report=dict(schema_version=1,total_chunks=n,section_count=section_count,word_counts=dict(min=sizes[0],median=median,p90=sizes[(9*n+9)//10-1],max=sizes[-1]),p90_method='nearest rank',split_sections=splits,chunks_sha256=hashlib.sha256(payload.encode()).hexdigest(),clean_sha256=hashes,config_sha256=hashlib.sha256((BASE/'chunking.json').read_bytes()).hexdigest(),per_work=dict(work_counts),per_unit=dict(counts),nonparagraph_splits=cuts,split_counts=dict(Counter(c['kind'] for c in cuts)))
    (BASE/'data/chunks.jsonl').write_text(payload,encoding='utf-8'); (BASE/'data/chunk_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Chunks: {n}; words min/median/p90/max: {sizes[0]}/{median:g}/{report["word_counts"]["p90"]}/{sizes[-1]}'); print(f'Split sections: {", ".join(s["section_id"] for s in splits)}'); print(f'chunks.jsonl SHA-256: {report["chunks_sha256"]}'); print(f'Nonparagraph splits: {report["split_counts"]}')

if __name__=='__main__': main()

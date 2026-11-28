"""Verify pinned sources, strip only the specified Plato apparatus, and render clean units."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, so corpus_kit imports when run as python corpora/<id>/<script>.py
from corpus_kit.source import envelope, load_pinned  # noqa: E402
from corpus_kit.spans import Ledger, balanced, contamination, nc, unique  # noqa: E402

BASE = Path('corpora/plato')
SOURCES = {
    55201: '8a30ff0c9c6384c218e28298aee340fea0fea820f81b59bb63e5f640d27a7460',
    76464: '504709b2c61926590988589a33099841fc9b1f77ae18c3cb38bf4f3d49ca1882',
    1600: '8b5c599ea734ff0f5e8d83f399dead8c796800897b107c8d53fa909f74a05d6f',
    1636: 'ce41cbe9eb5750163ef9084d253d7786d13c24968ae7f5079be3abda53114734',
}
WORKS = ('republic', 'apology', 'crito', 'phaedo', 'gorgias', 'meno', 'symposium', 'phaedrus')
ROMANS = 'I II III IV V VI VII VIII IX X'.split()
LABELS = {
    'meno': {'_Meno._': 'MENO', '_Men._': 'MENO', '_Socrates._': 'SOCRATES', '_Soc._': 'SOCRATES', '_Boy._': 'BOY', '_Any._': 'ANYTUS'},
    'crito': {'_Socrates._': 'SOCRATES', '_Soc._': 'SOCRATES', '_Crito._': 'CRITO', '_Cr._': 'CRITO'},
    'phaedo': {'_Echecrates._': 'ECHECRATES', '_Ech._': 'ECHECRATES', '_Phaedo._': 'PHAEDO', '_Phaed._': 'PHAEDO'},
    'gorgias': {'_Callicles._': 'CALLICLES', '_Cal._': 'CALLICLES', '_Socrates._': 'SOCRATES', '_Soc._': 'SOCRATES', '_Chaerephon._': 'CHAEREPHON', '_Chaer._': 'CHAEREPHON', '_Gorgias._': 'GORGIAS', '_Gor._': 'GORGIAS', '_Polus._': 'POLUS', '_Pol._': 'POLUS'},
    'symposium': {'COMPANION:': 'COMPANION', 'APOLLODORUS:': 'APOLLODORUS'},
    'phaedrus': {'SOCRATES:': 'SOCRATES', 'PHAEDRUS:': 'PHAEDRUS'},
    'apology': {}, 'republic': {},
}
REGISTER_SHA = 'fd847b5d3bee0929d31c413cff7f6d85b6eeacc9467cced7ce0213686ea69fec'
INLINE_CRITERION = 'A Greek word in parentheses is kept only where the English does not already carry the wordplay or argument it marks (mantike/manike, erromenos eros, nous/istoria/oiesis, oionoistike/oionistike, the place and parent names); a Greek gloss on a word the English already renders is a note. Every other register entry is text and is kept.'
INLINE_CHANGES = ['phr-016 (sophrosune)', 'phr-020 (imeros)', 'phr-023 (Anteros)']
INLINE_COVERED = {'sym-001': ['sym-002'], 'phr-018': ['phr-019']}
# P04 Stage B: closed list; anchors copied verbatim from the pinned Stage A register.
# Embedded to keep the recipe runnable from its four recipe files and raw sources alone.
INLINE = {1600: [('sym-001',
         's, O thou Phalerian (',
         ') man, halt! So I did',
         "(Probably\na play of words on (Greek), 'bald-headed.')"),
        ('sym-003', 'rior, come unbidden (', ') to the banquet of\nA', '(Iliad)'),
        ('sym-004', 'n\nexcuse by the way (', ').\n\nThis was the styl', '(Iliad)'),
        ('sym-006', 'omen who are\nwithin (', '). To-day let us have', '(compare Prot.)'),
        ('sym-007', 'ers and their loves (', '), they would be the ', '(compare Rep.)'),
        ('sym-009', 'd\nbe poor in spirit (', '), and that there sho', '(compare Arist. Politics)'),
        ('sym-012', 'of\nhis ancient need (', '). And the reason is ', '(compare Arist. Pol.)'),
        ('sym-013', ' the Lacedaemonians\n(', '). And if we are not ', '(compare Arist. Pol.)'),
        ('sym-015',
         'music in him before (',
         '); this also is a pro',
         '(A fragment of the\nSthenoaoea of Euripides.)'),
        ('sym-016', 'tone, as Homer says (', '),\nand strike me dumb', '(Odyssey)'),
        ('sym-018', 'Euripides would say\n(', ')) was a promise of t', '(Eurip. Hyppolytus)'),
        ('sym-019', 'iotima of Mantineia (', '), a woman wise in\nth', '(compare 1 Alcibiades)'),
        ('sym-020', 'lf as well as I can\n(', '). As you, Agathon, s', '(compare Gorgias)'),
        ('sym-021', ' Agathon, suggested (', '), I must speak\nfirst', '(supra)'),
        ('sym-023', 'e is a great spirit (', '),\nand like all spiri', '(daimon)'),
        ('sym-027',
         'ng of which I spoke (',
         ')? Will you drink wit',
         '(supra Will you have a very drunken\nman? etc.)'),
        ('sym-028', ' our wounds to heal (', ")'\n\nshall prescribe a", "(from Pope's Homer, Il.)"),
        ('sym-029', 'melodies of Olympus (', ')\nare derived from Ma', '(compare Arist. Pol.)'),
        ('sym-032', 'ys, or without them (', '); and\ntherefore I mu', '(In allusion to two proverbs.)'),
        ('sym-035', 'n, and went his way\n(', '). I will also tell, ', '(compare supra)'),
        ('sym-037', 'es, as you\ndescribe (', '), just as he is in t', '(Aristoph. Clouds)'),
        ('sym-038', 's\nin the same words (', '), so that any ignora', '(compare Gorg.)')],
 1636: [('phr-004',
         'r; the\noyster-shell (',
         ') has fallen with the',
         '(In allusion to a game in which two parties fled or pursued\n'
         'according as an oyster-shell which was thrown into the air fell with\n'
         'the dark or light side uppermost.)'),
        ('phr-008', ' inventors of names\n(', '), who would never ha', '(compare Cratylus)'),
        ('phr-016', 'rior to a sane mind (', ')\nfor the one is only', '(sophrosune)'),
        ('phr-017', 'f is as\nfollows:--\n\n(', ') The soul through al', '(Translated by Cic. Tus. Quaest.)'),
        ('phr-018',
         'ars. But the others (',
         ') receive judgment wh',
         '(The\n'
         'philosopher alone is not subject to judgment (krisis), for he has never\n'
         'lost the vision of truth.)'),
        ('phr-020', 'fore called\nemotion (', '), and is refreshed a', '(imeros)'),
        ('phr-021',
         'he growing of wings (',
         ') is a necessity to h',
         "(Or, reading pterothoiton, 'the\nmovement of wings.')"),
        ('phr-022', 'lood-red complexion (', '); the mate of insole', '(Or with grey and\nblood-shot eyes.)'),
        ('phr-023', 'mage, love for love (', ') lodging in his\nbrea', '(Anteros)'),
        ('phr-024',
         "t the 'sweet elbow'\n(",
         ') of the proverb is r',
         "(A proverb, like 'the grapes are sour,' applied to pleasures which\n"
         'cannot be had, meaning sweet things which, like the elbow, are out of\n'
         'the reach of the mouth. The promised pleasure turns out to be a long and\n'
         'tedious affair.)'),
        ('phr-025', 'e Eleatic Palamedes (', '), who has an\nart of ', '(Zeno)'),
        ('phr-026', 'erstood as a whole. (', ')\n\nSOCRATES: Yes, fri', '(Compare Charmides.)')]}

P06 = '[Footnote 1: Reading [Greek: Gu/nê| tô=| Kroi/sou tou= Ludou= progo/nô|.]'
P07_REFERENCES = ('them wherever they are found[38]:', '[38]Yes, indeed, I replied, and equally incompatible with the management')
P07_BODIES = ('[Footnote 38: Cp. _supra_, II. 368 D.]', '[Footnote 38: Making the answer of Socrates begin at [Greek: kai\\ ga\\r\npro\\s k.t.l.]]')
P08 = "[Footnote: 11: A play upon [Greek: to/kos], which means both 'offspring'\nand 'interest.']"
P09 = '[Footnote: Omitting [Greek: ei)s].]'
P10 = '(308}'
PAIRS = {7: ('the geometrician, when he is asked [7]whether', '    circle[7], will reply:'),
         8: ('the figure be such that [8]when you have produced a given side', '    of it[8], the given area'),
         9: ('    [9]corresponding to the part produced[9], then one consequence',)}
TOKEN = re.compile(r'\[\[steph (\d{1,3}[A-E]?)\]\]')
CONTAMINATION_TERMS = ['Project Gutenberg', 'Sidenote', 'Footnote', 'FOOTNOTES', 'Steph.',
    'PERSONS OF THE DIALOGUE', 'SCENE:', 'PLACE OF THE NARRATION:', 'INTRODUCTION', 'ANALYSIS',
    'Jowett', 'JOWETT', '[Illustration', 'Transcriber', 'INDEX', 'EUTHYPHRO', 'HIPPIAS',
    'ALCIBIADES', 'MENEXENUS', 'ERYXIAS', 'APPENDIX I', 'APPENDIX II', 'PREFACE.', 'CONTENTS.',
    'The scene is laid in the house of Cephalus', 'Produced by Sue Asscher', 'CLARENDON PRESS',
    'OXFORD UNIVERSITY PRESS', '_On the Ideas of Plato._', '_The Myths of Plato._',
    'On the Decline of Greek Literature', 'ON THE DECLINE OF GREEK LITERATURE', P10, '(compare', '(Compare', '(supra', '(Iliad)',
    '(Odyssey)', '(Or,', '(Or ', 'Translated by Cic']
CONTAMINATION_PATTERNS = {
    'printed page marker': r'\{\d+\}', 'Stephanus inline marker': r'\*\d+[A-E]?\*',
    'numbered footnote marker': r'\[\d+\]', 'margin page marker': r'(?m)\S {2,}\d+[ \t]*$',
    'unnormalised speaker label': r'(?m)^\s*_[A-Za-z]+\._',
    'book heading': r'(?m)^BOOK [IVX]+\.?$',
    'dialogue heading': r'(?m)^(?:THE REPUBLIC\.|MENO\.|APOLOGY\.|CRITO\.|PHAEDO\.|GORGIAS\.|SYMPOSIUM|PHAEDRUS)$',
}


BRACKET_REGISTER_SHA = '79cf49e5cf8a8f7cac5ff4e4069866f755e2a6613543eaceb77281b6ed041fe6'
BRACKET_CRITERION = "Square-bracketed words that render what the Greek leaves implicit are translation and are kept; Plato's own Greek words that a pun turns on are kept; identifications, alternative renderings, 'i. e.' glosses and explanations of a pun are translator commentary and are stripped."
# P13: pinned register anchors embedded to preserve the four-file recipe.
BRACKETS = [('brk-01', 55201, 'republic-02', 'ifice not a common [', '] pig, but some huge', '[Eleusinian]', True),
 ('brk-02',
  55201,
  'republic-03',
  "of Tiresias:--\n\n  '[",
  '] that he alone\n  sh',
  '[To him even after death did Persephone grant mind,]',
  False),
 ('brk-03',
  55201,
  'republic-06',
  'ing\nupon the name ([',
  ']). May I suppose th',
  '[Greek: ou)rano/s, o(rato/s]',
  False),
 ('brk-04',
  55201,
  'republic-08',
  'tion and evolution [',
  '] obtaining three in',
  '[_or_ squared\nand cubed]',
  True),
 ('brk-05', 55201, 'republic-09', 'the son of Ariston [', '] has decided that t', '[the\nbest]', True),
 ('brk-06', 55201, 'republic-10', 'econd. The largest\n[', '] is spangled, and t', '[or fixed stars]', True),
 ('brk-07', 55201, 'republic-10', 'd, and the seventh [', '] is brightest; the\n', '[or sun]', True),
 ('brk-08', 55201, 'republic-10', 'ghtest; the\neighth [', '] *617A* coloured by', '[or moon]', True),
 ('brk-09',
  55201,
  'republic-10',
  'e second and fifth [',
  '] are in colour like',
  '[Saturn and Mercury]',
  True),
 ('brk-10', 55201, 'republic-10', 'eceding; the third [', '] has the whitest li', '[Venus]', True),
 ('brk-11', 55201, 'republic-10', ' light;\nthe fourth [', '] is reddish; the si', '[Mars]', True),
 ('brk-12', 55201, 'republic-10', 'reddish; the sixth [', '] is in whiteness se', '[Jupiter]', True),
 ('brk-13',
  76464,
  'meno',
  ', then\n      they’ [',
  '] ‘would have\n      ',
  '[who were able to perform this feat]',
  False),
 ('brk-14', 76464, 'meno', ' virtue was wisdom [', '], then, as we\n    t', '[or knowledge]', True),
 ('brk-15', 76464, 'gorgias', 'he may,\n    as you [', '] suggest, defer the', '[Chaerephon]', True),
 ('brk-16', 76464, 'gorgias', ' of discourse, not [', '] about odd\n    and ', '[like arithmetic]', False),
 ('brk-17',
  76464,
  'gorgias',
  'captious questions—[',
  '] For\n    will any o',
  '[do\n    you seriously believe that there is any truth in all this?]',
  False),
 ('brk-18',
  76464,
  'gorgias',
  'good\n    and evil? [',
  ']\n\n    _Cal._ I real',
  '[i. e. in having more pleasure and more pain.]',
  True)]

def acquire(n):
    s = load_pinned(BASE / f'data/raw/pg{n}.txt', f'https://www.gutenberg.org/cache/epub/{n}/pg{n}.txt', SOURCES[n])
    if '[[' in s:
        raise ValueError(f'Reserved marker in source {n}')
    return s


def boundary(s, p, lo, hi):
    """Use exact contextual markers for recurring apparatus and ledger boundaries.

    The structural markers and all exceptions themselves are explicit literals;
    for repeated grammar-defined spans record a unique context and offset.
    """
    for width in (40, 80, 160, 320, 640, 1280):
        x, y = max(lo, p - width // 2), min(hi, p + width // 2)
        marker = s[x:y]
        if not marker:
            continue
        try:
            q = unique(s, marker, lo, hi)
        except ValueError:
            continue
        if q != x:
            raise ValueError('Exact boundary position mismatch')
        return marker, p - x
    raise ValueError(f'No unique contextual boundary at offset {p}')


def add(ledger, a, b, category, lo=0, hi=None, **extra):
    s = ledger.s
    hi = len(s) if hi is None else hi
    if not lo <= a < b <= hi:
        raise ValueError(f'Invalid span {category}: {a}:{b} in {lo}:{hi}')
    start_marker, start_delta = boundary(s, a, lo, hi)
    end_marker, end_delta = boundary(s, b, lo, hi)
    ledger.add(a, b, category)
    record = ledger.entries[-1][2]
    record.update(start_marker=start_marker, end_marker=end_marker,
                  start_marker_offset=start_delta, end_marker_offset=end_delta,
                  search_region=[lo, hi], source_offsets=[a, b], **extra)
    return record


def line_heading(s, marker, lo, hi):
    return unique(s, '\n' + marker + '\n', lo, hi) + 1


def para_end(s, p, hi):
    m = re.search(r'\n[ \t]*\n', s[p:hi])
    return p + m.start() if m else hi


def unit(uid, label, work, a, b):
    return dict(id=uid, label=label, work=work, start=a, end=b, markers=[],
                persons_block=None, headings=[], defects=[], insertion_candidates=[],
                footnotes={'marker_occurrences': 0, 'distinct_numbers': [], 'body_count': 0},
                sidenote_spans=0, sidenote_labels=0, page_markers=0, malformed_page_markers=0,
                speaker_labels={}, printed_speaker_labels={}, inline_note_ids=[])


def defect(u, code, text, ledger, a, **extra):
    u['defects'].append(dict(id=code, unit=u['id'], exact_marker=text, lf_line=ledger.line(a), **extra))


def persons(s, ledger, u, a, b):
    u['persons_block'] = s[a:b]
    add(ledger, a, b, 'persons_block', u['start'], u['end'], unit=u['id'])
    u['headings'].append({'kind': 'persons_block', 'text': s[a:b], 'lf_line_range': [ledger.line(a), ledger.line(b-1)]})


def heading(s, ledger, u, a, b, category):
    add(ledger, a, b, category, u['start'], u['end'], unit=u['id'])
    u['headings'].append({'kind': category, 'text': s[a:b], 'lf_line_range': [ledger.line(a), ledger.line(b-1)]})


def republic_regions(s, ledger, start, end):
    pre = line_heading(s, 'PREFACE.', start, end)
    intro = line_heading(s, 'INTRODUCTION AND ANALYSIS.', pre, end)
    title = line_heading(s, 'THE REPUBLIC.', intro, end)
    index = line_heading(s, 'INDEX.', title, end)
    trans = line_heading(s, "Transcriber's Note", index, end)
    book_starts = [line_heading(s, 'BOOK ' + r + ('' if i == 1 else '.'), title, index) for i, r in enumerate(ROMANS, 1)]
    if book_starts != sorted(book_starts):
        raise ValueError('Republic book order')
    add(ledger, start, pre, 'title_matter')
    add(ledger, pre, intro, 'preface')
    add(ledger, intro, title, 'introduction_analysis')
    add(ledger, title, book_starts[0], 'dialogue_title')
    add(ledger, index, trans, 'index')
    add(ledger, trans, end, 'transcriber_note')
    units = []
    for i, (a, b) in enumerate(zip(book_starts, book_starts[1:] + [index]), 1):
        label = f'Republic {ROMANS[i-1]}'
        u = unit(f'republic-{i:02d}', label, 'republic', a, b)
        h = a + len('BOOK ' + ROMANS[i-1] + ('' if i == 1 else '.'))
        heading(s, ledger, u, a, h, 'book_heading')
        if i == 1:
            p = unique(s, '                      _PERSONS OF THE DIALOGUE._', h, b)
            e = unique(s, 'The scene is laid in the house of Cephalus', p, b)
            persons(s, ledger, u, p, e)
            q = para_end(s, e, b)
            add(ledger, e, q, 'opening_note', a, b, unit=u['id'])
            first = unique(s, 'I went down yesterday to the Piraeus with Glaucon the son of Ariston, that\nI might offer up my prayers to the goddess[1]; and also because I wanted\nto see in what manner they would celebrate the festival, which was a new\nthing.', q, b)
            u['opening_sentence_source'] = s[first:para_end(s, first, b)].split('thing.', 1)[0] + 'thing.'
        units.append(u)
    return units, (intro, title), index


VOL_ORDER = ('Meno', 'Euthyphro', 'Apology', 'Crito', 'Phaedo', 'Gorgias',
             'Lesser Hippias', 'Alcibiades I', 'Menexenus', 'Alcibiades II', 'Eryxias')
VOL_NOTE_START = (1, 13, 14, 17, 23, 29, 53, 55, 62, 65, 77)
VOL_NOTE_END = (12, 13, 16, 22, 28, 52, 54, 61, 64, 76, 78)


def volume_regions(s, ledger, start, end):
    trans_start = unique(s, '=Transcriber’s Note=', start, end)
    title_start = unique(s, '    THE\n\n    DIALOGUES OF PLATO\n\n    _JOWETT_', trans_start, end)
    contents = line_heading(s, 'CONTENTS.', title_start, end)
    trans_end = line_heading(s, 'Transcriber’s Notes', contents, end)
    app1 = line_heading(s, 'APPENDIX I.', contents, trans_end)
    app2 = line_heading(s, 'APPENDIX II.', app1, trans_end)
    intros = {}
    for w in VOL_ORDER:
        if w == 'Alcibiades II':
            marker = '\nALCIBIADES II.\n\n_PERSONS OF THE DIALOGUE._'
        else:
            marker = '\n' + w.upper() + '.\n\n\nINTRODUCTION.\n'
        intros[w] = unique(s, marker, contents, trans_end) + 1
    add(ledger, start, trans_start, 'front_matter')
    add(ledger, trans_start, title_start, 'transcriber_note')
    add(ledger, title_start, contents, 'title_matter')
    add(ledger, contents, intros['Meno'], 'contents')
    add(ledger, app1, app2, 'excluded_appendix_i')
    add(ledger, app2, trans_end, 'excluded_appendix_ii')
    add(ledger, trans_end, end, 'transcriber_note')
    next_work = {w: intros[v] for w, v in zip(VOL_ORDER, VOL_ORDER[1:])}
    next_work.update({'Gorgias': app1, 'Menexenus': app2, 'Eryxias': trans_end})
    blocks = []
    for w, first, last in zip(VOL_ORDER, VOL_NOTE_START, VOL_NOTE_END):
        terminal = next_work[w]
        p = unique(s, f'\nFOOTNOTES\n\n[{first}] ', intros[w], terminal) + 1
        refs = list(re.finditer(r'(?m)^\[(\d+)\] ', s[p:terminal]))
        numbers = [int(m[1]) for m in refs]
        if numbers != list(range(first, last + 1)):
            raise ValueError(f'FOOTNOTES sequence {w}: {numbers}')
        notes = []
        for j, m in enumerate(refs):
            a = p + m.start()
            b = p + refs[j+1].start() if j+1 < len(refs) else terminal
            mark = f'\n[{m[1]}] '
            if unique(s, mark, p, terminal) + 1 != a:
                raise ValueError(f'FOOTNOTES body marker position {m[1]}')
            notes.append(dict(number=int(m[1]), lf_line_range=[ledger.line(a), ledger.line(b-1)], body=s[a:b].strip()))
        blocks.append(dict(work=w, start=p, end=terminal, notes=notes))
    all_bodies = {note['number']: (block['work'], note) for block in blocks for note in block['notes']}
    if list(all_bodies) != list(range(1, 79)):
        raise ValueError('Whole-file footnote body bijection')
    refs = []
    for m in re.finditer(r'\[(\d+)\]', s[start:end]):
        a = start + m.start()
        if any(block['start'] <= a < block['end'] for block in blocks):
            continue
        refs.append((a, int(m[1])))
    firsts = list(dict.fromkeys(v for _, v in refs))
    if firsts != list(range(1, 79)):
        raise ValueError(f'Whole-file footnote first occurrences: {firsts}')
    repeats = {k: v for k, v in Counter(v for _, v in refs).items() if v != 1}
    if repeats != {7: 2, 8: 2, 9: 2, 69: 2, 70: 2, 71: 2}:
        raise ValueError(f'Whole-file unexpected footnote repetition: {repeats}')
    # Verify each distinct reference belongs to its corresponding work's source region.
    for a, num in refs:
        w = all_bodies[num][0]
        # Appendix II introduction is part of the excluded Alcibiades II region.
        lo = app2 if w == 'Alcibiades II' else intros[w]
        hi = next_work[w]
        if not lo <= a < hi:
            raise ValueError(f'Footnote reference {num} outside {w}')
    units = []
    for w in ('Meno', 'Apology', 'Crito', 'Phaedo', 'Gorgias'):
        block = next(x for x in blocks if x['work'] == w)
        a0, b = intros[w], block['start']
        start_marker = '\n' + w.upper() + '.\n' + ('\n[Sidenote: _Apology._]' if w == 'Apology' else '\n_PERSONS OF THE DIALOGUE._')
        a = unique(s, start_marker, a0, b) + 1
        u = unit(w.lower(), w, w.lower(), a, b)
        # Explicit appended essays are separately accounted where printed as headings.
        essay_markers = {'Meno': ['_On the Ideas of Plato._'], 'Gorgias': ['_The Myths of Plato._']}.get(w, [])
        points = [line_heading(s, m, a0, a) for m in essay_markers]
        for k, (x, y) in enumerate(zip([a0] + points, points + [a])):
            add(ledger, x, y, 'introduction_analysis' if k == 0 else 'appended_essay', a0, a, work=w)
        heading(s, ledger, u, a, a+len(w.upper()+'.'), 'dialogue_title')
        if w != 'Apology':
            p = unique(s, '_PERSONS OF THE DIALOGUE._', a, b)
            pp = unique(s, '\n\n', p, p+len('_PERSONS OF THE DIALOGUE._')+2) + 2
            q = para_end(s, pp, b)
            persons(s, ledger, u, p, q)
            for m in re.finditer(r'(?m)^(?:SCENE:|PLACE OF THE NARRATION:)[^\n]*', s[q:b]):
                heading(s, ledger, u, q+m.start(), q+m.end(), 'scene_heading')
        add(ledger, b, block['end'], 'footnotes_section', b, block['end'], work=w)
        intro_refs = [v for x,v in refs if a0 <= x < a]
        body_refs = [v for x,v in refs if a <= x < b]
        intro_distinct = list(dict.fromkeys(intro_refs))
        body_distinct = list(dict.fromkeys(body_refs))
        if set(intro_distinct) & set(body_distinct) or sorted(intro_distinct+body_distinct) != [note['number'] for note in block['notes']]:
            raise ValueError(f'Introduction/dialogue reference attribution {w}')
        if w == 'Meno':
            for num, markers in PAIRS.items():
                positions = []
                for marker in markers:
                    p = unique(s, marker, a, b)
                    positions.extend(p+m.start() for m in re.finditer(r'\['+str(num)+r'\]', marker))
                if positions != [x for x,v in refs if v == num]:
                    raise ValueError(f'P02 pair markers {num}')
            defect(u, 'P02', '[7]...[7], [8]...[8], [9]...[9]', ledger, next(x for x,v in refs if v==7), handling='Authorised paired markers, two reference occurrences for each single body; enclosed text retained.', pairs=PAIRS)
        elif len(body_refs) != len(body_distinct):
            raise ValueError(f'Unexpected repeated reference in {w}')
        u['footnotes'] = dict(marker_occurrences=len(body_refs), distinct_numbers=body_distinct,
                              body_count=len(body_distinct), introduction_marker_occurrences=len(intro_refs),
                              introduction_distinct_numbers=intro_distinct, introduction_body_count=len(intro_distinct),
                              total_work_body_count=len(block['notes']), matched_bodies=block['notes'])
        units.append(u)
    add(ledger, intros['Euthyphro'], intros['Apology'], 'excluded_dialogue', intros['Euthyphro'], intros['Apology'], work='Euthyphro')
    whole = dict(body_count=len(all_bodies), reference_occurrences=len(refs), distinct_numbers=firsts,
                 repeated_numbers=repeats, bijection_passed=True, sections=[{'work': b['work'], 'numbers': [x['number'] for x in b['notes']]} for b in blocks])
    return units, whole, trans_end


SINGLE_REGIONS = {
    1600: ('symposium', 'Concerning the things about which you ask to be informed I believe that', 'In the evening he retired to rest at\nhis own home.'),
    1636: ('phaedrus', 'SOCRATES: My dear Phaedrus, whence come you, and whither are you going?', 'SOCRATES: Let us go.'),
}


def single_regions(n, s, ledger, start, end):
    work, first, last = SINGLE_REGIONS[n]
    intro = line_heading(s, 'INTRODUCTION.', start, end)
    first_offset = unique(s, first, intro, end)
    b = unique(s, last, first_offset, end) + len(last)
    title_marker = '\n' + work.upper() + '\n\n\nPERSONS OF THE DIALOGUE:'
    a = unique(s, title_marker, intro, first_offset) + 1
    add(ledger, start, intro, 'title_matter')
    if n==1636:
        essay=line_heading(s,'ON THE DECLINE OF GREEK LITERATURE.',intro,a)
        add(ledger,intro,essay,'introduction_analysis',intro,a)
        add(ledger,essay,a,'appended_essay',intro,a)
    else:
        add(ledger,intro,a,'introduction_analysis')
    u = unit(work, work.title(), work, a, b)
    heading(s, ledger, u, a, a+len(work.upper()), 'dialogue_title')
    p = unique(s, 'PERSONS OF THE DIALOGUE:', a, first_offset)
    q = para_end(s, p, first_offset)
    persons(s, ledger, u, p, q)
    scene = unique(s, '\nSCENE:', q, first_offset)+1
    e = para_end(s, scene, first_offset)
    heading(s, ledger, u, scene, e, 'scene_heading')
    add(ledger, b, end, 'back_matter')
    spans = []
    for ident, sm, em, text in INLINE[n]:
        x = unique(s, sm, first_offset, b) + len(sm) - 1
        y = unique(s, em, first_offset, b) + 1
        if s[x:y] != text or balanced(s, x, '(', ')', b) != y:
            raise ValueError(f'P04 register span mismatch {ident}')
        spans.append((x, y))
        add(ledger, x, y, 'inline_note', first_offset, b, unit=work, register_id=ident,
            covered_register_ids=INLINE_COVERED.get(ident, []), register_start_marker=sm, register_end_marker=em)
        u['inline_note_ids'].append(ident)
    if len(spans) != (22 if n == 1600 else 12) or any(x[1] > y[0] for x,y in zip(spans, spans[1:])):
        raise ValueError(f'P04 physical strip count or overlap {work}')
    return [u]


def in_strip(ledger, p):
    return any(a <= p < b for a,b,_ in ledger)


def bracket_apparatus(n, s, ledger, u):
    a,b = u['start'],u['end']
    foot_bodies = []
    pos = a
    pat = re.compile(r'\[(?:Sidenote:|Sidenote;|Illustration|Footnote(?: |:))')
    while True:
        m = pat.search(s,pos,b)
        if not m:
            break
        x = m.start()
        if in_strip(ledger,x):
            pos = m.end()
            continue
        category = 'sidenote' if m[0].startswith('[Sidenote') else ('illustration' if m[0].startswith('[Illustration') else 'footnote')
        if category == 'footnote' and n != 55201:
            raise ValueError(f'Unexpected bracketed footnote {u["id"]}: {ledger.line(x)}')
        if n == 55201 and u['id'] == 'republic-02' and s.startswith(P06,x):
            if unique(s,P06,a,b) != x:
                raise ValueError('P06 marker position')
            y = x+len(P06)
            if s[y:y+1] != '\n':
                raise ValueError('P06 is not a complete line')
            defect(u,'P06',P06,ledger,x,handling='Missing outer closing bracket; strip exact line, no correction.', number=1)
        else:
            y = balanced(s,x,'[',']',b)
        if category == 'footnote':
            text = s[x:y]
            nm = re.match(r'\[Footnote (\d+):',text)
            if nm:
                num = int(nm[1])
            elif u['id']=='republic-06' and text==P08 and unique(s,P08,a,b)==x:
                num=11
                defect(u,'P08',P08,ledger,x,handling='Extra colon in label; exact exception matched to reference 11.',number=11)
            elif u['id']=='republic-10' and text==P09 and unique(s,P09,a,b)==x:
                num=1
                defect(u,'P09',P09,ledger,x,handling='Missing printed number; authorised exact correspondence to reference 1.',number=1)
            else:
                raise ValueError(f'Unrecognised footnote label {u["id"]}: {text[:100]}')
            foot_bodies.append((x,y,num))
        if m[0]=='[Sidenote;':
            exact='[Sidenote; At twenty years of age the disciples will begin to be taught\nthe correlation of the sciences.]'
            if u['id']!='republic-07' or s[x:y]!=exact or unique(s,exact,a,b)!=x: raise ValueError('Unexpected malformed sidenote')
            defect(u,'P12',s[x:y],ledger,x,status='authorised',lf_line_range=[ledger.line(x),ledger.line(y-1)],handling='Mechanical delimiter typo: semicolon instead of colon; balanced sidenote stripped under existing rule.')
        if category == 'sidenote':
            u['sidenote_spans'] += 1
            u['sidenote_labels'] += s[x:y].count('[Sidenote:')+s[x:y].count('[Sidenote;')
        add(ledger,x,y,category,a,b,unit=u['id'])
        pos=y
    return foot_bodies


def republican_notes(s, ledger, u, bodies):
    a,b=u['start'],u['end']
    refs=[]
    for m in re.finditer(r'\[(\d+)\]',s[a:b]):
        x=a+m.start();y=a+m.end()
        if not in_strip(ledger,x):
            refs.append((x,y,int(m[1])))
    refnums=[v for _,_,v in refs]; bodynums=[v for _,_,v in bodies]
    if u['id']=='republic-03':
        expected=list(range(1,39))+[38,39,40]
        exact_refs=[]
        for marker in P07_REFERENCES:
            p=unique(s,marker,a,b)
            exact_refs.append(p+marker.index('[38]'))
        exact_bodies=[unique(s,marker,a,b) for marker in P07_BODIES]
        if exact_refs != [x for x,_,v in refs if v==38] or exact_bodies != [x for x,_,v in bodies if v==38]:
            raise ValueError('P07 duplicate footnote contextual mismatch')
        defect(u,'P07',P07_REFERENCES[1],ledger,exact_refs[1],handling='Two distinct references and two distinct bodies printed as 38; preserved numbering.', reference_markers=P07_REFERENCES, body_markers=P07_BODIES)
    else:
        expected=list(range(1,len(bodies)+1))
    if refnums != expected or bodynums != expected:
        raise ValueError(f'Republic footnote sequence {u["id"]}: markers {refnums}; bodies {bodynums}; expected {expected}')
    for ref,body in zip(refs,bodies):
        if not ref[0] < body[0]:
            raise ValueError(f'Footnote body precedes reference: {u["id"]} {ref[2]}')
        add(ledger,ref[0],ref[1],'footnote_marker',a,b,unit=u['id'],number=ref[2],matched_body_line=ledger.line(body[0]))
    u['footnotes']=dict(marker_occurrences=len(refs),distinct_numbers=list(dict.fromkeys(refnums)),body_count=len(bodies),printed_reference_sequence=refnums,printed_body_sequence=bodynums,matched_bodies=[dict(number=num,lf_line_range=[ledger.line(x),ledger.line(y-1)],text=s[x:y]) for x,y,num in bodies])


def locator_key(v):
    return (int(v.rstrip('ABCDE')), ' ABCDE'.index(v[-1]) if v[-1] in 'ABCDE' else 0)


def unit_apparatus(n,s,ledger,u):
    a,b=u['start'],u['end']
    bodies=bracket_apparatus(n,s,ledger,u)
    if n==55201:
        republican_notes(s,ledger,u,bodies)
        for m in re.finditer(r'\{\d+\}',s[a:b]):
            x,y=a+m.start(),a+m.end()
            if not in_strip(ledger,x):
                add(ledger,x,y,'page_marker',a,b,unit=u['id']);u['page_markers']+=1
        if u['id']=='republic-10':
            x=unique(s,P10,a,b)
            add(ledger,x,x+len(P10),'page_marker',a,b,unit=u['id'])
            u['page_markers']+=1;u['malformed_page_markers']+=1
            defect(u,'P10',P10,ledger,x,handling='Malformed printed-page marker removed exactly, not corrected.')
        for m in re.finditer(r'\*\d{1,3}[A-E]\*|\*Ed\. Steph\. 327\*',s[a:b]):
            x,y=a+m.start(),a+m.end()
            if in_strip(ledger,x):
                continue
            if m[0]=='*Ed. Steph. 327*':
                if u['id']!='republic-01' or unique(s,m[0],a,b)!=x:
                    raise ValueError('P05 opening marker position')
                v='327'
                defect(u,'P05',m[0],ledger,x,handling='Additional printed page-only marker form; 327 before 327B; never infer 327A.')
            else:
                v=m[0][1:-1]
            add(ledger,x,y,'stephanus',a,b,unit=u['id'],value=v)
            u['markers'].append((x,v,x,y))
    elif n==76464:
        actual=[]
        for m in re.finditer(r'\[(\d+)\]',s[a:b]):
            x,y=a+m.start(),a+m.end()
            if not in_strip(ledger,x):
                add(ledger,x,y,'footnote_marker',a,b,unit=u['id'],number=int(m[1]));actual.append(int(m[1]))
        if len(actual)!=u['footnotes']['marker_occurrences'] or list(dict.fromkeys(actual))!=u['footnotes']['distinct_numbers']:
            raise ValueError(f'Footnote marker census changed {u["id"]}')
        for m in re.finditer(r'(?m)^[^\n]+$',s[a:b]):
            x=a+m.start();line=m[0]
            p=re.search(r'=Steph\.= +(?P<first>\d{1,3})[ \t]*$',line)
            if p:
                v=p['first'];offset=p.start()
            else:
                p=re.search(r'\S {2,}(?P<page>\d{1,3})[ \t]*$',line)
                if not p:
                    continue
                v=p['page'];offset=p.start('page')
            q=x+offset;r=x+p.end()
            if in_strip(ledger,q):
                continue
            if in_strip(ledger,x):
                raise ValueError(f'Margin marker against stripped line {u["id"]} {ledger.line(x)}')
            add(ledger,q,r,'stephanus',a,b,unit=u['id'],value=v,emitted_at_source_offset=x)
            u['markers'].append((x,v,q,r))
        if u['id']=='meno':
            if not u['markers'] or u['markers'][0][1]!='71' or s[u['markers'][0][2]:u['markers'][0][3]].strip()!='=Steph.= 71':
                raise ValueError('P01 Meno first marker')
            x=u['markers'][0][2]
            defect(u,'P01','our lot! my dear Meno. Here at Athens there is a dearth    =Steph.= 71',ledger,x,handling='No marker at opening; locator beginning until printed 71; no inferred page 70.')
            if unique(s,u['defects'][-1]['exact_marker'],a,b)+u['defects'][-1]['exact_marker'].index('=Steph.')!=x:
                raise ValueError('P01 exact first marker mismatch')
        elif not u['markers'] or not s[u['markers'][0][2]:].startswith('=Steph.='):
            raise ValueError(f'Initial Stephanus marker {u["id"]}')
    u['markers'].sort()
    for prev,cur in zip(u['markers'],u['markers'][1:]):
        if locator_key(cur[1]) < locator_key(prev[1]):
            if u['id']=='republic-08' and (prev[1],cur[1])==('561E','561A'):
                if unique(s,'*561E*',a,b)!=prev[2] or unique(s,'*561A* Let him then be set over against democracy;',a,b)!=cur[2]:
                    raise ValueError('561E/561A exact marker mismatch')
                defect(u,'561E-to-561A','*561A* Let him then be set over against democracy;',ledger,cur[2],handling='Authorised decreasing printed transition 561E to 561A; never corrected.',previous_marker='*561E*')
            else:
                raise ValueError(f'Decreasing Stephanus {u["id"]}: {prev[1]} -> {cur[1]} at line {ledger.line(cur[2])}')
    if u['id']=='republic-08' and sum(d['id']=='561E-to-561A' for d in u['defects'])!=1:
        raise ValueError('Authorised Stephanus defect absent')
    # P13: validate the complete closed register against this unit before removal.
    registered = {}
    u['bracket_note_ids'] = []
    for ident, pg, uid, sm, em, text, remove in BRACKETS:
        if pg != n or uid != u['id']:
            continue
        x = unique(s, sm, a, b) + len(sm) - 1
        y = unique(s, em, a, b) + 1
        if s[x:y] != text or balanced(s, x, '[', ']', b) != y or any(l<y and r>x for l,r,_ in ledger):
            raise ValueError(f'P13 register span mismatch {ident}')
        registered[(x,y)] = (ident, remove)
    # Record all surviving square-bracketed spans, with nesting respected.
    pos=a
    while True:
        x=s.find('[',pos,b)
        if x<0:break
        covering=next(((l,r) for l,r,_ in ledger if l<=x<r),None)
        if covering:
            pos=covering[1];continue
        y=balanced(s,x,'[',']',b)
        if any(l<y and r>x for l,r,_ in ledger):
            raise ValueError(f'Insertion candidate overlaps apparatus {u["id"]} {ledger.line(x)}')
        if (x,y) not in registered:
            raise ValueError(f'Unregistered insertion candidate {u["id"]} {ledger.line(x)}')
        ident, remove = registered.pop((x,y))
        if remove:
            add(ledger,x,y,'bracket_note',a,b,unit=u['id'],register_id=ident)
            u['bracket_note_ids'].append(ident)
        else:
            u['insertion_candidates'].append(dict(id=ident,text=s[x:y],lf_line_range=[ledger.line(x),ledger.line(y-1)]))
        pos=y
    if registered:
        raise ValueError(f'P13 unmatched registered spans {u["id"]}: {registered}')


def render_unit(n,s,ledger,u):
    a,b=u['start'],u['end']
    strips=sorted((x,y,r) for x,y,r in ledger if a<=x<b)
    events={}
    for p,v,x,y in u['markers']:
        events.setdefault(p,[]).append(v)
    # Source-character map for labels and joins; None is a generated token.
    chars=[];offsets=[];cursor=a
    def keep(lo,hi):
        for p in range(lo,hi):
            for v in events.get(p,[]):
                token=f'[[steph {v}]] '
                chars.extend(token);offsets.extend([None]*len(token))
            chars.append(s[p]);offsets.append(p)
    for x,y,r in strips:
        if x<cursor or y>b:
            raise ValueError(f'Overlapping strip {u["id"]}: {r}')
        keep(cursor,x)
        if x in events:
            for v in events[x]:
                token=f'[[steph {v}]] '
                chars.extend(token);offsets.extend([None]*len(token))
        if any(x<p<y for p in events):
            raise ValueError('Stephanus insertion lies inside removed span')
        cursor=y
    keep(cursor,b)
    t=''.join(chars)
    if n==76464 and re.search(r'(?m)\S {2,}\d{1,3}[ \t]*$',TOKEN.sub('',t)):
        raise ValueError(f'Margin page marker survives pre-flatten rendering: {u["id"]}')
    # At a deletion join only, remove leftover whitespace immediately before
    # punctuation. Existing paragraph boundaries are not collapsed into prose.
    joins=[(x,y) for x,y,r in strips if r['category'] in ('inline_note','bracket_note','footnote','footnote_marker','page_marker','sidenote','illustration')]
    for m in reversed(list(re.finditer(r'\s+[,;:.?!)]',t))):
        x,y=m.start(),m.end()-1
        if '\n\n' in t[x:y] or offsets[y] is None:
            continue
        l=x-1
        if l<0 or offsets[l] is None:
            continue
        if any(offsets[l]<end and start<offsets[y] for start,end in joins):
            for j in range(x,y):chars[j]=''
    # Preserve offset correspondence after whitespace cleanup.
    kept=[(ch,off) for ch,off in zip(chars,offsets) if ch!='']
    t=''.join(ch for ch,_ in kept);offsets=[off for _,off in kept]
    paragraphs=[];pending=[];counts=Counter();printed_counts=Counter();synthetic_label_chars=0
    labelpat=re.compile(r'_[A-Za-z]+\._' if n==76464 else r'[A-Z]+:')
    for m in re.finditer(r'\S(?:.*?)(?=\n[ \t]*\n|\Z)',t,re.S):
        p=m.group().rstrip()
        # A token can precede a label when the printed margin number is against
        # its line; token-only apparatus paragraphs join the following paragraph.
        if not TOKEN.sub('',p).strip():
            pending.extend(x[0] for x in TOKEN.finditer(p));continue
        prefix=re.match(r'(?:\[\[steph \d{1,3}[A-E]?\]\]\s*)*',p)
        q=prefix.end()
        lm=labelpat.match(p,q) if n!=55201 else None
        if lm:
            old=lm[0]
            if old not in LABELS[u['work']]:
                raise ValueError(f'Unmapped speaker label {u["id"]}: {old}')
            normal=LABELS[u['work']][old]+':'
            counts[normal[:-1]]+=1;printed_counts[old]+=1
            if old!=normal:
                x=offsets[m.start()+q];y=offsets[m.start()+lm.end()-1]+1
                if s[x:y]!=old:
                    raise ValueError(f'Label source offset mismatch {u["id"]}: {old}')
                add(ledger,x,y,'speaker_label',a,b,unit=u['id'],source_label=old,replacement=normal,generated_non_whitespace_chars=nc(normal))
                p=p[:q]+normal+' '+p[lm.end():].lstrip()
        flat=' '.join(p.split())
        if pending:
            flat=' '.join(pending)+' '+flat;pending=[]
        paragraphs.append(flat)
    if pending:
        raise ValueError(f'Trailing orphan Stephanus token {u["id"]}: {pending}')
    clean='\n\n'.join(paragraphs)
    plain='\n\n'.join(' '.join(TOKEN.sub('',p).split()) for p in paragraphs)
    if not plain.strip():
        raise ValueError(f'Empty unit {u["id"]}')
    marker_values=[m[1] for m in TOKEN.finditer(clean)]
    expected=[v for _,v,_,_ in u['markers']]
    if marker_values!=expected:
        raise ValueError(f'Rendered marker sequence {u["id"]}')
    if u['id']=='symposium' and '(as Euripides would say)' not in plain:
        raise ValueError('P04 inner-note join mismatch')
    replacements=[r for x,y,r in ledger if a<=x<b and r['category']=='speaker_label']
    synthetic_label_chars=sum(nc(r['replacement']) for r in replacements)
    u['label_replacements']=replacements
    if any(r['generated_non_whitespace_chars']!=nc(r['replacement']) for r in replacements):
        raise ValueError(f'Generated label character mismatch: {u["id"]}')
    # Stronger than character counts: the complete retained non-whitespace
    # character sequence must match a direct reconstruction from the ledger.
    reconstructed=[]; cursor=a
    for x,y,r in sorted((x,y,r) for x,y,r in ledger if a<=x<b):
        if x<cursor or y>b: raise ValueError(f'Invalid reconstruction span {u["id"]}')
        reconstructed.append(s[cursor:x])
        if r['category']=='speaker_label': reconstructed.append(r['replacement'])
        cursor=y
    reconstructed.append(s[cursor:b])
    if ''.join(''.join(reconstructed).split())!=''.join(plain.split()):
        raise ValueError(f'Retained character sequence changed: {u["id"]}')
    u['retained_character_sequence_passed']=True
    rendered_nc=nc(plain);body_chars=rendered_nc-synthetic_label_chars
    stripped=sum(nc(s[x:y]) for x,y,_ in ledger if a<=x<b)
    src=nc(s[a:b]);difference=src-body_chars-stripped
    if difference:
        raise ValueError(f'Character conservation {u["id"]}: {src}-{body_chars}-{stripped}={difference}')
    u['speaker_labels']=dict(counts);u['printed_speaker_labels']=dict(printed_counts)
    u['stephanus']=dict(first=expected[0] if expected else None,last=expected[-1] if expected else None,count=len(expected),values=expected)
    u['conservation']=dict(source_non_whitespace_chars=src,clean_non_whitespace_chars=body_chars,stripped_non_whitespace_chars=stripped,difference=difference,rendered_body_non_whitespace_chars=rendered_nc,generated_normalised_label_chars=synthetic_label_chars)
    u['first_paragraph']=plain.split('\n\n')[0];u['last_paragraph']=plain.split('\n\n')[-1]
    u['paragraph_count']=len(paragraphs)
    # Full paragraphs are reported rather than guessing linguistic sentence
    # boundaries through abbreviations and quoted speech.
    return f'[[unit {u["id"]} | {u["label"]}]]\n\n{clean}\n',plain


def strip(n,s):
    ledger=Ledger(s);start,end=envelope(s)
    add(ledger,0,start,'gutenberg_header');add(ledger,end,len(s),'gutenberg_footer')
    report=dict(source_sha256=SOURCES[n],source_defects=[])
    if n==55201:
        units,intro,apparatus_end=republic_regions(s,ledger,start,end)
        report['introduction_footnotes']={'validated':False,'reason':'Introduction apparatus is unvalidated by design (P11); the region is stripped whole.'}
    elif n==76464:
        units,whole,apparatus_end=volume_regions(s,ledger,start,end)
        report['whole_file_footnotes']=whole
    else:
        units=single_regions(n,s,ledger,start,end);apparatus_end=end
    # Census only, including nested labels. Apparatus in larger excluded
    # edition regions is already covered by their single ledger entries.
    report['source_sidenote_label_count']=s[start:apparatus_end].count('[Sidenote:')+s[start:apparatus_end].count('[Sidenote;')
    report['source_sidenote_label_count_scope']='Gutenberg body up to index/back apparatus boundary; includes malformed and nested labels.'
    report['raw_sidenote_label_occurrences']={'colon':s.count('[Sidenote:'),'semicolon':s.count('[Sidenote;'),'includes_mentions_in_excluded_apparatus':True}
    files={};plain_all=[]
    for u in units:
        unit_apparatus(n,s,ledger,u)
        clean,plain=render_unit(n,s,ledger,u)
        files.setdefault(u['work'],[]).append(clean)
        plain_all.append(plain)
        report['source_defects'].extend(u['defects'])
        del u['markers']
    ledger.check_overlap()
    plain='\n\n'.join(plain_all)
    bad=contamination(plain,CONTAMINATION_TERMS)
    for name,pattern in CONTAMINATION_PATTERNS.items():
        if re.search(pattern,plain):bad.append(name)
    if n in INLINE:
        for ident,sm,em,text in INLINE[n]:
            if ' '.join(text.split()) in plain:bad.append(f'inline note {ident}')
    bracket_terms = [' '.join(text.split()) for _,_,_,_,_,text,remove in BRACKETS if remove]
    bad.extend(contamination(plain, bracket_terms))
    if bad:
        raise ValueError(f'Contamination {n}: {bad}')
    source_body=sum(u['conservation']['source_non_whitespace_chars'] for u in units)
    clean_body=sum(u['conservation']['clean_non_whitespace_chars'] for u in units)
    strips_body=sum(u['conservation']['stripped_non_whitespace_chars'] for u in units)
    stripped_all=sum(r['non_whitespace_chars'] for _,_,r in ledger)
    diff=nc(s)-clean_body-stripped_all
    if diff:
        raise ValueError(f'Whole-source conservation {n}: {nc(s)}-{clean_body}-{stripped_all}={diff}')
    label_totals=Counter()
    for u in units: label_totals[u['work']]+=sum(nc(r['replacement']) for r in u['label_replacements'])
    report.update(per_dialogue_generated_normalised_label_chars=dict(label_totals),retained_character_sequence_passed=all(u['retained_character_sequence_passed'] for u in units),units=units,stripped_spans=[r for _,_,r in ledger],strip_category_counts=dict(Counter(r['category'] for _,_,r in ledger)),
                  conservation=dict(source_non_whitespace_chars=source_body,clean_non_whitespace_chars=clean_body,stripped_non_whitespace_chars=strips_body,difference=source_body-clean_body-strips_body,rendered_body_non_whitespace_chars=sum(u['conservation']['rendered_body_non_whitespace_chars'] for u in units),generated_normalised_label_chars=sum(u['conservation']['generated_normalised_label_chars'] for u in units)),
                  whole_source_conservation=dict(source_non_whitespace_chars=nc(s),clean_non_whitespace_chars=clean_body,stripped_non_whitespace_chars=stripped_all,difference=diff),
                  contamination=dict(passed=True,matches=bad,terms=CONTAMINATION_TERMS+bracket_terms,patterns=CONTAMINATION_PATTERNS))
    if n in INLINE:
        report['inline_note_authorisation']=dict(register_sha256=REGISTER_SHA,criterion=INLINE_CRITERION,classification_changes=INLINE_CHANGES,physical_strips=[row[0] for row in INLINE[n]],covered_nested_entries={k:v for k,v in INLINE_COVERED.items() if k.startswith('sym-' if n==1600 else 'phr-')})
    report['bracket_note_authorisation']=dict(register_sha256=BRACKET_REGISTER_SHA,criterion=BRACKET_CRITERION,excluded_ids=[row[0] for row in BRACKETS if row[-1]],retained_ids=[row[0] for row in BRACKETS if not row[-1]],physical_strips=[ident for u in units for ident in u['bracket_note_ids']],status='authorised')
    return {w:'\n'.join(parts) for w,parts in files.items()},report


def main():
    register=BASE/'data/clean/parenthetical_register.json'
    if register.exists() and hashlib.sha256(register.read_bytes()).hexdigest()!=REGISTER_SHA:
        raise ValueError('Stage A parenthetical register hash mismatch')
    bracket_register=BASE/'data/clean/bracket_register.json'
    if bracket_register.exists() and hashlib.sha256(bracket_register.read_bytes()).hexdigest()!=BRACKET_REGISTER_SHA:
        raise ValueError('Stage A bracket register hash mismatch')
    texts={n:acquire(n) for n in SOURCES}
    result={n:strip(n,s) for n,s in texts.items()}
    actual=[ident for _,r in result.values() for ident in r['bracket_note_authorisation']['physical_strips']]
    retained=[z['id'] for _,r in result.values() for u in r['units'] for z in u['insertion_candidates']]
    if actual != [row[0] for row in BRACKETS if row[-1]] or retained != [row[0] for row in BRACKETS if not row[-1]]:
        raise ValueError('P13 closed list coverage or ordering mismatch')
    clean={w:t for files,_ in result.values() for w,t in files.items()}
    if set(clean)!=set(WORKS):raise ValueError(f'Dialogue set: {sorted(clean)}')
    dest=BASE/'data/clean';dest.mkdir(parents=True,exist_ok=True)
    report={str(n):r for n,(_,r) in result.items()}
    for w in WORKS:
        (dest/f'{w}.txt').write_bytes(clean[w].encode('utf-8'))
    (dest/'strip_report.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    for n,(_,r) in result.items():
        print(f'pg{n}: raw SHA-256 {SOURCES[n]}; conservation {r["conservation"]}; stripped spans {len(r["stripped_spans"])}; contamination passed')
    for w in WORKS:
        print(f'{w}.txt SHA-256: {hashlib.sha256(clean[w].encode("utf-8")).hexdigest()}')
    print('P04: 34 authorised physical inline_note strips; Stage A register unchanged if present.')
    print('P13: 13 authorised physical bracket_note strips; 5 retained; Stage A register unchanged if present.')


if __name__=='__main__':
    main()

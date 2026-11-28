"""Chunk Plato's clean dialogues from repository root without model calls."""
import bisect
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, so corpus_kit imports when run as python corpora/<id>/<script>.py
from corpus_kit.chunker import end_check, serialise, split_section, word_stats, words  # noqa: E402

BASE = Path('corpora/plato')
END_ABBREVIATIONS = frozenset(('Mr','Mrs','Dr','Prof','Rev','St','Capt','Hon','etc','vol','p','pp','viz','cf','i.e','e.g'))
WORKS = [('Republic',55201,'rep'),('Apology',76464,'apo'),('Crito',76464,'cri'),('Phaedo',76464,'pho'),('Gorgias',76464,'gor'),('Meno',76464,'men'),('Symposium',1600,'sym'),('Phaedrus',1636,'phr')]
LABELS = {'Meno':{'MENO','SOCRATES','BOY','ANYTUS'},'Crito':{'SOCRATES','CRITO'},'Phaedo':{'ECHECRATES','PHAEDO'},'Gorgias':{'CALLICLES','SOCRATES','CHAEREPHON','GORGIAS','POLUS'},'Symposium':{'COMPANION','APOLLODORUS'},'Phaedrus':{'SOCRATES','PHAEDRUS'}}
UNIT = re.compile(r'(?m)^\[\[unit ([^\n]+?) \| ([^\n]+)\]\]$')
TOKEN = re.compile(r'\[\[steph (\d{1,3}[A-E]?)\]\]')


def units(clean):
    headings=list(UNIT.finditer(clean))
    if not headings or headings[0].start()!=0:
        raise ValueError('Missing initial unit')
    for i,m in enumerate(headings):
        yield m[1],m[2],clean[m.end():headings[i+1].start() if i+1<len(headings) else len(clean)].strip()


def plain_offsets(body):
    """Remove structural tokens and map each to the next retained character.

    Paragraph breaks remain; whitespace around tokens is normalised within a
    paragraph. At a paragraph-start marker the offset is the paragraph start.
    """
    paragraphs=[]; marks=[]; starts=[]; offset=0
    for p in body.split('\n\n'):
        if not p or '\n' in p: raise ValueError('Invalid clean paragraph')
        tokens=list(TOKEN.finditer(p)); raw=TOKEN.sub('',p)
        if '[[' in raw: raise ValueError('Unexpected structural token')
        flat=' '.join(raw.split())
        if not flat: raise ValueError('Empty clean paragraph')
        for m in tokens:
            before=' '.join(TOKEN.sub('',p[:m.start()]).split())
            after=' '.join(TOKEN.sub('',p[m.end():]).split())
            pos=len(before)+(1 if before and after else 0)
            if flat[pos:]!=after: raise ValueError('Stephanus offset mismatch')
            marks.append((offset+pos,m[1]))
        starts.append(offset); paragraphs.append(flat); offset+=len(flat)+2
    plain='\n\n'.join(paragraphs)
    if [v for _,v in marks]!=[m[1] for m in TOKEN.finditer(body)]: raise ValueError('Marker loss')
    return plain,marks,starts


def main():
    config=json.loads((BASE/'chunking.json').read_text(encoding='utf-8'))
    manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    provenance={p['gutenberg_number']:p for p in manifest['source_provenance']}
    chunks=[];cuts=[];mid=[];counts=Counter();work_counts=Counter();hashes={};split_units=[]
    for work,source,code in WORKS:
        name=work.lower();raw=(BASE/f'data/clean/{name}.txt').read_bytes();hashes[name]=hashlib.sha256(raw).hexdigest()
        parsed=list(units(raw.decode('utf-8')))
        expected=[f'republic-{i:02d}' for i in range(1,11)] if work=='Republic' else [name]
        if [u[0] for u in parsed]!=expected: raise ValueError(f'Unit sequence {work}')
        for unit,label,body in parsed:
            plain,marks,starts=plain_offsets(body)
            unit_code=code+unit[-2:] if work=='Republic' else code
            try: pieces=split_section(plain,config['max_words'],frozenset(config['abbreviations']),initials=True)
            except ValueError as e: raise ValueError(f'{unit}: {e}') from e
            ids=[f'pl-{unit_code}-{i:03d}' for i in range(1,len(pieces)+1)]
            end_check(list(zip(ids,pieces)),END_ABBREVIATIONS,initials=True)
            if ' '.join(plain.split())!=' '.join(' '.join(pieces).split()): raise ValueError(f'Text changed {unit}')
            if len(pieces)>1: split_units.append({'unit':unit,'parts':len(pieces)})
            offset=0; positions=[p for p,v in marks]
            if bool(marks)!=(source in (55201,76464)): raise ValueError(f'Marker presence {unit}')
            for i,(cid,piece) in enumerate(zip(ids,pieces)):
                a=offset; b=a+len(piece)
                if not plain.startswith(piece,a): raise ValueError(f'Offset mismatch {cid}')
                if marks:
                    x=bisect.bisect_right(positions,a)-1; y=bisect.bisect_left(positions,b)-1
                    first=marks[x][1] if x>=0 else 'beginning';last=marks[y][1] if y>=0 else 'beginning'
                    val=first if first==last else f'{first}–{last}'
                    locator=label+(', ' if work=='Republic' else ' ')+val
                else:
                    first=bisect.bisect_right(starts,a);last=bisect.bisect_left(starts,b)
                    locator=f'{label} ¶{first}'+(f'–{last}' if first!=last else '')
                speakers=[]
                for p in starts[bisect.bisect_left(starts,a):bisect.bisect_left(starts,b)]:
                    m=re.match(r'([A-Z]+):',plain[p:b])
                    if m and m[1] in LABELS.get(work,()) and m[1] not in speakers: speakers.append(m[1])
                initial=re.match(r'([A-Z]+):',piece)
                if work in LABELS and (a not in starts or not initial or initial[1] not in LABELS[work]):
                    mid.append({'chunk_id':cid,'locator':locator,'first_12':piece.split()[:12]})
                chunks.append(dict(schema_version=1,chunk_id=cid,figure_id='plato',work=work,book=unit,section=None,part=None,parts_total=1,locator=locator,text=piece,word_count=words(piece),period='4th century BCE',genre='Philosophical dialogue',translator='Benjamin Jowett',speakers=speakers,source=source,source_sha256=provenance[source]['sha256']))
                counts[unit]+=1;work_counts[work]+=1;offset=b
                if i+1<len(pieces):
                    gap=re.match(r'\s*',plain[b:])[0];offset+=len(gap)
                    if '\n\n' not in gap:
                        if piece[-1] not in '.!?;': raise ValueError(f'Unexpected split {cid}')
                        cuts.append({'chunk_id':cid,'kind':'semicolon' if piece[-1]==';' else 'sentence','left':piece.split()[-12:],'right':pieces[i+1].split()[:12]})
            if offset!=len(plain): raise ValueError(f'Unconsumed text {unit}')
    if len({c['chunk_id'] for c in chunks})!=len(chunks): raise ValueError('Duplicate chunk IDs')
    if any(c['word_count']>config['max_words'] for c in chunks): raise ValueError('Word ceiling')
    payload,sha=serialise(chunks);stats=word_stats(chunks)
    split_counts={k:sum(c['kind']==k for c in cuts) for k in ('sentence','semicolon')}
    report=dict(schema_version=1,total_chunks=len(chunks),unit_count=len(counts),word_counts=stats,p90_method='nearest rank',split_units=split_units,chunks_sha256=sha,clean_sha256=hashes,config_sha256=hashlib.sha256((BASE/'chunking.json').read_bytes()).hexdigest(),per_work=dict(work_counts),per_unit=dict(counts),nonparagraph_splits=cuts,split_counts=split_counts,mid_speech_starts=mid,mid_speech_count=len(mid))
    (BASE/'data/chunks.jsonl').write_bytes(payload.encode('utf-8'))
    (BASE/'data/chunk_report.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(f'Chunks: {len(chunks)}; words min/median/p90/max: {stats["min"]}/{stats["median"]:g}/{stats["p90"]}/{stats["max"]}')
    print(f'Per unit: {dict(counts)}')
    print(f'chunks.jsonl SHA-256: {sha}')
    print(f'Nonparagraph splits: {split_counts}; mid-speech starts: {len(mid)}')

if __name__=='__main__': main()

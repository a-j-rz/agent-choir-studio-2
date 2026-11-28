"""Verify pinned sources and strip only specified spans. Run from repository root."""
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the repo root, so corpus_kit imports when run as python corpora/<id>/<script>.py
from corpus_kit.source import envelope, load_pinned  # noqa: E402
from corpus_kit.spans import Ledger, balanced, contamination, nc, unique  # noqa: E402

BASE = Path('corpora/charles_darwin')
SOURCES = {2009: '2b13c8524d813e706ad23336d81a142d48b44f1f96788b41494a0a83e1b82f88',
           2300: '2911dfcc2b0b498fe92ad9bd7e2c712046edb448eb6fe3bd669bcf9629adf8fd'}
ROMANS = 'I II III IV V VI VII VIII IX X XI XII XIII XIV XV XVI XVII XVIII XIX XX XXI'.split()
EXCEPTIONS = [
    ('descent-19', 49, "(49. ‘The Albert N’yanza,’", '1866, vol. i. p. 217.)', 'Position 48 printed as 49; duplicate number'),
    ('descent-19', 26, '(26. An observation by Vogt', 'that more observations are requisite on this point.', 'Missing closing parenthesis'),
    ('descent-02', 71, '(71. In Hylobates syndactylus,', 'wonderfully hook-like.', 'Missing closing parenthesis'),
    ('descent-04', 38, '(38. Lecky, ‘History of European Morals,’', '109.)', 'Position 37 printed as 38; duplicate number'),
    ('descent-17', 8, '(8. On the\nstructure and shedding of the horns of the reindeer,', '1866, p. 80.', 'Missing closing parenthesis'),
    ('descent-19', 8, '(8. As in Macacus cynomolgus', 'i. p. 2).', 'Unbalanced parentheses; extra full stop included in span'),
    ('descent-20', 1, '(1. ‘Schopenhauer and Darwinism,’ in', 'Jan. 1871, p. 323.', 'Missing closing parenthesis'),
]

def acquire(n):
    s = load_pinned(BASE / f'data/raw/pg{n}.txt', f'https://www.gutenberg.org/cache/epub/{n}/pg{n}.txt', SOURCES[n])
    if '[[' in s: raise ValueError('Reserved marker in source')
    return s

def strip(n,s):
    ledger=Ledger(s); units=[]; defects=[]; headings={}; synopses={}; notes={}; stars=0
    line=ledger.line; add=ledger.add
    def loc(marker,lo=0,hi=None): return unique(s,marker,lo,hi)
    def para_end(a):
        m=re.search(r'\n[ \t]*\n',s[a:]); return a+m.start() if m else len(s)
    start,end=envelope(s)
    add(0,start,'gutenberg_header'); add(end,len(s),'gutenberg_footer')
    if n==2009:
        sketch=loc('AN HISTORICAL SKETCH OF THE PROGRESS OF OPINION ON THE ORIGIN OF\nSPECIES, PREVIOUSLY TO THE PUBLICATION OF THE FIRST EDITION OF THIS\nWORK.',start,end)
        ep=loc('“But with regard to the material world,',start,sketch)
        add(start,ep,'edition_and_title_matter')
        ep2=loc('“The only distinct meaning of the word',ep,sketch); ep3=loc('“To conclude, therefore,',ep2,sketch)
        for a,b in [(ep,ep2),(ep2,ep3),(ep3,sketch)]: add(a,b,'epigraph')
        contents=loc('\nContents\n',sketch,end)+1
        detail=loc('\nDETAILED CONTENTS.\n',contents,end)+1
        intro=loc('\nINTRODUCTION.\n',detail,end)+1
        glossary=loc('\nGLOSSARY OF THE PRINCIPAL SCIENTIFIC TERMS USED IN THE PRESENT VOLUME.*\n',intro,end)+1
        index=loc('\nINDEX.\n',glossary,end)+1
        add(contents,detail,'contents'); add(detail,intro,'detailed_contents_and_title'); add(glossary,index,'glossary'); add(index,end,'index')
        units.append(('origin-sketch','Historical Sketch',sketch,contents,para_end(sketch),False))
        first=loc('\nCHAPTER I.\n',intro,glossary)+1
        units.append(('origin-intro','Introduction',intro,first,para_end(intro),False))
        terminal=glossary; prefix='origin'; count=15
    else:
        contents=loc('\nCONTENTS\n',start,end)+1
        pre=loc('\nPREFACE TO THE SECOND EDITION.\n',contents,end)+1
        detail=loc('\nDETAILED TABLE OF CONTENTS\n',pre,end)+1
        title=loc('\nTHE DESCENT OF MAN; AND SELECTION IN RELATION TO SEX.\n',detail,end)+1
        intro=loc('\nINTRODUCTION.\n',title,end)+1
        index=loc('\nINDEX. — Abbot, C., on the battles of seals.\n',intro,end)+1
        supplement=loc('\nSUPPLEMENTAL NOTE.\nON SEXUAL SELECTION IN RELATION TO MONKEYS.\n',intro,index)+1
        add(start,contents,'title_matter'); add(contents,pre,'contents'); add(detail,title,'detailed_contents'); add(title,intro,'title_matter'); add(index,end,'index')
        for marker in ['DOWN, BECKENHAM, KENT, September, 1874.', 'First Edition February 24, 1871. Second Edition September, 1874.']:
            x=loc(marker,pre,detail)
            if para_end(x)!=x+len(marker): raise ValueError('Preface signoff paragraph mismatch')
            add(x,x+len(marker),'preface_signoff')
        units.append(('descent-preface','Preface',pre,detail,para_end(pre),False))
        first=loc('\nCHAPTER I.\n',intro,index)+1
        units.append(('descent-intro','Introduction',intro,first,para_end(intro),False))
        terminal=supplement; prefix='descent'; count=21
        hux=loc('NOTE ON THE RESEMBLANCES AND DIFFERENCES IN THE STRUCTURE AND THE\nDEVELOPMENT OF THE BRAIN IN MAN AND APES BY PROFESSOR HUXLEY, F.R.S.',first,terminal)
        part2=loc('\nPART II.\nSEXUAL SELECTION.\n',first,terminal)+1
        add(hux,part2,'huxley_note')
        for marker in ['PART I.\nTHE DESCENT OR ORIGIN OF MAN.','PART II.\nSEXUAL SELECTION.','PART III.\nSEXUAL SELECTION IN RELATION TO MAN, AND CONCLUSION.']:
            a=loc(marker,intro,terminal); add(a,a+len(marker),'part_title')
        units.append(('descent-supplement','Supplemental Note',supplement,index,para_end(supplement),False))
        a=loc('Reprinted from NATURE, November 2, 1876, p. 18.',supplement,index); add(a,a+len('Reprinted from NATURE, November 2, 1876, p. 18.'),'reprint_line')
    chapters=[loc(f'\nCHAPTER {r}.\n',first-1,terminal)+1 for r in ROMANS[:count]]
    for i,a in enumerate(chapters):
        b=chapters[i+1] if i+1<count else terminal
        label=f'Ch. {ROMANS[i]}' if n==2009 else f'Pt {"I" if i<7 else "II" if i<18 else "III"}, Ch. {ROMANS[i]}'
        units.append((f'{prefix}-{i+1:02d}',label,a,b,para_end(a),True))
    units.sort(key=lambda u:u[2])
    for uid,label,a,b,h,chapter in units:
        add(a,h,'heading')
        if chapter:
            m=re.search(r'\S',s[h:b]); x=h+m.start(); y=para_end(x)
            if '—' not in s[x:y]: raise ValueError(f'Invalid synopsis {uid}')
            add(x,y,'synopsis'); synopses[uid]=s[x:y][:60]
    if n==2009:
        a,b=sketch,contents
        marker_order = [int(m[1]) for m in re.finditer(r'\[([123])\]',s[a:b]) if not s[a+m.start()-2:a+m.start()] == '\n ']
        if marker_order != [1,2,3]: raise ValueError('Origin note sequence')
        for i in range(1,4):
            marker=f'[{i}]'; ms=list(re.finditer(re.escape(marker),s[a:b]))
            if len(ms)!=2: raise ValueError('Origin footnote marker count')
            p,q=[a+m.start() for m in ms]; add(p,p+len(marker),'footnote_marker')
            if s[q-1]!=' ' or s[q-2]!='\n': raise ValueError('Origin note indentation')
            endnote=q
            for ln in s[q-1:b].splitlines(keepends=True):
                if not ln.startswith(' '): break
                endnote=(q-1 if endnote==q else endnote)+len(ln)
            add(q-1,endnote,'footnote')
        notes['origin-sketch']={'count':3,'sequence_valid':True,'numbers':[1,2,3]}
    else:
        for a_marker,b_marker,unit in [('                Native Population','  1872               51,531','descent-07'),('                                                   Males   Females','                                           Total     934       761','descent-08')]:
            u=next(u for u in units if u[0]==unit); a=loc(a_marker,u[2],u[3]); b=loc(b_marker,a,u[3])+len(b_marker); add(a,b,'table')
        captions=[]
        for m in re.finditer(r'\[Fig\.',s[intro:index]):
            a=intro+m.start(); b=balanced(s,a,'[',']',index); add(a,b,'figure_caption'); captions.append(a)
        if len(captions)!=57: raise ValueError(f'Caption count {len(captions)}')
        for uid,label,a,b,h,chapter in units:
            blocked=sorted((x,y) for x,y,_ in ledger if x<b and y>a)
            pos=h; seq=[]
            while pos<b:
                m=re.search(r'\((\*?)(\d{1,3})\.(?=\s)',s[pos:b])
                if not m: break
                x=pos+m.start(); overlap=next(((l,r) for l,r in blocked if l<=x<r),None)
                if overlap: pos=overlap[1]; continue
                num=int(m[2]); position=len(seq)+1
                e=next((e for e in EXCEPTIONS if e[0]==uid and e[1]==num and s.startswith(e[2],x)),None)
                if e:
                    if loc(e[2],a,b)!=x: raise ValueError('Exception start mismatch')
                    # End marker must be unique within the exception note search region, before next numbered note.
                    next_note=re.search(r'\(\*?\d{1,3}\.(?=\s)',s[x+len(e[2]):b]); limit=x+len(e[2])+next_note.start() if next_note else b
                    y=loc(e[3],x,limit)+len(e[3]); defects.append({'unit':uid,'note_number':num,'position':position,'start_text':e[2],'end_text':e[3],'defect':e[4]})
                else:
                    next_note=re.search(r'\(\*?\d{1,3}\.(?=\s)',s[x+len(m[0]):b])
                    limit=x+len(m[0])+next_note.start() if next_note else b
                    y=balanced(s,x,'(',')',limit)
                if num!=position and not(e and ((uid=='descent-04' and position==37 and num==38) or (uid=='descent-19' and position==48 and num==49))): raise ValueError(f'Note sequence {uid} position {position}, got {num}, line {line(x)}')
                if m[1]: stars+=1
                add(x,y,'footnote'); seq.append(num); pos=y
            notes[uid]={'count':len(seq),'sequence_valid':True,'numbers':seq}
        if len(defects)!=7 or stars!=1: raise ValueError(f'Defect/star counts: {len(defects)}/{stars}')
        expected = dict(zip(['descent-preface','descent-intro']+[f'descent-{i:02d}' for i in range(1,22)]+['descent-supplement'], [0,2,56,96,79,50,37,32,69,99,26,80,34,72,94,55,33,57,49,47,76,28,2,0]))
        actual = {k:v['count'] for k,v in notes.items()}
        if actual != expected: raise ValueError(f'Note counts differ: {[(k,expected[k],actual.get(k)) for k in expected if actual.get(k)!=expected[k]]}')
    for m in re.finditer(r'\[Illustration[^\]]*\]',s):
        if not any(a<=m.start()<b for a,b,_ in ledger): add(m.start(),m.end(),'illustration')
    # Render retained text with a source offset map. Deleted inline spans do not
    # leave internal newlines; paragraph boundaries outside spans are preserved.
    out=[]; body_chars=0; class_exceptions=[]
    for uid,label,a,b,h,chapter in units:
        spans=sorted((x,y) for x,y,_ in ledger if a<=x<b)
        cursor=a; chars=[]; offsets=[]
        for x,y in spans:
            if x<cursor or y>b: raise ValueError(f'Overlapping spans {uid}: {line(x)}')
            chars.append(s[cursor:x]); offsets.extend(range(cursor,x))
            cursor=y
        chars.append(s[cursor:b]); offsets.extend(range(cursor,b))
        t=''.join(chars)
        # Whitespace before punctuation after a removed note is immaterial to
        # character conservation; remove it only at the recorded join.
        out.append(f'[[unit {uid} | {label}]]'); headings[uid]=[]
        for p in re.finditer(r'\S(?:.*?)(?=\n[ \t]*\n|\Z)',t,re.S):
            raw=p.group().strip(); flat=' '.join(raw.split())
            if not flat: continue
            class_exception = uid=='descent-16' and re.match(r'^CLASS (?:II|III|IV|V|VI)\. —',flat) is not None
            if class_exception: class_exceptions.append(flat.split(' —',1)[0])
            is_heading=(re.fullmatch(r'_[^_]+_',flat) is not None) if n==2009 else (flat.isupper() and not class_exception)
            if is_heading:
                x=offsets[p.start()]; y=offsets[p.start()+len(p.group().rstrip())-1]+1
                if any(l<y and r>x for l,r,_ in ledger): raise ValueError(f'Heading overlaps strip {uid}: {flat}')
                add(x,y,'heading'); title=(flat[1:-1] if n==2009 else flat).removesuffix('.')
                headings[uid].append(title); out.append(f'[[section {len(headings[uid])} | {title}]]')
            else:
                # Remove spaces immediately before punctuation only where a deleted span joined it.
                raw_chars=list(p.group()); base=p.start()
                for j in range(len(raw_chars)-1,0,-1):
                    if raw_chars[j] in ',;:.' and raw_chars[j-1].isspace() and offsets[base+j]>offsets[base+j-1]+1:
                        k=j-1
                        while k>=0 and raw_chars[k].isspace(): raw_chars[k]=''; k-=1
                flat=' '.join(''.join(raw_chars).split()); out.append(flat); body_chars+=nc(flat)
    ledger.check_overlap()
    clean='\n\n'.join(out)+'\n'
    # Body region is everything between first retained unit and glossary/index.
    low=units[0][2]; high=glossary if n==2009 else index
    stripped=sum(nc(s[max(low,a):min(high,b)]) for a,b,_ in ledger if a<high and b>low)
    source=nc(s[low:high]); difference=source-body_chars-stripped
    if difference: raise ValueError(f'Character conservation {n}: {source}-{body_chars}-{stripped}={difference}')
    body='\n'.join(x for x in clean.splitlines() if not x.startswith('[['))
    if nc(body)!=body_chars: raise ValueError('Rendered clean character count mismatch')
    if n==2300 and 'females, and agree' not in body: raise ValueError('Chapter XIX note 8 join mismatch')
    bad=contamination(clean,['Project Gutenberg','GLOSSARY','INDEX','[Fig.','[Illustration','Reprinted from NATURE','BY PROFESSOR HUXLEY','DETAILED','[1]','[2]','[3]','BECKENHAM','First Edition February'])
    if re.search(r'\(\*?\d{1,3}\.\s',clean): bad.append('numbered parenthetical')
    if re.search(r'(?m)^Fig\.\s*\d',body): bad.append('orphan figure caption')
    if any(x.rstrip().endswith(']') and x.count(']') > x.count('[') for x in body.splitlines()): bad.append('orphan closing bracket')
    if n==2300:
        if class_exceptions != [f'CLASS {r}.' for r in ROMANS[1:6]]: raise ValueError(f'CLASS exceptions: {class_exceptions}')
        if sum(r['category']=='heading' for _,_,r in ledger)!=129: raise ValueError('Descent heading count differs from 129')
        current_unit=None
        for paragraph in clean.split('\n\n'):
            if paragraph.startswith('[[unit '): current_unit=paragraph.split()[1]
            elif not paragraph.startswith('[[') and paragraph.strip().isupper() and not (current_unit=='descent-16' and re.match(r'^CLASS (?:II|III|IV|V|VI)\. —',paragraph)): bad.append('uppercase body paragraph')
    if bad: raise ValueError(f'Contamination {n}: {bad}')
    return clean,{'source_sha256':SOURCES[n],'stripped_spans':[r for _,_,r in ledger],'footnotes':notes,'star_form_count':stars,'source_defects':defects,'synopses':synopses,'headings':headings,'conservation':{'source_non_whitespace_chars':source,'clean_non_whitespace_chars':body_chars,'stripped_non_whitespace_chars':stripped,'difference':difference},'contamination':{'passed':True,'matches':bad}}

def main():
    results={n:strip(n,acquire(n)) for n in SOURCES}
    dest=BASE/'data/clean'; dest.mkdir(parents=True,exist_ok=True)
    report={}
    for n,(clean,r) in results.items():
        name='origin' if n==2009 else 'descent'; (dest/f'{name}.txt').write_text(clean,encoding='utf-8'); report[name]=r
        print(f'{name}: raw SHA-256 {SOURCES[n]}; conservation {r["conservation"]}; footnotes {sum(x["count"] for x in r["footnotes"].values())}; stripped spans {len(r["stripped_spans"])}')
    (dest/'strip_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__': main()

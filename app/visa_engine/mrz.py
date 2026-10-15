"""ICAO Doc 9303 Part 7 MRV-A (2x44), MRV-B (2x36).

Number semantics are issuer-dependent: visa OR passport. Never guess which.
Checksums describe transcription structure only. Passport TD3 is untouched.
"""
from datetime import date
import re

def check_digit(text):
    def number(c): return 0 if c=='<' else int(c) if c.isdigit() else ord(c)-55
    return str(sum(number(c)*(7,3,1)[i%3] for i,c in enumerate(text))%10)

def parse_mrz(lines):
    rows=[(re.sub(r'\s+','',part.upper()),line.confidence) for line in lines for part in line.text.splitlines()]
    candidates=[]
    rejected=[]
    for i,(first,score) in enumerate(rows[:-1]):
        second,other_score=rows[i+1]
        if len(first) not in (36,44) or len(second)!=len(first) or not first.startswith('V'): continue
        reasons=[]
        if not re.fullmatch(r'V[A-Z<][A-Z<]{3}[A-Z<]+',first): reasons.append('mrz_first_line_structure')
        if not re.fullmatch(r'[A-Z0-9<]{9}[0-9][A-Z<]{3}[0-9]{6}[0-9][MF<][0-9]{6}[0-9][A-Z0-9<]*',second): reasons.append('mrz_second_line_structure')
        if reasons:
            rejected.append(dict(raw_lines=[rows[i][0],rows[i+1][0]],reasons=reasons))
            continue
        checks={key:check_digit(second[start:end])==second[end] for key,start,end in [('number',0,9),('birth',13,19),('valid_until',21,27)]}
        for name,raw in [('birth_calendar',second[13:19]),('expiry_calendar',second[21:27])]:
            possible=False
            for century in (1900,2000,2100):
                try: date(century+int(raw[:2]),int(raw[2:4]),int(raw[4:]));possible=True
                except ValueError: pass
            checks[name]=possible
        confidence=min(score,other_score) if score is not None and other_score is not None else None
        candidates.append(dict(format='MRV-A' if len(first)==44 else 'MRV-B',checks=checks,
            document_number=second[:9].rstrip('<'),citizenship=second[10:13],valid_until_raw=second[21:27],confidence=confidence))
    if len(candidates)!=1:
        return dict(found=bool(candidates),format=None,valid=False,rejected_pairs=rejected,errors=['multiple_mrz'] if candidates else sorted({reason for pair in rejected for reason in pair['reasons']}))
    item=candidates[0]
    return dict(found=True,valid=all(item['checks'].values()),errors=[] if all(item['checks'].values()) else ['mrz_check_failed'],**item)

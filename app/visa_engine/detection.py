"""Explainable visa evidence, separate from field-confidence thresholds."""
import re
from .normalization import normalize_date
from .visual import find_labels
from app.document_engine.visual_dates import valid_box

DATE_TOKEN=re.compile(r'(?<![0-9])(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{2}[./][0-9]{2}[./](?:[0-9]{4}|[0-9]{2}))(?![0-9])')

def visa_markers(lines):
    return [i for i,b in enumerate(lines) if (b.confidence or 0)>=.90
            and re.search(r'(?<!\w)(?:visa|виза)(?!\w)',b.text,re.I)]

def mrz_like_pairs(lines,image_size=None):
    """Damaged MRV-looking text is detection evidence, never parsed field data."""
    candidates=[]
    for i,first in enumerate(lines):
        a=re.sub(r'\s+','',first.text.upper())
        if not (30<=len(a)<=50 and a.startswith('V') and a.count('<')>=4): continue
        if not re.fullmatch(r'[A-Z0-9<]+',a) or (first.confidence or 0)<.85 or not valid_box(first.bbox): continue
        for j,second in enumerate(lines):
            if i==j or not valid_box(second.bbox) or (second.confidence or 0)<.85: continue
            b=re.sub(r'\s+','',second.text.upper())
            if not (30<=len(b)<=50 and b.count('<')>=2 and sum(c.isdigit() for c in b)>=8): continue
            if not re.fullmatch(r'[A-Z0-9<]+',b) or abs(len(a)-len(b))>6: continue
            x,y,r,bottom=first.bbox; sx,sy,sr,sb=second.bbox
            height=max(bottom-y,sb-sy)
            overlap=min(r,sr)-max(x,sx)
            if sy<bottom-.2*height or sy-bottom>2*height or abs(x-sx)>height: continue
            if overlap<.8*max(r-x,sr-sx): continue
            if image_size and (y<image_size[1]*.55 or r-x<image_size[0]*.5): continue
            candidates.append(dict(indices=[i,j],raw_lines=[first.text,second.text],normalized_lines=[a,b],
                                   lengths=[len(a),len(b)],confidence=min(first.confidence,second.confidence),
                                   bbox=[min(x,sx),y,max(r,sr),sb]))
    return candidates

def detect_visa(lines,fields,mrz,image_size=None,header_candidates=None):
    markers=visa_markers(lines)
    labels=[dict(field=field,matched_label=alias,line_index=i,text=line.text,confidence=line.confidence,bbox=line.bbox)
            for i,line in enumerate(lines) for field,_,alias in find_labels(line.text)]
    reliable_labels={row['field'] for row in labels if row['field']!='_birth' and (row['confidence'] or 0)>=.90}
    dates=[]
    for i,line in enumerate(lines):
        if (line.confidence or 0)<.90: continue
        for match in DATE_TOKEN.finditer(line.text):
            raw=match.group()
            # Calendar-shaped short dates are evidence only, not century-resolved values.
            if normalize_date(raw) or any(normalize_date(raw,century+int(raw[-2:])) for century in (1900,2000)):
                dates.append(dict(raw_text=raw,line_index=i,confidence=line.confidence))
    pairs=mrz_like_pairs(lines,image_size)
    reliable=sum(bool(fields[k].value) for k in ('visa_type','entries','issue_date','valid_from','valid_until'))
    strong_layout=bool(markers and fields['visa_number'].value and reliable>=3 and any(fields[k].value for k in ('issue_date','valid_from','valid_until')))
    features={'mrv_like_pair':bool(pairs),'visa_word':bool(markers),'visa_labels':len(reliable_labels)>=2,
              'dates':bool(dates),'document_number':bool(fields['visa_number'].value or header_candidates),
              'spatial_layout':bool(pairs or reliable>=2)}
    weights={'mrv_like_pair':3,'visa_word':2,'visa_labels':2,'dates':1,'document_number':1,'spatial_layout':1}
    score=10 if mrz.get('valid') else sum(weights[k] for k,value in features.items() if value)
    combined=bool(markers and ((pairs and dates) or (len(reliable_labels)>=3 and len(dates)>=2 and reliable>=1)))
    supported=bool(mrz.get('valid') or strong_layout or (combined and score>=6))
    basis='validated_mrz' if mrz.get('valid') else 'visual_layout' if strong_layout else 'combined_evidence' if supported else 'insufficient_evidence'
    reasons=[]
    if not mrz.get('valid'): reasons.append('no_valid_supported_mrv')
    if not markers: reasons.append('no_confident_visa_word')
    if not reliable_labels: reasons.append('no_confident_visa_labels')
    if not fields['visa_number'].value: reasons.append('no_labelled_visa_number')
    if not strong_layout: reasons.append('incomplete_strong_visual_layout')
    if not supported: reasons.append('insufficient_independent_visa_evidence')
    return dict(supported=supported,basis=basis,score=score,score_max=10,partial_threshold=6,features=features,
                matched_labels=labels,visa_marker_indices=markers,date_evidence=dates,mrz_like_pairs=pairs,reasons=reasons)

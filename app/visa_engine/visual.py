"""Conservative label/bounding-box association with dev-only diagnostics."""
import re
from app.document_engine.models import ExtractedField
from app.document_engine.visual_dates import spatial_relation
from .models import FIELD_NAMES
from .normalization import normalize_date, normalize_choice, ENTRIES, VISA_TYPES

LABELS = {
    'visa_number': ('visa number','visa no','номер визы','numero de visa'),
    'visa_type': ('visa type','type of visa','тип визы','категория визы'),
    'entries': ('number of entries','no. of entries','entries','кратность','количество въездов'),
    'issue_date': ('date of issue','issue date','date issued','дата выдачи'),
    'valid_from': ('valid from','действует с','действительна с'),
    'valid_until': ('valid until','valid to','expiry date','действует до','действительна до'),
    'citizenship': ('nationality','citizenship','гражданство'),
    'passport_number_if_present': ('passport number','passport no','номер паспорта'),
    'purpose_or_category_if_reliable': ('purpose of visit','purpose','цель поездки'),
    'issuing_authority_if_reliable': ('issuing authority','issued by','орган выдачи'),
    # These labels compete for nearby values, but are never extracted as visa dates.
    '_birth': ('date of birth','birth date','дата рождения'),
}
DATE_FIELDS={'issue_date','valid_from','valid_until'}

def find_labels(text):
    matches=[]
    for field,aliases in LABELS.items():
        for alias in sorted(aliases,key=len,reverse=True):
            match=re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',text,re.I)
            if match:
                matches.append((field,match.end(),alias));break
    return matches

def value_for(field,raw):
    raw=raw.strip(' :;№#').strip()
    if field in DATE_FIELDS: return normalize_date(raw)
    if field=='entries': return normalize_choice(raw,ENTRIES)
    if field=='visa_type': return normalize_choice(raw,VISA_TYPES)
    if field in {'visa_number','passport_number_if_present'}:
        value=raw.upper()
        return value if re.fullmatch(r'[A-Z0-9][A-Z0-9-]{3,31}',value) and any(c.isdigit() for c in value) else None
    if field=='citizenship':
        return raw.upper() if re.fullmatch(r'[A-Za-z]{3}',raw) else None
    return raw if 1<=len(raw)<=100 and not any(ord(c)<32 for c in raw) else None

def extract_visual(lines):
    fields={key:ExtractedField() for key in FIELD_NAMES}
    candidates={key:[] for key in FIELD_NAMES}
    labels=[(i,field,end,alias) for i,line in enumerate(lines) for field,end,alias in find_labels(line.text)]
    label_indices={i for i,_,_,_ in labels}
    for i,field,end,alias in labels:
        if field.startswith('_'): continue
        label=lines[i]
        for j,block in enumerate(lines):
            if '<' in block.text: continue
            if i==j:
                # A merged block is usable only when it contains one label.
                if len(find_labels(block.text))!=1: continue
                relation=('same_block',0.0); raw=block.text[end:].strip(' :;№#')
            else:
                if j in label_indices: continue
                relation=spatial_relation(label.bbox,block.bbox);raw=block.text.strip()
            if not relation or not raw: continue
            position,distance=relation
            if distance>8: continue
            competitors=[]
            for li,other,_,_ in labels:
                if li==i or other==field: continue
                link=spatial_relation(lines[li].bbox,block.bbox) if li!=j else ('same_block',0.0)
                if link: competitors.append(link[1])
            value=value_for(field,raw)
            scores=[label.confidence,block.confidence]
            confidence=min(scores) if all(s is not None and 0<=s<=1 for s in scores) else 0
            spatial_score=max(0,1-.04*distance)
            reasons=[]
            if value in (None,'unknown'): reasons.append('invalid_or_ambiguous_value')
            if confidence<.90: reasons.append('low_ocr_confidence')
            if competitors and min(competitors)<=distance+.35: reasons.append('competing_label')
            candidates[field].append(dict(raw_text=raw,value=value,matched_label=alias,relative_position=position,
                distance_to_label=round(distance,4),ocr_confidence=block.confidence,label_confidence=label.confidence,
                spatial_score=round(spatial_score,4),score=round(confidence*spatial_score,4),reasons=reasons))
    for field,items in candidates.items():
        eligible=[c for c in items if not c['reasons']]
        values={c['value'] for c in eligible}
        if len(values)==1:
            best=max(eligible,key=lambda c:c['score'])
            best['selected']=True
            fields[field]=ExtractedField(best['value'],best['score'],'visual_ocr',True)
        elif len(values)>1:
            for item in eligible: item['reasons'].append('ambiguous_candidates')
    # A labelled purpose can establish an explicit study type, never a lone visa code.
    purpose=fields['purpose_or_category_if_reliable']
    inferred=normalize_choice(purpose.value or '',VISA_TYPES)
    if fields['visa_type'].value is None and not candidates['visa_type'] and inferred!='unknown':
        fields['visa_type']=ExtractedField(inferred,purpose.confidence,'visual_ocr',True)
    return fields,candidates


def header_number_candidates(lines,image_size):
    """A narrow fallback for a unique serial beside an explicit VISA heading.

    The caller additionally requires independent MRV-like evidence. No value is
    taken from this helper alone. Never choose a bare page-wide number/date.
    """
    if not image_size: return []
    from app.document_engine.visual_dates import valid_box
    headings=[b for b in lines if b.text.strip().casefold() in {'visa','виза'}
              and (b.confidence or 0)>=.90 and valid_box(b.bbox) and b.bbox[1]<image_size[1]*.25]
    numbers=[b for b in lines if (b.confidence or 0)>=.95 and valid_box(b.bbox)
             and re.fullmatch(r'[0-9]{6,12}|[0-9]{1,3} +[0-9]{6,10}',b.text.strip())]
    result=[]
    for title in headings:
        for block in numbers:
            raw=block.text.strip();box=block.bbox;confidence=block.confidence
            # A short adjacent prefix and serial may be separate OCR blocks.
            prefixes=[]
            for other in lines:
                if other is block or not valid_box(other.bbox) or (other.confidence or 0)<.95: continue
                if not re.fullmatch(r'[0-9]{1,3}',other.text.strip()): continue
                x,y,r,b=other.bbox;dx,dy,dr,db=box;height=max(b-y,db-dy)
                if -.2*height<=dx-r<=height and abs((y+b-dy-db)/2)<=.5*height:
                    prefixes.append(other)
            if len(prefixes)>1: continue
            if prefixes:
                prefix=prefixes[0];raw=prefix.text.strip()+' '+raw
                box=(prefix.bbox[0],min(prefix.bbox[1],box[1]),box[2],max(prefix.bbox[3],box[3]))
                confidence=min(confidence,prefix.confidence)
            compact=re.sub(r' +','',raw)
            if not 6<=len(compact)<=12 or normalize_date(compact): continue
            relation=spatial_relation(title.bbox,box)
            if not relation or relation[0]!='right' or relation[1]>6: continue
            score=min(title.confidence,confidence)*(1-.04*relation[1])*.90
            result.append(dict(raw_text=raw,value=compact,matched_label=title.text,association='visa_heading_serial',
                relative_position='right',distance_to_label=round(relation[1],4),ocr_confidence=confidence,
                label_confidence=title.confidence,score=round(score,4),bbox=list(box),
                reason='unique_header_serial_requires_independent_mrv_evidence'))
    return result

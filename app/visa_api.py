"""Visa processing/confirmation over the existing safe local document storage."""
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from . import documents
from .visa_engine.models import VisaConfirmation, FIELD_NAMES

router=APIRouter(prefix='/api/documents/visa',tags=['visa'])

class ProcessingRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    document_id: str = Field(pattern=r'^[a-f0-9]{32}$')

def require_record(index,document_id=None):
    record=index.get('visa')
    if not record or not documents.stored_path(record).is_file(): raise HTTPException(404,'document_not_found')
    if document_id and Path(record['stored_name']).stem!=document_id: raise HTTPException(409,'document_changed')
    return record

def save(index):
    try: documents.write_index(index)
    except OSError: raise HTTPException(500,'storage_error') from None

def view(record):
    extraction=record.get('visa_extraction')
    fields=record.get('visa_fields') if record.get('status')=='verified' else None
    fields=fields or (extraction or {}).get('extracted_fields',{})
    data={key:fields.get(key,{}).get('value') for key in FIELD_NAMES}
    # Retain earlier one-field user confirmations while introducing the visa form.
    for key,item in record.get('manual_fields',{}).items():
        if not item.get('confirmed'): continue
        if key=='expiry_date': data['valid_until']=item['value']
        elif key=='visa_type' and item['value']=='multiple_entry': data['entries']='multiple'
        elif key in data: data[key]=item['value']
    summary={key:extraction[key] for key in ('processing_status','detected_document_type','processing_seconds','extracted_fields','errors')} if extraction else None
    return dict(document=documents.public_record('visa',record),data=data,fields=fields,extraction=summary)

@router.get('/data')
def get_data():
    with documents.storage_lock: return view(require_record(documents.read_index()))

@router.post('/process')
def process_visa(body: ProcessingRequest,request: Request):
    with documents.storage_lock:
        index=documents.read_index();record=require_record(index,body.document_id)
        if record.get('status')=='verified': raise HTTPException(409,'already_verified')
        if record.get('status')=='processing': raise HTTPException(409,'processing_in_progress')
        path=documents.stored_path(record);record['status']='processing';save(index)
    result=request.app.state.visa_engine.process(path)
    with documents.storage_lock:
        index=documents.read_index();record=require_record(index,body.document_id)
        if record.get('status')=='verified': return view(record)
        record['visa_extraction']=result
        record['extracted_fields']=result['extracted_fields']
        record['status']='processing_error' if result['processing_status']=='failed' else 'needs_confirmation'
        save(index);return view(record)

@router.put('/data')
def confirm_visa(body: VisaConfirmation):
    with documents.storage_lock:
        index=documents.read_index();record=require_record(index,body.document_id)
        data=body.data.model_dump(mode='json')
        extracted=(record.get('visa_extraction') or {}).get('extracted_fields',{})
        previous=record.get('visa_fields',{})
        fields={}
        for key,value in data.items():
            candidate=previous.get(key) or extracted.get(key,{})
            same=value is not None and value!='unknown' and candidate.get('value')==value
            fields[key]=dict(value=value,source=candidate.get('source','manual') if same else 'manual' if value not in (None,'unknown') else 'unresolved',
                             confidence=candidate.get('confidence') if same else None,needs_confirmation=False)
        record.update(visa_data=data,visa_fields=fields,status='verified')
        # The newly reviewed form supersedes legacy date/type corrections, not receipt dates.
        record['manual_fields']={key:item for key,item in record.get('manual_fields',{}).items() if key=='received_at'}
        save(index);return view(record)

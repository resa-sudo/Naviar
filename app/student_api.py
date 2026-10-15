"""Single-user profile source plus one-field document confirmations."""
import json
from pathlib import Path
from uuid import uuid4
from datetime import date
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from . import documents
from .student_context import build_context, rule_results, FIELDS
from .next_actions import next_actions

router=APIRouter(prefix='/api/student',tags=['student-context'])
STATE_DIRECTORY=Path(__file__).resolve().parents[1]/'data/student'


class Profile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    citizenship: Literal['tm','uz','tj','kg','kz','other']
    university: Literal['rudn','msu','hse','spbu','other']
    degree: Literal['bachelor','master','phd','preparatory']
    language: Literal['ru','en']


class ManualField(BaseModel):
    model_config=ConfigDict(extra='forbid')
    field: str = Field(max_length=40)
    value: str = Field(min_length=1,max_length=200)
    confirmed: Literal[True]


def read_profile():
    path=STATE_DIRECTORY/'profile.json'
    if not path.exists(): return None
    try:
        stored=json.loads(path.read_text(encoding='utf-8'))
        Profile.model_validate({key:stored[key] for key in Profile.model_fields})
        return stored
    except (OSError,ValueError,KeyError):
        raise HTTPException(500,'profile_storage_error') from None


@router.get('/profile')
def get_profile():
    with documents.storage_lock:
        return {'profile':read_profile()}


@router.put('/profile')
def save_profile(profile: Profile):
    with documents.storage_lock:
        existing=read_profile()
        value={**profile.model_dump(),'student_id':existing['student_id'] if existing else uuid4().hex}
        try:
            STATE_DIRECTORY.mkdir(parents=True,exist_ok=True)
            temporary=STATE_DIRECTORY/'profile.tmp'
            temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(STATE_DIRECTORY/'profile.json')
        except OSError: raise HTTPException(500,'profile_storage_error') from None
        return {'profile':value}


@router.get('/context')
def get_context():
    with documents.storage_lock:
        profile=read_profile()
        records=documents.list_documents()
        if not profile: return dict(context=None,documents=records,rules=None,next_actions=[])
        context=build_context(profile,documents.read_index())
        rules=rule_results(context)
        return dict(context=context,documents=records,rules=rules,next_actions=next_actions(context,rules))


@router.patch('/documents/{kind}/{document_id}/field')
def confirm_field(kind: str, document_id: str, body: ManualField):
    if kind not in {'visa','migration_card','registration'} or body.field not in FIELDS[kind]:
        raise HTTPException(422,'unsupported_field')
    if kind=='visa' and body.field not in {'visa_type','issue_date','expiry_date','received_at'}:
        raise HTTPException(422,'unsupported_field')
    value=body.value.strip()
    if body.field.endswith('_date') or body.field=='received_at':
        try:
            parsed=date.fromisoformat(value)
            if parsed.isoformat()!=value: raise ValueError()
            if body.field in {'issue_date','entry_date','registration_date','received_at'} and parsed>date.today(): raise ValueError()
        except ValueError: raise HTTPException(422,'invalid_date') from None
    if body.field=='visa_type' and value not in {'multiple_entry','other'}:
        raise HTTPException(422,'invalid_value')
    if not value or any(ord(c)<32 for c in value): raise HTTPException(422,'invalid_value')
    with documents.storage_lock:
        index=documents.read_index(); record=index.get(kind)
        if not record or not documents.stored_path(record).is_file(): raise HTTPException(404,'document_not_found')
        if Path(record['stored_name']).stem!=document_id: raise HTTPException(409,'document_changed')
        if kind=='visa' and record.get('status')=='verified' and body.field!='received_at':
            raise HTTPException(409,'use_visa_confirmation')
        current=record.get('manual_fields',{})
        updated={**current,body.field:dict(value=value,source='manual_fallback',confirmed=True)}
        issue=updated.get('issue_date',{}).get('value'); expiry=updated.get('expiry_date',{}).get('value')
        if issue and expiry and expiry<issue: raise HTTPException(422,'invalid_date_order')
        record['manual_fields']=updated
        try: documents.write_index(index)
        except OSError: raise HTTPException(500,'storage_error') from None
    return get_context()

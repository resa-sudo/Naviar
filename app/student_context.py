"""Single student read-model composed from source records, never persisted as a copy."""
from datetime import date
from typing import Any, Literal
from pydantic import BaseModel, Field
from . import documents
from .deadlines.models import StudentContext as RulesContext
from .deadlines.entry_regimes import entry_regime_for
from .deadlines.rules import evaluate_context


class ContextField(BaseModel):
    value: Any = None
    source: Literal['profile','document_record','passport_ocr','visa_ocr','migration_card_ocr','registration_ocr','medical_document','derived_rule','manual_fallback','manual_confirmed'] | None = None
    confirmed: bool = False
    confidence: float | None = None
    status: str = 'missing'


def field(value=None, source=None, confirmed=False, confidence=None):
    return ContextField(value=value, source=source, confirmed=confirmed if value is not None else False,
                        confidence=confidence, status='missing' if value is None else 'confirmed' if confirmed else 'needs_confirmation')


class StudentContext(BaseModel):
    student_id: ContextField
    citizenship: ContextField
    university_id: ContextField
    study_level: ContextField
    preferred_language: ContextField
    entry_regime: ContextField
    residence_type: ContextField
    student_category: ContextField
    passport: dict[str, ContextField]
    visa: dict[str, ContextField]
    migration_card: dict[str, ContextField]
    registration: dict[str, ContextField]
    medical: dict[str, Any]


FIELDS = {
    'passport': ('passport_number','issue_date','expiry_date','issuing_country','birth_date'),
    'visa': ('visa_number','visa_type','entries','issue_date','valid_from','valid_until','expiry_date','received_at','citizenship','passport_number_if_present','purpose_or_category_if_reliable','issuing_authority_if_reliable'),
    'migration_card': ('entry_date','migration_card_number'),
    'registration': ('registration_date','expiry_date','address_if_available'),
}
OCR_KEYS = {'issue_date':'date_of_issue','birth_date':'date_of_birth'}
COUNTRIES = {'tm':'TKM','uz':'UZB','tj':'TJK','kg':'KGZ','kz':'KAZ'}


def document_context(kind, record):
    result = {key:field() for key in FIELDS[kind]}
    result['document_id'] = field()
    result['confirmed'] = field(False, 'derived_rule', True)
    if not record:
        return result
    result['document_id'] = field(documents.public_record(kind,record)['document_id'],'document_record',True)
    extraction = (record.get('extraction') or {}).get('mrz',{}).get('fields',{})
    # Future document processors may supply this same field envelope.
    if kind != 'passport':
        extraction = record.get('extracted_fields',{})
    for key in FIELDS[kind]:
        candidate = extraction.get(OCR_KEYS.get(key,key) if kind=='passport' else key,{})
        if candidate.get('value') is not None:
            result[key] = field(candidate['value'],kind+'_ocr',False,candidate.get('confidence'))
        confirmed_data = record.get('passport_data',{}) if kind=='passport' and record.get('status')=='verified' else {}
        if key in confirmed_data:
            value=confirmed_data[key]
            source='passport_ocr' if value==candidate.get('value') else 'manual_confirmed'
            result[key]=field(value,source,True,candidate.get('confidence') if source=='passport_ocr' else None)
        # Explicit, confirmed corrections always outrank extracted values.
        manual=record.get('manual_fields',{}).get(key,{})
        if manual.get('confirmed') and manual.get('value') is not None:
            result[key]=field(manual['value'],'manual_fallback',True)
    if kind=='visa':
        for key,item in record.get('visa_fields',{}).items():
            if record.get('status')=='verified' and item.get('value') not in (None,'unknown'):
                result[key]=field(item['value'],'visa_ocr' if item['source'] in ('mrz','visual_ocr') else 'manual_confirmed',True,item.get('confidence'))
        if result['expiry_date'].confirmed and record.get('status')!='verified':
            result['valid_until']=result['expiry_date']
        elif result['valid_until'].value is not None:
            result['expiry_date']=result['valid_until']
    complete = record.get('status')=='verified' if kind in {'passport','visa'} else result['entry_date' if kind=='migration_card' else 'expiry_date'].confirmed
    result['confirmed']=field(complete,'derived_rule',True)
    return result


def confirmed_value(group, key):
    item=group.get(key)
    return item.value if item and item.confirmed else None


def build_context(profile, index):
    records={kind:record for kind,record in index.items() if kind in FIELDS and documents.stored_path(record).is_file()}
    parts={kind:document_context(kind,records.get(kind)) for kind in FIELDS}
    citizenship=COUNTRIES.get(profile['citizenship'].lower(),profile['citizenship'].upper())
    if citizenship=='OTHER': citizenship=None
    regime=entry_regime_for(citizenship or '')
    medical_records={r['medical_type']:r for r in index.get('medical_certificates',[]) if r['medical_type'] not in documents.LEGACY_MEDICAL_TYPES and documents.stored_path(r).is_file()}
    medical={}
    for name,slot in [('hiv_certificate_present','medical_hiv_certificate'),('infectious_certificate_present','medical_infectious_diseases_certificate'),('drug_screening_certificate_present','medical_drug_screening_certificate')]:
        medical[name]=field(slot in medical_records,'medical_document',True)
    medical['completion_count']=field(len(medical_records),'derived_rule',True)
    medical['relevant_dates']={slot:{key:field(record.get(key),'medical_document',record.get(key) is not None) for key in ('issue_date','valid_until')} for slot,record in medical_records.items()}
    return StudentContext(student_id=field(profile['student_id'],'derived_rule',True),
        citizenship=field(citizenship,'profile',True), university_id=field(profile['university'],'profile',True),
        study_level=field(profile['degree'],'profile',True),preferred_language=field(profile['language'],'profile',True),
        entry_regime=field(regime if regime!='unknown' else None,'derived_rule',regime!='unknown'),
        residence_type=field(),student_category=field('foreign_student' if citizenship and citizenship!='RUS' else None,'derived_rule',bool(citizenship)),
        medical=medical,**parts)


def rule_results(context, today=None):
    today=today or date.today()
    birth=confirmed_value(context.passport,'birth_date')
    age='unknown'
    if birth:
        born=date.fromisoformat(birth)
        years=today.year-born.year-((today.month,today.day)<(born.month,born.day))
        age='adult' if years>=18 else 'minor'
    visa_type=confirmed_value(context.visa,'visa_type')
    entries=confirmed_value(context.visa,'entries')
    # Adapter only: the existing Rules Engine calls multiplicity visa_type.
    rule_visa_type='multiple_entry' if entries=='multiple' or visa_type=='multiple_entry' else 'other' if entries in {'single','double'} else 'unknown'
    inputs=RulesContext(university_id=context.university_id.value,citizenship=context.citizenship.value or 'unknown',
        student_category=context.student_category.value or 'unknown',entry_regime=context.entry_regime.value or 'unknown',
        residence=context.residence_type.value or 'unknown',age_category=age,
        visa_type=rule_visa_type,
        visa_expiry=confirmed_value(context.visa,'expiry_date'),new_visa_received=confirmed_value(context.visa,'received_at'),
        entry_date=confirmed_value(context.migration_card,'entry_date'))
    return evaluate_context(inputs,today=today)

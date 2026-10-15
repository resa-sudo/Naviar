"""Read versioned configuration and match explicitly supplied student context."""
import json
from datetime import date
from pathlib import Path
from .models import DeadlineRule, DeadlinePolicy, StudentContext
from .engine import calculate_deadline, source_status
from .calendar import BusinessCalendar

CONFIG = Path(__file__).resolve().parents[2] / 'config'


def load_policy():
    return DeadlinePolicy.model_validate_json((CONFIG / 'deadline_policy.json').read_text(encoding='utf-8-sig'))


def load_rules(university_id):
    manifest = json.loads((CONFIG / 'rules/manifest.json').read_text(encoding='utf-8-sig'))
    version = manifest['active_versions'].get(university_id)
    if version is None:
        return []
    # Paths are taken from trusted local manifest, not assembled for unknown IDs.
    data = json.loads((CONFIG / 'rules' / university_id / f'{version}.json').read_text(encoding='utf-8-sig'))
    rules = [DeadlineRule.model_validate(row) for row in data['rules']]
    if any(r.university_id != university_id or r.version != version for r in rules):
        raise ValueError('rule_version_mismatch')
    return rules


def evaluate_context(context: StudentContext, *, today=None):
    today = today or date.today()
    policy = load_policy()
    values = context.model_dump(mode='json')
    from .entry_regimes import entry_regime_for, citizenship_code
    values['citizenship'] = citizenship_code(context.citizenship)
    medical = context.medical_certificates.model_dump(mode='json')
    medical_confirmed = context.medical_certificates.status == 'confirmed'
    medical['days_remaining'] = (context.medical_certificates.valid_until-today).days if medical_confirmed and context.medical_certificates.valid_until else None
    insurance = context.insurance.model_dump(mode='json')
    insurance['days_remaining'] = (context.insurance.valid_until-today).days if context.insurance.valid_until else None
    rows = []
    for rule in load_rules(context.university_id):
        if rule.country_of_study != context.country_of_study:
            continue
        if context.entry_regime != 'unknown' and context.entry_regime not in rule.entry_regime:
            continue
        if context.student_category != 'unknown' and context.student_category not in rule.student_category:
            continue
        missing = []
        if context.entry_regime == 'unknown':
            missing.append('entry_regime')
        if context.student_category == 'unknown':
            missing.append('student_category')
        unmatched = [key for key, value in rule.conditions.items() if values.get(key) != value]
        missing.extend(unmatched)
        trigger = getattr(context, rule.trigger_date_field, None)
        if rule.trigger_date_field == 'medical_completed_at':
            trigger = context.medical_certificates.completed_at if medical_confirmed else None
        result = calculate_deadline(rule, trigger, BusinessCalendar(rule.country_of_study), today=today, policy=policy)
        if missing:
            result.update(deadline_date=None, recommended_action_date=None, days_remaining_calendar=None,
                          days_remaining_business=None, status='unknown', action_required='Требуется уточнение', reason='applicability_not_confirmed')
        requirements = []
        requirements_pending = False
        # Never serve a generic checklist for an unresolved scenario/source.
        if not missing and source_status(rule, today, policy) == 'verified' and result['reason'] not in {'rule_outside_validity','trigger_outside_scope'}:
            for item in rule.required_documents:
                if any(values.get(key) == 'unknown' for key in item.conditions):
                    requirements_pending = True
                elif all(values.get(key) == value for key, value in item.conditions.items()):
                    requirements.append(item.title)
        if rule.procedure_type == 'medical_renewal':
            medical['next_required_at'] = result['deadline_date']
            if result['deadline_date']:
                medical['days_remaining'] = result['days_remaining_calendar']
        expiry = context.visa_expiry if rule.document_type == 'visa' else context.stay_expiry if rule.document_type == 'registration' and rule.trigger_type == 'document_expiry' else None
        rows.append(dict(rule_id=rule.rule_id,title=rule.title,document_type=rule.document_type,
                         day_type=rule.day_type,procedure_type=rule.procedure_type,
                         expiry_date=expiry, expiry_days_remaining=(expiry-today).days if expiry else None,
                         result=result, missing_context=missing, required_documents=requirements,
                         requirements_pending=requirements_pending, submission_place=rule.submission_place,
                         address=rule.address, appointment_required=rule.appointment_required,
                         online_service_name=rule.online_service_name, processing_time_days=rule.processing_time_days,
                         processing_time_type=rule.processing_time_type, notes=rule.notes,
                         review_reason=rule.review_reason, related_sources=[s.model_dump(mode='json') for s in rule.related_sources]))
    return dict(today=today,university_id=context.university_id,procedures=rows,
                entry_regime=context.entry_regime, entry_regime_determined=entry_regime_for(context.citizenship) != 'unknown',
                medical_certificates=medical, insurance=insurance,
                message=None if rows else 'Правила для выбранного университета или категории пока не подтверждены.',
                medical_categories=['Медицинское освидетельствование','Дактилоскопия','ДМС'])

"""Deterministic next actions; only confirmed rule results become deadlines."""
from pydantic import BaseModel
from datetime import date


class NextAction(BaseModel):
    title: str
    priority: str
    reason: str
    deadline: date | None = None
    days_remaining: int | None = None
    destination: str | None = None
    source_rule: dict | None = None
    document_type: str | None = None
    field: str | None = None


RANK = {'overdue':0,'due_today':1,'urgent':2,'attention':3,'missing':4,'safe':5}


def next_actions(context, results):
    actions=[]
    for row in results['procedures']:
        result=row['result']
        if result['deadline_date'] is None or result['status']=='unknown': continue
        actions.append(NextAction(title='Подать документы на продление визы' if row['procedure_type']=='visa_extension' else row['title'],
            priority=result['status'],reason='Срок рассчитан по подтверждённым данным и правилу университета.',
            deadline=result['deadline_date'],days_remaining=result['days_remaining_business'] if row['day_type']=='business_days' else result['days_remaining_calendar'],
            destination=row['submission_place'],source_rule=result['rule_source'],document_type=row['document_type']))
    for kind,key,title in [('visa','expiry_date','Нужна дата окончания визы'),('migration_card','entry_date','Проверьте дату въезда'),('registration','expiry_date','Нужна дата окончания регистрации')]:
        if kind=='visa' and context.entry_regime.value!='visa_required': continue
        group=getattr(context,kind)
        if group[key].confirmed: continue
        actions.append(NextAction(title=title,priority='missing',reason='Укажите одно недостающее значение в документе.' if group['document_id'].value else 'Сначала добавьте документ.',document_type=kind,field=key))
    if context.passport['document_id'].value and not context.passport['confirmed'].value:
        actions.append(NextAction(title='Проверьте данные паспорта',priority='missing',reason='Подтвердите данные перед использованием.',document_type='passport'))
    return sorted(actions,key=lambda action:(RANK[action.priority],action.deadline or date.max))[:3]

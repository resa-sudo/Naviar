"""Pure deadline calculation; no university names, storage or network."""
from datetime import date, timedelta
from .models import DeadlineRule, DeadlinePolicy
from .calendar import BusinessCalendar, CalendarMissing


def source_status(rule, today, policy):
    dates = [rule.source_last_verified_at, *[s.last_verified_at for s in rule.related_sources]]
    if any((today - checked).days > policy.source_max_age_days or checked > today for checked in dates):
        return 'needs_reverification'
    return rule.review_status


def calculate_deadline(rule: DeadlineRule, trigger_date: date | None, calendar: BusinessCalendar,
                       *, today: date | None = None, policy: DeadlinePolicy | None = None):
    today = today or date.today()
    policy = policy or DeadlinePolicy()
    review = source_status(rule, today, policy)
    result = dict(trigger_date=trigger_date, deadline_date=None, days_remaining_calendar=None,
                  days_remaining_business=None, status='unknown', action_required='Требуется уточнение',
                  reason=None, recommended_action_date=None, warnings=[],
                  rule_source=dict(title=rule.official_source_title, url=str(rule.official_source_url),
                                   last_verified_at=rule.source_last_verified_at, status=review,
                                   rule_id=rule.rule_id, version=rule.version))
    if review != 'verified':
        result['reason'] = review
        return result
    if (rule.valid_from and today < rule.valid_from) or (rule.valid_to and today > rule.valid_to):
        result['reason'] = 'rule_outside_validity'
        return result
    if trigger_date is None:
        result['reason'] = 'trigger_date_missing'
        return result
    if rule.trigger_valid_from and trigger_date < rule.trigger_valid_from:
        result['reason'] = 'trigger_outside_scope'
        return result
    if rule.country_of_study != calendar.country:
        result['reason'] = 'calendar_country_mismatch'
        return result
    sign = -1 if rule.direction == 'before' else 1
    try:
        deadline = (calendar.shift(trigger_date, sign * rule.offset_days) if rule.day_type == 'business_days'
                    else trigger_date + timedelta(days=sign * rule.offset_days))
    except (CalendarMissing, OverflowError) as error:
        result['reason'] = str(error) if isinstance(error, CalendarMissing) else 'date_out_of_range'
        return result
    calendar_days = (deadline - today).days
    try:
        business_days = calendar.between(today, deadline)
    except CalendarMissing as error:
        business_days = None
        result['warnings'].append(str(error))
    result.update(deadline_date=deadline, days_remaining_calendar=calendar_days, days_remaining_business=business_days)
    distance = calendar_days if policy.status_day_type == 'calendar_days' else business_days
    if calendar_days < 0:
        status = 'overdue'
    elif calendar_days == 0:
        status = 'due_today'
    elif distance is None:
        status = 'unknown'
    elif distance <= policy.urgent_days:
        status = 'urgent'
    elif distance <= policy.attention_days:
        status = 'attention'
    else:
        status = 'safe'
    result.update(status=status, action_required='Посмотреть порядок действий' if status == 'overdue' else 'Что подготовить',
                  reason='calculated_excluding_trigger' if status != 'unknown' else 'calendar_missing')
    if rule.recommended_buffer_days:
        result['recommended_action_date'] = deadline - timedelta(days=rule.recommended_buffer_days)
    return result

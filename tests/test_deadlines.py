"""Deadline arithmetic uses synthetic rule variants, never activates draft seeds."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from app.deadlines.calendar import BusinessCalendar, CalendarMissing
from app.deadlines.engine import calculate_deadline
from app.deadlines.models import DeadlinePolicy, StudentContext, ServiceLocation
from app.deadlines.rules import load_rules, evaluate_context, CONFIG
from app import deadline_api

TODAY = date(2026,9,29)


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.calendar=BusinessCalendar()
        self.rule=next(r for r in load_rules('rudn') if r.procedure_type=='registration_after_new_visa')

    def calculate(self, trigger, **changes):
        return calculate_deadline(self.rule.model_copy(update=changes),trigger,self.calendar,today=TODAY)

    def context(self, **changes):
        return StudentContext(**dict(dict(university_id='rudn',citizenship='tm',student_category='foreign_student',entry_regime='visa_required',residence='university_dormitory',visa_type='multiple_entry',age_category='adult',new_visa_received='2026-09-29'),**changes))

    def test_twenty_business_days_before(self):
        result=self.calculate(date(2026,10,30),offset_days=20,direction='before')
        self.assertEqual(result['deadline_date'],date(2026,10,2))
        self.assertEqual(result['days_remaining_business'],3)
        self.assertEqual(result['days_remaining_calendar'],3)

    def test_twenty_calendar_days_before(self):
        self.assertEqual(self.calculate(date(2026,10,30),offset_days=20,direction='before',day_type='calendar_days')['deadline_date'],date(2026,10,10))

    def test_thirty_calendar_days_after(self):
        self.assertEqual(self.calculate(date(2026,9,1),offset_days=30,day_type='calendar_days')['deadline_date'],date(2026,10,1))

    def test_three_business_days_after(self):
        self.assertEqual(self.calculate(date(2026,10,2))['deadline_date'],date(2026,10,7))

    def test_weekends_and_transfer_dates(self):
        for day in (date(2026,1,9),date(2026,3,9),date(2026,5,11),date(2026,12,31),date(2026,10,3),date(2026,10,4)):
            self.assertFalse(self.calendar.is_business_day(day))
        self.assertTrue(self.calendar.is_business_day(date(2026,1,12)))
        self.assertEqual(self.calendar.shift(date(2026,5,7),3),date(2026,5,13))

    def test_official_holidays(self):
        for day in (date(2026,1,1),date(2026,1,7),date(2026,2,23),date(2026,5,1),date(2026,6,12),date(2026,11,4)):
            self.assertFalse(self.calendar.is_business_day(day))
        self.assertEqual(self.calendar.shift(date(2026,11,3),1),date(2026,11,5))

    def test_new_year_without_next_calendar(self):
        result=self.calculate(date(2026,12,30),offset_days=1)
        self.assertIsNone(result['deadline_date'])
        self.assertEqual(result['status'],'unknown')
        self.assertIn('calendar_missing:2027',result['reason'])

    def test_new_year_with_explicit_synthetic_calendar(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'RU'; root.mkdir()
            (root/'2026.json').write_text((CONFIG/'calendars/RU/2026.json').read_text(encoding='utf-8'),encoding='utf-8')
            # Toy next-year data, not published or claimed to be an official calendar.
            (root/'2027.json').write_text(json.dumps(dict(country='RU',year=2027,status='verified',weekend_weekdays=[5,6],working_weekends=[],non_working_dates=['2027-01-01'])),encoding='utf-8')
            self.assertEqual(BusinessCalendar(directory=folder).shift(date(2026,12,30),1),date(2027,1,4))

    def test_missing_previous_year(self):
        result=self.calculate(date(2026,1,12),offset_days=1,direction='before')
        self.assertEqual(result['reason'],'calendar_missing:2025')

    def test_calendar_days_can_cross_missing_year(self):
        result=self.calculate(date(2026,12,20),offset_days=30,day_type='calendar_days')
        self.assertEqual(result['deadline_date'],date(2027,1,19))
        self.assertIsNone(result['days_remaining_business'])
        self.assertIn('calendar_missing:2027',result['warnings'])

    def test_today_and_overdue(self):
        self.assertEqual(self.calculate(date(2026,9,29),offset_days=0)['status'],'due_today')
        self.assertEqual(self.calculate(date(2026,9,28),offset_days=0)['status'],'overdue')

    def test_status_policy_configurable(self):
        for days, expected in ((1,'urgent'),(7,'attention'),(20,'safe')):
            r=self.calculate(TODAY,offset_days=days,day_type='calendar_days')
            self.assertEqual(r['status'],expected)
        r=calculate_deadline(self.rule,TODAY,self.calendar,today=TODAY,policy=DeadlinePolicy(urgent_days=0,attention_days=1))
        self.assertEqual(r['status'],'safe')

    def test_missing_trigger_and_country(self):
        self.assertEqual(self.calculate(None)['reason'],'trigger_date_missing')
        r=calculate_deadline(self.rule,TODAY,BusinessCalendar('KZ'),today=TODAY)
        self.assertEqual(r['reason'],'calendar_country_mismatch')

    def test_stale_source_and_validity(self):
        result=self.calculate(TODAY,source_last_verified_at=date(2026,1,1))
        self.assertIsNone(result['deadline_date'])
        self.assertEqual(result['rule_source']['status'],'needs_reverification')
        self.assertEqual(self.calculate(TODAY,valid_to=date(2026,9,28))['reason'],'rule_outside_validity')

    def test_different_universities_do_not_mix(self):
        self.assertEqual(load_rules('msu'),[])
        self.assertEqual(evaluate_context(self.context(university_id='msu'),today=TODAY)['procedures'],[])

    def test_entry_regimes_are_separate(self):
        visa=evaluate_context(self.context(),today=TODAY)['procedures']
        free=evaluate_context(self.context(citizenship='unknown',entry_regime='visa_free'),today=TODAY)['procedures']
        self.assertIn('visa_extension',[r['procedure_type'] for r in visa])
        self.assertNotIn('visa_extension',[r['procedure_type'] for r in free])
        self.assertNotIn('registration_after_new_visa',[r['procedure_type'] for r in free])

    def test_citizenship_does_not_guess_regime(self):
        rows=evaluate_context(self.context(citizenship='uz',entry_regime='unknown'),today=TODAY)['procedures']
        self.assertTrue(all(r['result']['status']=='unknown' and not r['required_documents'] for r in rows))

    def test_conflicting_seed_rules_are_not_activated(self):
        for rule in load_rules('rudn'):
            if rule.review_status!='verified':
                result=calculate_deadline(rule,TODAY,self.calendar,today=TODAY)
                self.assertIsNone(result['deadline_date'])
                self.assertEqual(result['reason'],'requires_clarification')

    def test_applicability_and_conditional_checklists(self):
        def registration(context):
            return next(r for r in evaluate_context(context,today=TODAY)['procedures'] if r['procedure_type']=='registration_after_new_visa')
        self.assertEqual(len(registration(self.context())['required_documents']),6)
        self.assertEqual(len(registration(self.context(age_category='minor'))['required_documents']),7)
        self.assertTrue(registration(self.context(age_category='unknown'))['requirements_pending'])
        other=registration(self.context(residence='other'))
        self.assertIsNone(other['result']['deadline_date'])
        self.assertEqual(other['required_documents'],[])

    def test_model_validation_and_location(self):
        with self.assertRaises(ValidationError):
            self.context(university_id='../rudn')
        with self.assertRaises(ValidationError):
            self.context(visa_expiry='2026-02-30')
        locations=json.loads((CONFIG/'service_locations.json').read_text(encoding='utf-8'))
        self.assertEqual(ServiceLocation.model_validate(locations[0]).name,'МФЦ РУДН')

    def test_local_context_persists_separately(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(deadline_api,'STATE_DIRECTORY',Path(folder)):
            self.assertIsNone(deadline_api.get_state()['context'])
            deadline_api.save_state(self.context())
            self.assertEqual(deadline_api.get_state()['context']['new_visa_received'],'2026-09-29')
            self.assertEqual([p.name for p in Path(folder).iterdir()],['context.json'])

    def test_signed_business_day_count(self):
        self.assertEqual(self.calendar.between(date(2026,10,2),date(2026,10,7)),3)
        self.assertEqual(self.calendar.between(date(2026,10,7),date(2026,10,2)),-3)
        self.assertEqual(self.calendar.between(TODAY,TODAY),0)

    def test_trigger_scope_is_separate_from_rule_validity(self):
        result=self.calculate(date(2026,8,31),trigger_valid_from=date(2026,9,1),offset_days=30,day_type='calendar_days')
        self.assertIsNone(result['deadline_date'])
        self.assertEqual(result['reason'],'trigger_outside_scope')

    def test_tkm_regime_cannot_be_overridden(self):
        for code in ('TKM','tkm','tm','TM'):
            context=self.context(citizenship=code,entry_regime='visa_free')
            self.assertEqual(context.entry_regime,'visa_required')
            result=evaluate_context(context,today=TODAY)
            self.assertTrue(result['entry_regime_determined'])
            self.assertNotIn('stay_extension',[r['procedure_type'] for r in result['procedures']])
        self.assertEqual(self.context(university_id='msu').entry_regime,'visa_required')

    def test_active_visa_deadline(self):
        rows=evaluate_context(self.context(visa_expiry='2026-10-30',visa_type='unknown'),today=TODAY)['procedures']
        row=next(r for r in rows if r['procedure_type']=='visa_extension')
        self.assertEqual(row['result']['deadline_date'],date(2026,10,2))
        self.assertEqual(row['result']['days_remaining_business'],3)
        self.assertEqual(row['expiry_days_remaining'],31)
        self.assertEqual(row['required_documents'],[])

    def test_visa_today_and_overdue(self):
        context=self.context(visa_expiry='2026-10-30')
        for today,status in ((date(2026,10,2),'due_today'),(date(2026,10,5),'overdue')):
            row=next(r for r in evaluate_context(context,today=today)['procedures'] if r['procedure_type']=='visa_extension')
            self.assertEqual(row['result']['status'],status)

    def test_visa_checklist_scope(self):
        for changes,expected in (({},9),({'citizenship':'unknown'},0),({'visa_type':'other'},0)):
            row=next(r for r in evaluate_context(self.context(**changes),today=TODAY)['procedures'] if r['procedure_type']=='visa_extension')
            self.assertEqual(len(row['required_documents']),expected)

    def test_medical_dates_and_insurance_counts(self):
        context=self.context(medical_certificates={'status':'confirmed','completed_at':'2026-09-01','valid_until':'2026-10-30'},insurance={'valid_from':'2026-01-01','valid_until':'2026-10-02','provider':'Demo','policy_number':'DEMO'})
        result=evaluate_context(context,today=TODAY)
        self.assertEqual(result['medical_certificates']['days_remaining'],31)
        self.assertIsNone(result['medical_certificates']['next_required_at'])
        self.assertEqual(result['insurance']['days_remaining'],3)

    def test_medical_no_invented_deadline(self):
        result=evaluate_context(self.context(medical_certificates={'completed_at':'2026-09-01','valid_until':'2026-10-30','next_required_at':'2026-11-01','days_remaining':999}),today=TODAY)
        self.assertIsNone(result['medical_certificates']['next_required_at'])
        self.assertIsNone(result['medical_certificates']['days_remaining'])
        for row in result['procedures']:
            if row['document_type']=='medical_examination':
                self.assertIsNone(row['result']['deadline_date'])

    def test_medical_persistence(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(deadline_api,'STATE_DIRECTORY',Path(folder)):
            deadline_api.save_state(self.context(medical_certificates={'status':'confirmed','completed_at':'2026-09-01','valid_until':'2026-10-30'},fingerprinting={'status':'completed'}))
            saved=deadline_api.get_state()['context']
            self.assertEqual(saved['medical_certificates']['completed_at'],'2026-09-01')
            self.assertEqual(saved['medical_certificates']['valid_until'],'2026-10-30')
            self.assertEqual(saved['fingerprinting']['status'],'completed')

    def test_medical_and_insurance_validation(self):
        for changes in ({'medical_certificates':{'status':'confirmed'}},{'medical_certificates':{'completed_at':'2026-09-01','valid_until':'2026-08-01'}},{'fingerprinting':{'status':'repeat_annually'}},{'insurance':{'valid_from':'2026-10-01','valid_until':'2026-09-01'}}):
            with self.assertRaises(ValidationError): self.context(**changes)

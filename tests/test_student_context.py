"""Student read-model uses isolated source records, never real documents."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app import documents, student_api
from app.student_context import build_context, rule_results
from app.next_actions import next_actions
from test_documents import PNG
import test_documents as fixtures


class StudentContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for module,name,value in [(documents,'UPLOAD_DIRECTORY',Path(self.temp.name)/'uploads'),(student_api,'STATE_DIRECTORY',Path(self.temp.name)/'student')]:
            guard=patch.object(module,name,value);guard.start();self.addCleanup(guard.stop)
        self.profile=student_api.save_profile(student_api.Profile(citizenship='tm',university='rudn',degree='bachelor',language='ru'))['profile']

    def context(self): return build_context(self.profile,documents.read_index())
    def upload(self,kind='visa'): return documents.save_document(kind,'demo.png','image/png',PNG)
    def confirm(self,record,key,value): return student_api.confirm_field(record['type'],record['document_id'],student_api.ManualField(field=key,value=value,confirmed=True))

    def test_profile_and_derived_regime(self):
        context=self.context()
        self.assertEqual(context.citizenship.value,'TKM');self.assertEqual(context.citizenship.source,'profile')
        self.assertEqual(context.entry_regime.value,'visa_required');self.assertEqual(context.entry_regime.source,'derived_rule')
        self.assertEqual(context.university_id.value,'rudn');self.assertEqual(context.study_level.value,'bachelor')
        self.assertEqual(context.student_category.value,'foreign_student')

    def test_profile_id_is_stable(self):
        updated=student_api.save_profile(student_api.Profile(citizenship='tm',university='rudn',degree='master',language='ru'))['profile']
        self.assertEqual(updated['student_id'],self.profile['student_id'])
        self.assertEqual(student_api.read_profile()['degree'],'master')

    def test_missing_document_never_invents_dates(self):
        context=self.context()
        self.assertIsNone(context.visa['expiry_date'].value)
        self.assertFalse(context.visa['expiry_date'].confirmed)
        actions=next_actions(context,rule_results(context,today=date(2026,9,29)))
        self.assertTrue(any(a.field=='expiry_date' and a.document_type=='visa' for a in actions))
        self.assertTrue(all(a.deadline is None for a in actions))

    def test_manual_confirmation_drives_rule_and_action(self):
        record=self.upload();self.confirm(record,'expiry_date','2026-10-30')
        context=self.context();rules=rule_results(context,today=date(2026,9,29))
        action=next_actions(context,rules)[0]
        self.assertEqual(action.deadline,date(2026,10,2));self.assertEqual(action.days_remaining,3)
        self.assertEqual(action.destination,'МФЦ РУДН');self.assertEqual(action.source_rule['rule_id'],'rudn.visa_extension')
        self.assertEqual(context.visa['expiry_date'].source,'manual_fallback')

    def test_unconfirmed_ocr_cannot_drive_deadlines(self):
        self.upload();index=documents.read_index();index['visa']['extracted_fields']={'expiry_date':{'value':'2026-10-30','confidence':.95}};documents.write_index(index)
        context=self.context();self.assertEqual(context.visa['expiry_date'].source,'visa_ocr')
        self.assertFalse(context.visa['expiry_date'].confirmed)
        self.assertTrue(all(row['result']['deadline_date'] is None for row in rule_results(context,today=date(2026,9,29))['procedures']))

    def test_manual_override_outranks_ocr(self):
        record=self.upload();index=documents.read_index();index['visa']['extracted_fields']={'expiry_date':{'value':'2026-10-30','confidence':.99}};documents.write_index(index)
        self.confirm(record,'expiry_date','2026-10-31')
        self.assertEqual(self.context().visa['expiry_date'].value,'2026-10-31')
        self.assertEqual(self.context().visa['expiry_date'].source,'manual_fallback')
        self.assertIsNone(self.context().visa['expiry_date'].confidence)

    def test_confirmed_passport_is_read_without_copying(self):
        self.upload('passport');index=documents.read_index();index['passport'].update(status='verified',passport_data=fixtures.DocumentTests.demo_passport())
        documents.write_index(index);before=(documents.UPLOAD_DIRECTORY/'index.json').read_bytes()
        context=self.context();self.assertTrue(context.passport['confirmed'].value)
        self.assertEqual(context.passport['passport_number'].source,'manual_confirmed')
        self.assertEqual(context.passport['passport_number'].value,index['passport']['passport_data']['passport_number'])
        self.assertEqual((documents.UPLOAD_DIRECTORY/'index.json').read_bytes(),before)
        self.assertEqual([p.name for p in student_api.STATE_DIRECTORY.iterdir()],['profile.json'])

    def test_removed_document_removes_context_and_fallback(self):
        record=self.upload();self.confirm(record,'expiry_date','2026-10-30');documents.delete_document(documents.DocumentType.visa)
        self.assertIsNone(self.context().visa['expiry_date'].value)
        self.upload();self.assertIsNone(self.context().visa['expiry_date'].value)

    def test_old_form_cannot_confirm_new_file(self):
        old=self.upload();documents.delete_document(documents.DocumentType.visa);self.upload()
        with self.assertRaises(HTTPException) as error: self.confirm(old,'expiry_date','2026-10-30')
        self.assertEqual(error.exception.status_code,409)

    def test_invalid_dates_are_rejected(self):
        record=self.upload()
        for value in ('2026-02-30','not-a-date','20261030'):
            with self.assertRaises(HTTPException): self.confirm(record,'expiry_date',value)
        self.confirm(record,'issue_date','2026-09-01')
        with self.assertRaises(HTTPException): self.confirm(record,'expiry_date','2026-08-01')

    def test_medical_presence_and_dates(self):
        record=documents.save_document('medical_certificates','demo.png','image/png',PNG,medical_type='medical_hiv_certificate')
        from app.medical_models import MedicalFileDates
        documents.save_medical_dates(record['document_id'],MedicalFileDates(issue_date='2026-09-01',valid_until='2026-10-30'))
        medical=self.context().medical
        self.assertEqual(medical['completion_count'].value,1)
        self.assertTrue(medical['hiv_certificate_present'].value)
        self.assertEqual(medical['relevant_dates']['medical_hiv_certificate']['issue_date'].source,'medical_document')

    def test_next_action_urgency_and_limit(self):
        record=self.upload();self.confirm(record,'expiry_date','2026-10-30')
        context=self.context();actions=next_actions(context,rule_results(context,today=date(2026,10,5)))
        self.assertEqual(actions[0].priority,'overdue');self.assertLessEqual(len(actions),3)

    def test_unknown_country_does_not_guess_regime(self):
        profile={**self.profile,'citizenship':'other'}
        context=build_context(profile,{})
        self.assertIsNone(context.entry_regime.value);self.assertIsNone(context.student_category.value)

    def test_debug_planning_does_not_override_student_sources(self):
        from app import deadline_api
        from app.deadlines.models import StudentContext as RulesContext
        with patch.object(deadline_api,'STATE_DIRECTORY',Path(self.temp.name)/'planning'):
            deadline_api.save_state(RulesContext(university_id='rudn',citizenship='tm',student_category='foreign_student',visa_expiry='2026-10-30'))
            self.upload()
            result=student_api.get_context()
            self.assertIsNone(result['context'].visa['expiry_date'].value)
            self.assertTrue(all(row['result']['deadline_date'] is None for row in result['rules']['procedures']))

"""Pure synthetic layout/MRV regressions, no OCR downloads or user files."""
import unittest
from pathlib import Path
from app.document_engine.models import OCRLine,OCRResult
from app.visa_engine.engine import VisaEngine
from app.visa_engine.mrz import parse_mrz,check_digit
from app.visa_engine.normalization import normalize_date,normalize_choice,ENTRIES,VISA_TYPES
from app.visa_engine.visual import extract_visual
from app.visa_engine.models import VisaData
from scripts.visa_fixture import layout,mrz_rows

class VisaEngineTests(unittest.TestCase):
    def process(self,lines):
        class Provider:
            def extract(self,path,context): return OCRResult(lines)
        return VisaEngine(Provider()).process(Path('synthetic.png'))

    def test_supported_layout(self):
        result=self.process(layout(False));self.assertEqual(result['processing_status'],'success')
        self.assertEqual(result['detected_document_type'],'visa')
        self.assertTrue(all(v['needs_confirmation'] for v in result['extracted_fields'].values()))

    def test_missing_expiry_still_partial_supported_visa(self):
        lines=layout(False);del lines[11:13]
        result=self.process(lines)
        self.assertEqual(result['processing_status'],'partial')
        self.assertIsNone(result['extracted_fields']['valid_until']['value'])
        self.assertEqual(result['extracted_fields']['visa_number']['value'],'TEST00001')

    def test_blank_image_is_unsupported_not_provider_failure(self):
        result=self.process([])
        self.assertEqual(result['processing_status'],'unsupported_or_not_visa')
        self.assertEqual(result['errors'],[])

    def test_random_certificate(self):
        result=self.process([OCRLine('CERTIFICATE visa number 1234',.99,(0,0,500,40))])
        self.assertEqual(result['processing_status'],'unsupported_or_not_visa')
        self.assertTrue(all(v['value'] is None for v in result['extracted_fields'].values()))

    def test_number_and_dates_not_mixed(self):
        fields=self.process(layout(False))['extracted_fields']
        for key,value in [('visa_number','TEST00001'),('issue_date','2026-09-15'),('valid_from','2026-09-16'),('valid_until','2026-10-30')]:
            self.assertEqual(fields[key]['value'],value)
            self.assertEqual(fields[key]['source'],'visual_ocr')

    def test_all_date_formats(self):
        for raw in ['30.10.2026','30/10/2026','2026-10-30','30102026','30 10 2026']:
            with self.subTest(raw=raw): self.assertEqual(normalize_date(raw),'2026-10-30')
        self.assertIsNone(normalize_date('30.10.26'))
        self.assertEqual(normalize_date('30.10.26',2026),'2026-10-30')

    def test_invalid_dates(self):
        for raw in ['32132020','29022023','123456789','26-10-30','2026-02-30']:
            self.assertIsNone(normalize_date(raw))
        self.assertEqual(normalize_date('29022024'),'2024-02-29')

    def test_entries_mapping(self):
        for raw,value in [('SINGLE','single'),('1','single'),('DOUBLE','double'),('2','double'),('MULT','multiple'),('MULTIPLE','multiple'),('МНОГОКРАТНАЯ','multiple')]:
            self.assertEqual(normalize_choice(raw,ENTRIES),value)
        self.assertEqual(normalize_choice('SINGLE DOUBLE',ENTRIES),'unknown')

    def test_visa_type_mapping(self):
        for raw in ['STUDENT','STUDY','УЧЕБНАЯ']:
            self.assertEqual(normalize_choice(raw,VISA_TYPES),'student')
        for raw in ['C','STUDENT TOURIST','?', 'visa']:
            self.assertEqual(normalize_choice(raw,VISA_TYPES),'unknown')

    def test_two_candidates_unresolved(self):
        lines=[OCRLine('Valid until',.99,(0,0,120,30)),OCRLine('30.10.2026',.99,(140,0,290,30)),OCRLine('31.10.2026',.99,(0,50,150,80))]
        self.assertIsNone(extract_visual(lines)[0]['valid_until'].value)

    def test_birth_label_owns_date(self):
        lines=[OCRLine('Valid until',.99,(0,0,140,30)),OCRLine('Date of birth',.99,(0,60,140,90)),OCRLine('30.10.2026',.99,(160,60,310,90))]
        self.assertIsNone(extract_visual(lines)[0]['valid_until'].value)

    def test_label_above_date(self):
        fields,_=extract_visual([OCRLine('Valid from',.99,(0,0,120,30)),OCRLine('16/09/2026',.99,(0,45,170,75))])
        self.assertEqual(fields['valid_from'].value,'2026-09-16')

    def test_no_label(self):
        self.assertIsNone(extract_visual([OCRLine('30.10.2026',.99,(0,0,180,30))])[0]['valid_until'].value)

    def test_low_confidence_and_weak_geometry(self):
        for score,x in [(.89,140),(.99,2000)]:
            fields,_=extract_visual([OCRLine('Valid until',score,(0,0,120,30)),OCRLine('30.10.2026',.99,(x,0,x+180,30))])
            self.assertIsNone(fields['valid_until'].value)

    def test_mrv_a_b(self):
        for width,name in [(44,'MRV-A'),(36,'MRV-B')]:
            result=parse_mrz([OCRLine(row,.98) for row in mrz_rows(width)])
            self.assertTrue(result['valid']);self.assertEqual(result['format'],name)
        result=self.process(layout())
        for key in ('visa_number','valid_until','citizenship'): self.assertEqual(result['extracted_fields'][key]['source'],'mrz')

    def test_bad_checksum(self):
        first,second=mrz_rows();second=second[:27]+str((int(second[27])+1)%10)+second[28:]
        self.assertFalse(parse_mrz([OCRLine(first),OCRLine(second)])['valid'])

    def test_invalid_mrz_calendar(self):
        first,second=mrz_rows();raw='261332'
        second=second[:21]+raw+check_digit(raw)+second[28:]
        self.assertFalse(parse_mrz([OCRLine(first,.99),OCRLine(second,.99)])['valid'])

    def test_passport_not_visa(self):
        first,second=mrz_rows()
        self.assertFalse(parse_mrz([OCRLine('P'+first[1:]),OCRLine(second)])['found'])

    def test_mrz_number_semantics_and_century_unresolved(self):
        result=self.process([OCRLine(row,.99) for row in mrz_rows()])
        for key in ('visa_number','passport_number_if_present','valid_until'):
            self.assertIsNone(result['extracted_fields'][key]['value'])
        self.assertEqual(result['processing_status'],'partial')

    def test_conflicting_expiry(self):
        lines=layout();lines[12]=OCRLine('2026-10-31',.99,lines[12].bbox)
        result=self.process(lines)
        self.assertIsNone(result['extracted_fields']['valid_until']['value'])
        self.assertIn('expiry_conflict',result['errors'])

    def test_date_order(self):
        with self.assertRaises(ValueError): VisaData(issue_date='2026-09-15',valid_until='2026-08-01')
        with self.assertRaises(ValueError): VisaData(valid_from='2027-01-01',valid_until='2026-10-30')
        with self.assertRaises(ValueError): VisaData()
        with self.assertRaises(ValueError): VisaData(visa_number='test\nsecret')

    def test_provider_error_is_sanitized(self):
        class Provider:
            def extract(self,*args): raise RuntimeError('secret path')
        result=VisaEngine(Provider()).process(Path('synthetic.png'))
        self.assertEqual(result['errors'],['ocr_failed']);self.assertEqual(result['processing_status'],'failed')

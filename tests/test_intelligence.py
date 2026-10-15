"""Synthetic passport intelligence cases; no real documents."""
from datetime import date
from pathlib import Path
import unittest
from app.document_engine.engine import DocumentEngine
from app.document_engine.models import OCRLine, OCRResult, ProcessingContext
from app.document_engine.mrz import parse_td3
from app.document_engine.detection import detect_td3
from app.document_engine.visual_dates import extract_issue_date
from test_mrz import FIRST, SECOND

TODAY = date(2026, 9, 29)


class IntelligenceTests(unittest.TestCase):
    def process(self, lines):
        class Provider:
            def extract(self, path, context):
                return OCRResult(lines)
        return DocumentEngine(Provider()).process(Path('synthetic.png'), ProcessingContext('passport'), today=TODAY)

    def test_td3_detected_and_dates_resolved(self):
        result = self.process([OCRLine(FIRST, .96), OCRLine(SECOND, .97)])
        self.assertTrue(result.detection['supported'])
        self.assertEqual(result.mrz.fields['date_of_birth'].value, '2000-01-01')
        self.assertEqual(result.mrz.fields['expiry_date'].value, '2030-01-01')
        self.assertEqual(result.date_resolution['date_of_birth']['confidence'], .97)
        self.assertTrue(all(f.needs_confirmation for f in result.mrz.fields.values()))

    def test_certificate_is_unsupported_and_not_prefilled(self):
        result = self.process([OCRLine('SYNTHETIC CERTIFICATE'), OCRLine('Date of issue: 2020-01-01', .99)])
        self.assertEqual(result.status, 'unsupported_or_not_passport')
        self.assertTrue(all(f.value is None for f in result.mrz.fields.values()))

    def test_partial_and_wrong_length_mrz(self):
        for lines in ([OCRLine(FIRST)], [OCRLine(FIRST), OCRLine(SECOND[:-1])], [OCRLine(FIRST[:-1]), OCRLine(SECOND)]):
            with self.subTest(lines=lines):
                result = self.process(lines)
                self.assertEqual(result.status, 'unsupported_or_not_passport')
                self.assertIn('partial_or_damaged_td3', result.detection['reasons'])
                self.assertTrue(all(f.value is None for f in result.mrz.fields.values()))

    def test_checks_required_but_nationality_typo_is_tolerated(self):
        damaged = SECOND[:10] + 'UT0' + SECOND[13:]
        result = self.process([OCRLine(FIRST), OCRLine(damaged)])
        self.assertEqual(result.status, 'partial')
        self.assertIsNone(result.mrz.fields['nationality'].value)
        bad = list(SECOND)
        for index in (9,19,27):
            bad[index] = str((int(bad[index]) + 1) % 10)
        lines = [OCRLine(FIRST), OCRLine(''.join(bad))]
        self.assertFalse(detect_td3(lines, parse_td3(lines)).supported)

    def test_visual_labelled_date_and_integration(self):
        lines = [OCRLine('Date of issue: 2020-01-15', .96), OCRLine(FIRST, .98), OCRLine(SECOND, .98)]
        result = self.process(lines)
        field = result.mrz.fields['date_of_issue']
        self.assertEqual(field.value, '2020-01-15')
        self.assertEqual(field.source, 'visual_ocr')
        self.assertEqual(field.confidence, .96)
        self.assertEqual(result.status, 'success')
        self.assertTrue(field.needs_confirmation)

    def test_visual_no_context_or_low_score_stays_empty(self):
        for text, score in [('2020-01-15', .99), ('Date of issue: 2020-01-15', .5), ('Date of issue: 2020-01-15', None)]:
            result = extract_issue_date([OCRLine(text, score)], today=TODAY)
            self.assertIsNone(result.field.value)
            self.assertEqual(len(result.candidate_dates), 1)
            self.assertTrue(result.reasons)

    def test_visual_ambiguous_order_competing_dates_and_context(self):
        cases = [
            [OCRLine('Date of issue: 01/02/2020', .99)],
            [OCRLine('Date of issue: 2020-01-15', .99), OCRLine('Date of issue: 2021-01-15', .98)],
            [OCRLine('Date of issue / expiry: 2020-01-15', .99)],
            [OCRLine('Date of issue: 2020-02-30', .99)],
            [OCRLine('Date of issue: 2035-01-01', .99)],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assertIsNone(extract_issue_date(lines, today=TODAY).field.value)
        result = extract_issue_date([OCRLine('Дата выдачи: 15.01.2020', .95)], today=TODAY)
        self.assertEqual(result.field.value, '2020-01-15')

    def test_visual_adjacent_label_and_date_consistency(self):
        lines = [OCRLine('Date of issue:', .96), OCRLine('2020-01-15', .97)]
        self.assertEqual(extract_issue_date(lines, today=TODAY).field.value, '2020-01-15')
        self.assertIsNone(extract_issue_date(lines, today=TODAY, birth_date='2021-01-01').field.value)
        self.assertIsNone(extract_issue_date(lines, today=TODAY, expiry_date='2019-01-01').field.value)

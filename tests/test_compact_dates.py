"""Compact dates and narrowly scoped near-threshold issue-label acceptance."""
from datetime import date
import unittest
from app.document_engine.models import OCRLine
from app.document_engine.visual_dates import extract_issue_date


class CompactDateTests(unittest.TestCase):
    def extract(self, raw='17092013', label_score=.8986, extra=(), box=(100,120,200,140), **context):
        lines = [OCRLine('Date of issue', label_score, (100,100,240,120)),
                 OCRLine(raw, .99, box), *extra]
        return extract_issue_date(lines, today=date(2026,9,29), **context)

    def test_compact_examples(self):
        for raw, expected in [('17092013','2013-09-17'),('01012020','2020-01-01'),('31122025','2025-12-31'),('29022024','2024-02-29')]:
            with self.subTest(raw=raw):
                self.assertEqual(self.extract(raw).field.value, expected)

    def test_unique_near_threshold_confidence(self):
        r = self.extract()
        self.assertEqual(r.field.source, 'visual_ocr')
        self.assertTrue(r.field.needs_confirmation)
        self.assertAlmostEqual(r.field.confidence, .8986)
        self.assertEqual(r.selection_reason, 'near_threshold_unique_issue_date')
        self.assertEqual(r.selected_candidate['confidence_basis']['ambiguity_penalty'], 1)
        farther = self.extract(box=(100,130,200,150))
        self.assertLess(farther.field.confidence, r.field.confidence)

    def test_two_nearby_candidates_are_unresolved(self):
        r = self.extract(extra=[OCRLine('18092013', .99, (250,100,350,120))])
        self.assertIsNone(r.field.value)
        self.assertEqual(r.field.source, 'unresolved')
        self.assertTrue(r.field.needs_confirmation)

    def test_label_threshold_boundary(self):
        self.assertIsNone(self.extract(label_score=.8799).field.value)
        self.assertEqual(self.extract(label_score=.88).field.value, '2013-09-17')

    def test_birth_and_expiry_are_excluded(self):
        for context in ({'birth_date':'2013-09-17'}, {'expiry_date':'2013-09-17'}):
            with self.subTest(context=context):
                self.assertIsNone(self.extract(**context).field.value)

    def test_invalid_or_ambiguous_compact(self):
        for raw in ('32132020','29022023','01022020','170920130','1709201','ID17092013'):
            with self.subTest(raw=raw):
                self.assertIsNone(self.extract(raw).field.value)

    def test_strong_and_near_label_standard_date(self):
        self.assertEqual(self.extract('2020-01-15', label_score=.97).field.value, '2020-01-15')
        self.assertEqual(self.extract('15.01.2020').field.value, '2020-01-15')

    def test_no_label(self):
        r=extract_issue_date([OCRLine('17092013', .99, (100,120,200,140))])
        self.assertIsNone(r.field.value)

    def test_weak_geometry_or_missing_boxes(self):
        self.assertIsNone(self.extract(box=(100,150,200,170)).field.value)
        self.assertIsNone(self.extract(box=None).field.value)
        self.assertIsNone(self.extract(label_score=.99,box=(100,150,200,170)).field.value)

    def test_weak_date_ocr_does_not_use_exception(self):
        lines=[OCRLine('Issue date',.8986,(100,100,240,120)), OCRLine('17092013',.94,(100,120,200,140))]
        self.assertIsNone(extract_issue_date(lines).field.value)

    def test_localized_label_and_competing_known_expiry(self):
        lines=[OCRLine('Дата выдачи',.89,(100,100,240,120)), OCRLine('17092013',.99,(100,120,200,140)),
               OCRLine('16 09 2023',.99,(100,143,200,163))]
        r=extract_issue_date(lines, birth_date='1988-09-01', expiry_date='2023-09-16')
        self.assertEqual(r.field.value,'2013-09-17')

    def test_compact_requires_entire_date_block(self):
        self.assertIsNone(self.extract('17092013 extra text').field.value)
        self.assertEqual(self.extract(' 17092013 ').field.value, '2013-09-17')

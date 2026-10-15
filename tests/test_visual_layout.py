"""Synthetic layouts, coordinates unrelated to any real passport template."""
from datetime import date
import unittest
from app.document_engine.models import OCRLine
from app.document_engine.visual_dates import extract_issue_date

TODAY = date(2026, 9, 29)


def block(text, box, score=.97):
    return OCRLine(text, score, box)


class VisualLayoutTests(unittest.TestCase):
    def extract(self, lines, **kwargs):
        return extract_issue_date(lines, today=TODAY, **kwargs)

    def test_label_left_date_right(self):
        r = self.extract([block('Date of issue', (100,100,240,120)), block('15.01.2020', (260,100,360,120))])
        self.assertEqual(r.field.value, '2020-01-15')
        self.assertEqual(r.selected_candidate['relative_position'], 'right')
        self.assertEqual(r.selected_candidate['distance_to_label'], 1)
        self.assertEqual(r.field.source, 'visual_ocr')
        self.assertTrue(r.field.needs_confirmation)

    def test_label_above_date_with_interleaved_column(self):
        r = self.extract([block('Date issued', (100,100,240,120)), block('AUTHORITY', (400,110,530,130)), block('15/01/2020', (100,126,220,146))])
        self.assertEqual(r.field.value, '2020-01-15')
        self.assertEqual(r.selected_candidate['relative_position'], 'below')

    def test_multiple_dates_and_other_labels(self):
        r = self.extract([block('Date of birth', (100,20,240,40)), block('1990-01-15', (100,45,220,65)),
                          block('Issue date', (100,100,240,120)), block('2020-01-15', (100,125,220,145)),
                          block('Expiry date', (400,100,540,120)), block('2030-01-15', (400,125,520,145))])
        self.assertEqual(r.field.value, '2020-01-15')
        self.assertEqual(len(r.candidate_dates), 3)

    def test_known_birth_is_closer_but_not_selected(self):
        r = self.extract([block('Date of issue', (100,100,240,120)), block('1990-01-15', (241,100,340,120)),
                          block('2020-01-15', (100,128,220,148))], birth_date='1990-01-15')
        self.assertEqual(r.field.value, '2020-01-15')
        self.assertIn('matches_known_birth_or_expiry', r.candidate_dates[0]['reasons'])

    def test_known_expiry_nearby_is_not_selected(self):
        r = self.extract([block('Date of issue', (100,100,240,120)), block('2023-01-15', (241,100,340,120)),
                          block('2020-01-15', (100,128,220,148))], expiry_date='2023-01-15')
        self.assertEqual(r.field.value, '2020-01-15')

    def test_other_label_owns_date(self):
        r = self.extract([block('Issue date', (100,100,200,120)), block('Expiry date', (220,100,320,120)),
                          block('2020-01-15', (195,126,300,146))])
        self.assertIsNone(r.field.value)
        self.assertIn('closer_birth_or_expiry_label', r.candidate_dates[0]['reasons'])

    def test_equal_candidates_remain_empty(self):
        r = self.extract([block('Issue date', (100,100,300,120)), block('2020-01-15', (100,130,190,150)),
                          block('2021-01-15', (210,130,300,150))])
        self.assertIsNone(r.field.value)
        self.assertEqual(r.selection_reason, 'no_clear_spatial_winner')

    def test_no_label_and_far_label(self):
        date_line = block('2020-01-15', (100,300,220,320))
        for lines in ([date_line], [block('Issue date', (100,100,240,120)), date_line]):
            self.assertIsNone(self.extract(lines).field.value)

    def test_ocr_typo_in_label(self):
        r = self.extract([block('Date of issve', (100,100,240,120)), block('2020-01-15', (100,126,220,146))])
        self.assertEqual(r.field.value, '2020-01-15')
        self.assertEqual(r.matched_labels[0]['match_method'], 'one_character_ocr_error')
        self.assertIsNone(self.extract([block('Date of expiry', (100,100,240,120)), block('2020-01-15', (100,126,220,146))]).field.value)

    def test_formats_and_two_digit_century(self):
        for raw in ('15.01.2020','15/01/2020','2020-01-15','15 01 2020','15.01.20'):
            with self.subTest(raw=raw):
                r = self.extract([block('Дата выдачи', (100,100,240,120)), block(raw, (100,126,220,146))], birth_date='1990-01-01')
                self.assertEqual(r.field.value, '2020-01-15')
        r = self.extract([OCRLine('Date of issue: 15.01.20', .99)])
        self.assertIsNone(r.field.value)
        self.assertIn('two_digit_year_requires_birth_context', r.candidate_dates[0]['reasons'])
        self.assertIsNone(self.extract([OCRLine('Date of issue: 15.01.20', .99)], birth_date='1910-01-01').field.value)

    def test_ambiguous_day_month_and_compact_digits(self):
        for raw in ('01/02/2020', '17092013'):
            self.assertIsNone(self.extract([OCRLine('Date of issue: '+raw, .99)]).field.value)

    def test_low_confidence_candidate_is_not_ignored(self):
        r = self.extract([block('Issue date', (100,100,300,120)), block('2020-01-15', (100,130,190,150)),
                          block('2021-01-15', (210,130,300,150), .6)])
        self.assertIsNone(r.field.value)

    def test_localized_alias_is_configurable(self):
        r = self.extract([block('Fecha de emisión', (100,100,240,120)), block('2020-01-15', (100,126,220,146))], label_aliases=('fecha de emisión',))
        self.assertEqual(r.field.value, '2020-01-15')

    def test_scale_independence(self):
        original = [block('Issue date', (100,100,240,120)), block('2020-01-15', (100,126,220,146))]
        scaled = [block(line.text, tuple(v*3 for v in line.bbox)) for line in original]
        self.assertEqual(self.extract(original).selected_candidate['distance_to_label'], self.extract(scaled).selected_candidate['distance_to_label'])

    def test_invalid_boxes_do_not_invent_adjacency(self):
        for box in ((0,0,0,0),(0,0,float('nan'),10)):
            self.assertIsNone(self.extract([block('Issue date', box), block('2020-01-15', (100,126,220,146))]).field.value)

    def test_missing_score_is_not_fabricated(self):
        r = self.extract([block('Issue date', (100,100,240,120), None), block('2020-01-15', (100,126,220,146))])
        self.assertIsNone(r.field.value)
        self.assertIsNone(r.candidate_dates[0]['confidence'])

    def test_repeated_spaces_are_supported(self):
        self.assertEqual(self.extract([OCRLine('Date issued: 15   01  2020', .99)]).field.value, '2020-01-15')

    def test_mrz_digits_are_not_visual_date_candidates(self):
        r = self.extract([OCRLine('AZ00010556UZB8809014M23091653010988660001460<', .99)])
        self.assertEqual(r.candidate_dates, [])

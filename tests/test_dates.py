from datetime import date
import unittest
from app.document_engine.dates import resolve_mrz_date

TODAY = date(2026, 9, 29)


class DateResolutionTests(unittest.TestCase):
    def resolve(self, raw, kind="date_of_birth", **kwargs):
        return resolve_mrz_date(raw, kind, today=TODAY, checksum_valid=True, **kwargs)

    def test_unique_birth(self):
        result = self.resolve("000101", confidence=.91)
        self.assertEqual(result.value, "2000-01-01")
        self.assertEqual(result.confidence, .91)
        self.assertTrue(result.needs_confirmation)

    def test_ambiguous_birth(self):
        result = self.resolve("100101")
        self.assertIsNone(result.value)
        self.assertEqual(result.candidates, ["1910-01-01", "2010-01-01"])
        self.assertIn("ambiguous_century", result.reasons)

    def test_unique_expiry(self):
        result = self.resolve("300101", "expiry_date", birth_candidates=["2000-01-01"])
        self.assertEqual(result.value, "2030-01-01")
        self.assertIsNone(result.confidence)

    def test_ambiguous_expiry(self):
        result = self.resolve("300101", "expiry_date")
        self.assertIsNone(result.value)
        self.assertEqual(result.candidates, ["1930-01-01", "2030-01-01"])

    def test_invalid_and_checksum(self):
        for raw in ("000230", "ab0101", "001301", "", "000000"):
            with self.subTest(raw=raw):
                self.assertIsNone(self.resolve(raw).value)
                self.assertIn("invalid_calendar_date", self.resolve(raw).reasons)
        self.assertIsNone(resolve_mrz_date("000101", "date_of_birth", today=TODAY).value)

    def test_future_birth_never_selected(self):
        self.assertEqual(self.resolve("270101").value, "1927-01-01")
        self.assertEqual(self.resolve("000229").value, "2000-02-29")

    def test_expiry_respects_all_possible_births(self):
        result = self.resolve("300101", "expiry_date", birth_candidates=["1910-01-01", "2010-01-01"])
        self.assertIsNone(result.value)
        self.assertEqual(len(result.candidates), 2)

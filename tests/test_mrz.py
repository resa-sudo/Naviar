"""Only fictional TD3 fixtures; no real identities or passport numbers."""
from pathlib import Path
import unittest
from app.document_engine.engine import DocumentEngine
from app.document_engine.models import OCRLine, OCRResult, ProcessingContext
from app.document_engine.mrz import check_digit, parse_td3

FIRST = "P<UTO" + "SYNTHETIC<<DEMO<ONLY".ljust(39, "<")
# Fixed fixture digits are independent of parser calls at test time.
SECOND = "TEST00001" + "7" + "UTO" + "000101" + "8" + "X" + "300101" + "9" + "<" * 14 + "0" + "6"


class MRZTests(unittest.TestCase):
    def test_valid_synthetic_td3(self):
        result = parse_td3(FIRST + "\n" + SECOND)
        self.assertEqual(len(FIRST), 44)
        self.assertEqual(len(SECOND), 44)
        self.assertTrue(result.structure_consistent, result.checks)
        self.assertEqual(result.fields["surname"].value, "SYNTHETIC")
        self.assertEqual(result.fields["given_names"].value, "DEMO ONLY")
        self.assertEqual(result.fields["passport_number"].value, "TEST00001")
        self.assertEqual(result.fields["nationality"].value, "UTO")
        self.assertEqual(result.fields["issuing_country"].value, "UTO")
        self.assertEqual(result.fields["sex"].value, "X")
        self.assertIsNone(result.fields["date_of_birth"].value)
        self.assertIsNone(result.fields["expiry_date"].value)
        self.assertEqual(result.raw_dates["date_of_birth"], "000101")
        self.assertIsNone(result.fields["surname"].confidence)

    def test_wrong_checksum(self):
        result = parse_td3(FIRST + "\n" + SECOND[:9] + "0" + SECOND[10:])
        self.assertFalse(result.checks["passport_number"])
        self.assertFalse(result.checks["composite"])
        self.assertIsNone(result.fields["passport_number"].value)

    def test_normalization_and_damaged_ocr(self):
        clean = parse_td3(" ".join(FIRST.lower()) + "\n" + " ".join(SECOND))
        self.assertTrue(clean.structure_consistent)
        damaged = parse_td3(FIRST + "\n" + SECOND[:14] + "?" + SECOND[15:])
        self.assertFalse(damaged.checks["date_of_birth"])
        self.assertIsNone(damaged.fields["date_of_birth"].value)
        self.assertEqual(damaged.fields["passport_number"].value, "TEST00001")

    def test_missing_second_line(self):
        result = parse_td3(FIRST)
        self.assertTrue(result.found)
        self.assertFalse(result.structure_consistent)
        self.assertEqual(result.fields["surname"].value, "SYNTHETIC")
        self.assertIsNone(result.fields["passport_number"].value)

    def test_unknown_and_ambiguous_document(self):
        self.assertFalse(parse_td3("NOT A PASSPORT\nSYNTHETIC TEST").found)
        result = parse_td3(FIRST + "\n" + SECOND + "\n" + FIRST + "\n" + SECOND)
        self.assertFalse(result.found)
        self.assertIn("multiple_td3_candidates", result.errors)

    def test_partial_provider_and_confidence(self):
        class FixtureProvider:
            def extract(self, path, context):
                return OCRResult([OCRLine(FIRST, 0.81)])
        result = DocumentEngine(FixtureProvider()).process(Path("synthetic.png"), ProcessingContext("passport", "RU", "UTO"))
        self.assertEqual(result.status, "unsupported_or_not_passport")
        self.assertIsNone(result.mrz.fields["surname"].value)
        self.assertIsNone(result.mrz.fields["passport_number"].confidence)

    def test_provider_failure_is_sanitized(self):
        class BrokenProvider:
            def extract(self, path, context):
                raise RuntimeError("PRIVATE OCR TEXT AND PATH")
        result = DocumentEngine(BrokenProvider()).process(Path("synthetic.png"), ProcessingContext("passport"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.errors, ["ocr_provider_error"])

    def test_unknown_type_does_not_call_provider(self):
        class UnusedProvider:
            def extract(self, path, context):
                raise AssertionError("must not be called")
        result = DocumentEngine(UnusedProvider()).process(Path("test.png"), ProcessingContext("visa"))
        self.assertEqual(result.errors, ["unsupported_document_type"])

    def test_checksum_values_and_context(self):
        self.assertEqual(check_digit("<"), "0")
        self.assertEqual(check_digit("ABC"), "5")
        with self.assertRaises(ValueError):
            check_digit("?")
        with self.assertRaises(ValueError):
            ProcessingContext("passport", "Russia")


if __name__ == "__main__":
    unittest.main()

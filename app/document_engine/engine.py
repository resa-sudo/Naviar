"""Passport processing with an injected local OCR provider."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
from time import perf_counter
from .models import ExtractedField, MRZResult, OCRProvider, ProcessingContext, ProcessingResult
from .mrz import normalize_line, parse_td3
from .dates import resolve_mrz_date
from .detection import detect_td3
from .visual_dates import extract_issue_date


class DocumentEngine:
    def __init__(self, provider: OCRProvider):
        self.provider = provider

    def process(self, path: Path, context: ProcessingContext, *, today: date | None = None) -> ProcessingResult:
        started = perf_counter()
        today = today or date.today()
        if context.document_type != "passport":
            return ProcessingResult(context, "failed", MRZResult(), 0, ["unsupported_document_type"])
        try:
            output = self.provider.extract(path, context)
        except Exception:
            return ProcessingResult(context, "failed", MRZResult(), round(perf_counter() - started, 3), ["ocr_provider_error"])
        mrz = parse_td3(output.lines)
        detection = detect_td3(output.lines, mrz)
        result = ProcessingResult(context, "failed", mrz, 0, list(output.errors), detection=asdict(detection))
        if not detection.supported:
            # Keep parser evidence in the dev result but never prefill from an
            # unsupported/partial document. Provider failure is not classification.
            mrz.fields = MRZResult().fields
            result.status = "failed" if output.errors and not output.lines else "unsupported_or_not_passport"
            result.errors += mrz.errors + detection.reasons
        else:
            second = mrz.lines[1]
            scores = [line.confidence for line in output.lines for part in line.text.splitlines()
                      if normalize_line(part) == second]
            score = scores[0] if len(scores) == 1 else None
            birth = resolve_mrz_date(mrz.raw_dates.get("date_of_birth", ""), "date_of_birth",
                                     today=today, checksum_valid=mrz.checks.get("date_of_birth") is True, confidence=score)
            expiry = resolve_mrz_date(mrz.raw_dates.get("expiry_date", ""), "expiry_date", today=today,
                                      checksum_valid=mrz.checks.get("expiry_date") is True,
                                      confidence=score, birth_candidates=birth.candidates)
            for name, resolution in (("date_of_birth", birth), ("expiry_date", expiry)):
                result.date_resolution[name] = asdict(resolution)
                mrz.fields[name] = ExtractedField(resolution.value, resolution.confidence,
                                                   "mrz" if resolution.value else "unresolved")
                mrz.errors = [e for e in mrz.errors if e != name + "_century_requires_confirmation"]
                result.errors.extend(name + ":" + reason for reason in resolution.reasons)
            visual = extract_issue_date(output.lines, today=today, birth_date=birth.value, expiry_date=expiry.value)
            mrz.fields["date_of_issue"] = visual.field
            result.visual_date_candidates = visual.candidate_dates
            result.visual_date_debug = {"matched_labels": visual.matched_labels,
                                        "selected_candidate": visual.selected_candidate,
                                        "selection_reason": visual.selection_reason}
            result.errors += mrz.errors + visual.reasons
            result.status = "success" if all(f.value is not None for f in mrz.fields.values()) and mrz.structure_consistent else "partial"
        result.processing_seconds = round(perf_counter() - started, 3)
        return result

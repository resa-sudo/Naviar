"""Evidence of a supported TD3 layout, never an authenticity decision."""
from dataclasses import dataclass, field
import re
from .models import MRZResult, OCRLine
from .mrz import normalize_line


@dataclass
class DocumentDetection:
    detected_document_type: str = "unsupported_or_not_passport"
    supported: bool = False
    reasons: list[str] = field(default_factory=list)


def detect_td3(lines: list[OCRLine], mrz: MRZResult) -> DocumentDetection:
    result = DocumentDetection()
    normalized = [normalize_line(part) for line in lines for part in line.text.splitlines() if part.strip()]
    near = any(42 <= len(line) <= 46 and line.startswith("P") and "<<" in line for line in normalized)
    if len(mrz.lines) != 2:
        result.reasons = ["partial_or_damaged_td3" if near else "td3_pair_not_found"]
        return result
    second = mrz.lines[1]
    # Allow a nationality OCR typo (e.g. UT0) for classification only. The
    # stricter parser still leaves the affected nationality field unresolved.
    shape = bool(re.fullmatch(r"[A-Z0-9<]{9}[0-9][A-Z0-9<]{3}[0-9]{6}[0-9][MFX<][0-9]{6}[0-9][A-Z0-9<]{14}[0-9<][0-9]", second))
    valid_checks = sum(mrz.checks.get(key) is True for key in ("passport_number", "date_of_birth", "expiry_date"))
    if not shape or valid_checks == 0:
        result.reasons = ["td3_structure_or_checks_insufficient"]
        return result
    result.supported = True
    result.detected_document_type = "td3_passport"
    result.reasons = ["two_td3_lines_with_partial_checksum_evidence"]
    if not mrz.structure_consistent:
        result.reasons.append("mrz_contains_unresolved_structure_or_checks")
    return result

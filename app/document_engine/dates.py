"""Conservative century resolution. Windows are extraction heuristics, not law."""
from dataclasses import dataclass, field
from datetime import date
from calendar import monthrange
import re


@dataclass
class DateResolution:
    value: str | None = None
    confidence: float | None = None
    resolution_method: str = "unresolved"
    needs_confirmation: bool = True
    candidates: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def calendar_candidates(raw: str, first_year: int, last_year: int) -> list[date]:
    if not re.fullmatch(r"[0-9]{6}", raw):
        return []
    result = []
    for year in range(first_year, last_year + 1):
        if year % 100 != int(raw[:2]):
            continue
        try:
            result.append(date(year, int(raw[2:4]), int(raw[4:])))
        except ValueError:
            pass
    return result


def resolve_mrz_date(raw: str, kind: str, *, today: date | None = None,
                     checksum_valid: bool = False, confidence: float | None = None,
                     birth_candidates: list[str] | None = None) -> DateResolution:
    """DOB: age 0..125. Expiry: past 100/future 20 years, after possible DOB.

    Wide explicit windows deliberately allow unresolved old documents. Scores
    are inherited OCR evidence, never a probability that the century is correct.
    Even a unique candidate must be confirmed by the user.
    """
    today = today or date.today()
    result = DateResolution()
    if kind not in {"date_of_birth", "expiry_date"}:
        raise ValueError("unsupported_date_kind")
    if not checksum_valid:
        result.reasons = ["mrz_date_checksum_missing_or_failed"]
        return result
    if not re.fullmatch(r"[0-9]{6}", raw) or not calendar_candidates(raw, 1800, 2199):
        result.reasons = ["invalid_calendar_date"]
        return result
    if kind == "date_of_birth":
        candidates = calendar_candidates(raw, max(1, today.year - 126), today.year)
        candidates = [d for d in candidates if d <= today and
                      today.year - d.year - ((today.month, today.day) < (d.month, d.day)) <= 125]
        method = "checksum_calendar_age_0_to_125"
    else:
        earliest = date(max(1, today.year - 100), today.month, min(today.day, monthrange(max(1, today.year - 100), today.month)[1]))
        latest = date(min(9999, today.year + 20), today.month, min(today.day, monthrange(min(9999, today.year + 20), today.month)[1]))
        candidates = [d for d in calendar_candidates(raw, earliest.year, latest.year) if earliest <= d <= latest]
        births = [date.fromisoformat(value) for value in (birth_candidates or [])]
        if births:
            candidates = [d for d in candidates if any(d > birth for birth in births)]
        method = "checksum_calendar_today_minus_100_plus_20_after_possible_birth"
        if not births:
            result.reasons.append("birth_context_unavailable")
    result.candidates = [d.isoformat() for d in candidates]
    if len(candidates) == 1:
        result.value = result.candidates[0]
        result.resolution_method = method
        result.confidence = confidence if confidence is not None and 0 <= confidence <= 1 else None
    else:
        result.reasons.append("ambiguous_century" if candidates else "no_candidate_within_heuristic_bounds")
    return result

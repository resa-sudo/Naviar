"""Engine contracts: no FastAPI, university or OCR-library dependency."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
import re

FIELD_NAMES = ("surname", "given_names", "nationality", "passport_number",
               "date_of_birth", "sex", "expiry_date", "issuing_country", "date_of_issue")


@dataclass(frozen=True)
class ProcessingContext:
    document_type: str
    country_of_study: str | None = None
    issuing_country: str | None = None

    def __post_init__(self):
        for value, length in ((self.country_of_study, 2), (self.issuing_country, 3)):
            if value is not None and not re.fullmatch(f"[A-Z]{{{length}}}", value):
                raise ValueError("invalid_country_code")


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float | None = None
    # Axis-aligned (left, top, right, bottom) in original-image pixels.
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class OCRResult:
    lines: list[OCRLine]
    errors: list[str] = field(default_factory=list)


class OCRProvider(Protocol):
    def extract(self, path: Path, context: ProcessingContext) -> OCRResult: ...


@dataclass
class ExtractedField:
    value: str | None = None
    confidence: float | None = None
    source: str = "unresolved"
    needs_confirmation: bool = True


@dataclass
class MRZResult:
    found: bool = False
    lines: list[str] = field(default_factory=list)
    fields: dict[str, ExtractedField] = field(default_factory=lambda: {key: ExtractedField() for key in FIELD_NAMES})
    checks: dict[str, bool | None] = field(default_factory=dict)
    raw_dates: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def structure_consistent(self):
        return bool(self.checks) and all(value is True for value in self.checks.values())


@dataclass
class ProcessingResult:
    context: ProcessingContext
    status: Literal["success", "partial", "failed", "unsupported_or_not_passport"]
    mrz: MRZResult
    processing_seconds: float
    errors: list[str] = field(default_factory=list)

    detection: dict = field(default_factory=dict)
    date_resolution: dict = field(default_factory=dict)
    visual_date_candidates: list[dict] = field(default_factory=list)

    visual_date_debug: dict = field(default_factory=dict)

"""Explainable issue-date association. Geometry is normalized by text height.

No passport templates or country coordinates. Candidate diagnostics stay in
Document Lab/storage, never the production UI response. Scores are OCR evidence,
not calibrated probabilities of field correctness.
"""
from dataclasses import dataclass, field as dataclass_field
from datetime import date
from math import hypot, isfinite
import re
import unicodedata
from .models import ExtractedField, OCRLine

# Extend this vocabulary for another language; no layout/template change needed.
ISSUE_LABELS = ("date of issue", "issue date", "date issued", "issued on", "дата выдачи",
                "date d'émission", "fecha de expedición")
OTHER_LABEL = re.compile(r"birth|expiry|expiration|valid\s+until|рожд|оконч|действител", re.I)
DATE_PATTERN = re.compile(r"(?<!\d)(?:\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}(?:[-/.]|[ \t]+)\d{2}(?:[-/.]|[ \t]+)(?:\d{4}|\d{2})|\d{8})(?!\d)")


@dataclass
class VisualDateResult:
    field: ExtractedField = dataclass_field(default_factory=ExtractedField)
    candidate_dates: list[dict] = dataclass_field(default_factory=list)
    reasons: list[str] = dataclass_field(default_factory=list)
    matched_labels: list[dict] = dataclass_field(default_factory=list)
    selected_candidate: dict | None = None
    selection_reason: str = "no_reliable_candidate"


def words(text):
    return re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", text).casefold(), re.UNICODE)


def one_edit_apart(left, right):
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    short, long = sorted((left, right), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def match_label(text, aliases):
    tokens = words(DATE_PATTERN.sub("", text))
    fuzzy = None
    for alias in aliases:
        expected = "".join(words(alias))
        for size in range(1, len(words(alias)) + 1):
            for offset in range(len(tokens) - size + 1):
                candidate = "".join(tokens[offset:offset + size])
                if candidate == expected:
                    return {"matched_label": alias, "match_method": "exact"}
                if len(expected) >= 7 and one_edit_apart(candidate, expected):
                    fuzzy = {"matched_label": alias, "match_method": "one_character_ocr_error"}
    return fuzzy


def valid_box(box):
    return (box is not None and len(box) == 4 and all(isinstance(v, (int, float)) and isfinite(v) for v in box)
            and box[2] > box[0] and box[3] > box[1])


def spatial_relation(label_box, date_box):
    if not valid_box(label_box) or not valid_box(date_box):
        return None
    lx, ly, lr, lb = label_box
    dx, dy, dr, db = date_box
    height = max(lb - ly, db - dy)
    center_offset = abs((ly + lb - dy - db) / 2)
    if dx >= lr - .2 * height and center_offset <= .75 * height and dx - lr <= 12 * height:
        return "right", hypot(max(0, dx - lr), center_offset) / height
    overlap = min(lr, dr) - max(lx, dx)
    horizontal_gap = max(0, -overlap)
    if dy >= lb - .2 * height and dy - lb <= 3 * height and (overlap > 0 or abs(dx - lx) <= 2 * height):
        return "below", hypot(max(0, dy - lb), horizontal_gap) / height
    return None


def date_options(raw: str, *, today=None, birth_date=None, expiry_date=None):
    """Return possible ISO dates; never silently pick DD/MM over MM/DD.

    Two-digit years require a known DOB. Enumerate years from DOB to today,
    constrained by expiry; use a century only when exactly one date survives.
    Compact DDMMYYYY requires eight digits and an unambiguous calendar date.
    """
    today = today or date.today()
    compact = bool(re.fullmatch(r"[0-9]{8}", raw))
    parts = [raw[:2], raw[2:4], raw[4:]] if compact else re.split(r"[-/.]|[ \t]+", raw)
    if len(parts) != 3:
        return [], "missing_date_separators"
    if len(parts[0]) == 4:
        orders = [(int(parts[1]), int(parts[2]))]
        years = [int(parts[0])]
        method = "compact_ddmmyyyy" if compact else "four_digit_year"
    else:
        orders = [(int(parts[1]), int(parts[0])), (int(parts[0]), int(parts[1]))]
        if len(parts[2]) == 2:
            if not birth_date:
                return [], "two_digit_year_requires_birth_context"
            years = [year for year in range(date.fromisoformat(birth_date).year, today.year + 1)
                     if year % 100 == int(parts[2])]
            method = "two_digit_year_between_known_birth_and_today_before_expiry"
        else:
            years = [int(parts[2])]
            method = "compact_ddmmyyyy" if compact else "four_digit_year"
    values = set()
    for year in years:
        for month, day in orders:
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            if not 1800 <= year <= 2199:
                continue
            if len(parts[2]) == 2 and len(parts[0]) != 4:
                if candidate > today or candidate.isoformat() < birth_date or (expiry_date and candidate.isoformat() >= expiry_date):
                    continue
            values.add(candidate.isoformat())
    return sorted(values), method


def extract_issue_date(lines: list[OCRLine], *, today: date | None = None,
                       birth_date: str | None = None, expiry_date: str | None = None,
                       label_aliases=ISSUE_LABELS) -> VisualDateResult:
    today = today or date.today()
    result = VisualDateResult()
    # A multiline provider block has no per-line geometry: never invent boxes.
    blocks = []
    for line in lines:
        parts = [part for part in line.text.splitlines() if part.strip()]
        blocks.extend(OCRLine(part, line.confidence, line.bbox if len(parts) == 1 else None) for part in parts)
    for index, block in enumerate(blocks):
        match = match_label(block.text, label_aliases)
        if match:
            result.matched_labels.append({**match, "line_index": index, "raw_text": block.text,
                                          "bbox": block.bbox, "ocr_confidence": block.confidence})
    other_labels = [i for i, block in enumerate(blocks) if OTHER_LABEL.search(block.text)]
    for index, block in enumerate(blocks):
        # MRZ numbers are not visual-zone dates.
        if "<" in block.text and len(re.sub(r"\s+", "", block.text)) >= 40:
            continue
        matches = list(DATE_PATTERN.finditer(block.text))
        for match in matches:
            values, method = date_options(match.group(), today=today, birth_date=birth_date, expiry_date=expiry_date)
            links = []
            for label in result.matched_labels:
                li = label["line_index"]
                relation = ("same_block", 0.0) if li == index else spatial_relation(blocks[li].bbox, block.bbox)
                # Retain old text-only-provider support only for adjacent label-only
                # and date-only lines when neither has coordinates.
                if relation is None and li == index - 1 and blocks[li].bbox is None and block.bbox is None:
                    if DATE_PATTERN.fullmatch(block.text.strip()) and "".join(words(blocks[li].text)) == "".join(words(label["matched_label"])):
                        relation = ("adjacent_text_only", 0.0)
                if relation:
                    position, distance = relation
                    cost = distance + (.2 if position == "below" else 0) + (.4 if label["match_method"] != "exact" else 0)
                    links.append((cost, label, position, distance))
            links.sort(key=lambda link: link[0])
            best = links[0] if links else None
            reasons = []
            if method == "compact_ddmmyyyy" and (not best or best[2] not in {"right", "below"} or best[3] > 1):
                reasons.append("compact_requires_close_spatial_relation")
            if method == "compact_ddmmyyyy" and block.text.strip() != match.group():
                reasons.append("compact_requires_standalone_date_block")
            if len(values) != 1:
                reasons.append("ambiguous_date_or_century" if values else method if method in {"missing_date_separators", "two_digit_year_requires_birth_context"} else "invalid_calendar_date_or_context")
            value = values[0] if len(values) == 1 else None
            label = best[1] if best else None
            scores = [block.confidence, label["ocr_confidence"] if label else None]
            confidence = min(scores) if all(s is not None and 0 <= s <= 1 for s in scores) else None
            if not best:
                reasons.append("no_spatial_issue_label")
            if confidence is None or confidence < .90:
                reasons.append("missing_or_low_provider_score")
            if len(links) > 1 and links[1][0] - links[0][0] < .75 and links[1][1]["line_index"] != links[0][1]["line_index"]:
                reasons.append("competing_issue_labels")
            if len(matches) > 1 or OTHER_LABEL.search(block.text) or (label and OTHER_LABEL.search(label["raw_text"])):
                reasons.append("conflicting_date_context")
            if birth_date in values or expiry_date in values:
                reasons.append("matches_known_birth_or_expiry")
            if value and (value > today.isoformat() or (birth_date and value < birth_date) or (expiry_date and value >= expiry_date)):
                reasons.append("issue_date_conflicts_with_date_context")
            if best:
                for other in other_labels:
                    relation = ("same_block", 0) if other == index else spatial_relation(blocks[other].bbox, block.bbox)
                    if relation and relation[1] <= best[3] + .5:
                        reasons.append("closer_birth_or_expiry_label")
                        break
            result.candidate_dates.append({"raw_text": match.group(), "normalized_date": value,
                "possible_dates": values, "normalization_method": method, "line_index": index,
                "bbox": block.bbox, "distance_to_label": round(best[3], 3) if best else None,
                "relative_position": best[2] if best else "unrelated", "ocr_confidence": block.confidence,
                "confidence": confidence, "matched_label": label["matched_label"] if label else None,
                "label_line_index": label["line_index"] if label else None,
                "label_confidence": label["ocr_confidence"] if label else None,
                "label_match_method": label["match_method"] if label else None,
                "association_cost": round(best[0], 3) if best else None, "reasons": list(dict.fromkeys(reasons))})
    # A narrow exception, not a lower global threshold. Require actual close
    # geometry, strong date OCR and no plausible nearby competing date.
    excluded_conflicts = {"matches_known_birth_or_expiry", "issue_date_conflicts_with_date_context",
                          "closer_birth_or_expiry_label", "conflicting_date_context"}
    for candidate in result.candidate_dates:
        if candidate["reasons"] != ["missing_or_low_provider_score"]:
            continue
        if candidate["label_confidence"] is None or candidate["ocr_confidence"] is None:
            continue
        if not (.88 <= candidate["label_confidence"] < .90 and candidate["ocr_confidence"] >= .95):
            continue
        if candidate["relative_position"] not in {"right", "below"} or candidate["distance_to_label"] > 1:
            continue
        rivals = [other for other in result.candidate_dates if other is not candidate
                  and other["association_cost"] is not None
                  and not excluded_conflicts.intersection(other["reasons"])
                  and (other["distance_to_label"] <= 1.5 or
                       other["association_cost"] - candidate["association_cost"] < .75)]
        if rivals:
            candidate["reasons"].append("near_threshold_competing_candidate")
            continue
        spatial_score = 1 / (1 + .1 * candidate["distance_to_label"])
        label_match_penalty = .95 if candidate["label_match_method"] != "exact" else 1.0
        # Ambiguity has a hard veto above; only a unique association reaches here.
        ambiguity_penalty = 1.0
        candidate["confidence_basis"] = {
            "rule": "near_threshold_unique_issue_date", "label_ocr": candidate["label_confidence"],
            "candidate_ocr": candidate["ocr_confidence"], "spatial_score": spatial_score,
            "label_match_penalty": label_match_penalty, "ambiguity_penalty": ambiguity_penalty,
            "formula": "min(label_ocr,candidate_ocr)*spatial_score*label_match_penalty*ambiguity_penalty",
        }
        candidate["confidence"] = min(candidate["label_confidence"], candidate["ocr_confidence"]) * spatial_score * label_match_penalty * ambiguity_penalty
        candidate["reasons"] = []
    eligible = sorted((c for c in result.candidate_dates if not c["reasons"]), key=lambda c: c["association_cost"])
    if eligible:
        best = eligible[0]
        # Do not ignore a nearby low-score/ambiguous competitor merely because it
        # cannot be normalized. Explicit DOB/expiry conflicts are excluded.
        rivals = [c for c in result.candidate_dates if c is not best and c["association_cost"] is not None
                  and not any(r in c["reasons"] for r in ("matches_known_birth_or_expiry", "issue_date_conflicts_with_date_context", "closer_birth_or_expiry_label", "conflicting_date_context"))]
        ambiguous = any(c["association_cost"] - best["association_cost"] < .75 for c in rivals)
        if not ambiguous:
            result.selected_candidate = best
            result.selection_reason = "near_threshold_unique_issue_date" if best.get("confidence_basis") else "unique_clear_label_association"
            result.field = ExtractedField(best["normalized_date"], best["confidence"], "visual_ocr")
        else:
            result.selection_reason = "no_clear_spatial_winner"
    if result.field.value is None:
        result.reasons = [result.selection_reason if result.candidate_dates else "issue_date_not_found"]
    return result

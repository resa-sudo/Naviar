"""Conservative TD3 parser. Checks structure, never passport authenticity.

Reference: ICAO Doc 9303 Parts 3/4. No guessing missing characters or centuries.
"""
from datetime import date
import re
import unicodedata
from .models import ExtractedField, MRZResult, OCRLine

WEIGHTS = (7, 3, 1)


def check_digit(value: str) -> str:
    total = 0
    for index, character in enumerate(value):
        if character == "<":
            number = 0
        elif "0" <= character <= "9":
            number = ord(character) - ord("0")
        elif "A" <= character <= "Z":
            number = ord(character) - ord("A") + 10
        else:
            raise ValueError("invalid_mrz_character")
        total += number * WEIGHTS[index % 3]
    return str(total % 10)


def normalize_line(text: str) -> str:
    # Do not strip unknown characters or invent filler characters.
    text = unicodedata.normalize("NFKC", text).upper()
    text = text.replace("‹", "<").replace("«", "<<")
    return re.sub(r"\s+", "", text)


def checksum(value: str, expected: str) -> bool:
    try:
        return check_digit(value) == expected
    except ValueError:
        return False


def parse_td3(lines: list[OCRLine] | str) -> MRZResult:
    if isinstance(lines, str):
        lines = [OCRLine(line) for line in lines.splitlines()]
    normalized = []
    for line in lines:
        # Providers may return one block with several physical lines.
        normalized.extend((normalize_line(part), line.confidence) for part in line.text.splitlines() if part.strip())
    result = MRZResult()
    candidates = [(index, line, confidence) for index, (line, confidence) in enumerate(normalized)
                  if len(line) == 44 and re.fullmatch(r"P[A-Z<][A-Z<]{42}", line)]
    if not candidates:
        result.errors.append("td3_not_found")
        return result
    if len(candidates) > 1:
        result.errors.append("multiple_td3_candidates")
        return result
    index, first, first_confidence = candidates[0]
    result.found = True
    result.lines = [first]
    result.checks["line1_structure"] = True

    def put(name, value, confidence):
        if not value:
            return
        # This is the provider's line recognition score, not a calibrated
        # probability of field correctness. No provider score means null.
        if confidence is not None and not 0 <= confidence <= 1:
            confidence = None
        result.fields[name] = ExtractedField(value, confidence, "mrz")

    issuer = first[2:5]
    if re.fullmatch(r"[A-Z]{3}", issuer):
        put("issuing_country", issuer, first_confidence)
    names = first[5:].split("<<", 1)
    put("surname", " ".join(filter(None, names[0].split("<"))), first_confidence)
    if len(names) == 2:
        put("given_names", " ".join(filter(None, names[1].split("<"))), first_confidence)

    second_entry = normalized[index + 1] if index + 1 < len(normalized) else None
    if second_entry is None or len(second_entry[0]) != 44:
        result.checks["line2_structure"] = False
        result.errors.append("second_line_missing_or_wrong_length")
        return result
    second, confidence = second_entry
    result.lines.append(second)
    result.checks["line2_structure"] = bool(re.fullmatch(r"[A-Z0-9<]{9}[0-9<][A-Z<]{3}[0-9<]{6}[0-9<][MFX<][0-9<]{6}[0-9<][A-Z0-9<]{14}[0-9<][0-9]", second))
    result.checks["passport_number"] = checksum(second[:9], second[9])
    result.checks["date_of_birth"] = checksum(second[13:19], second[19])
    result.checks["expiry_date"] = checksum(second[21:27], second[27])
    optional = second[28:42]
    result.checks["optional_data"] = (
        second[42] in "0<" if optional == "<" * 14
        else checksum(optional, second[42])
    )
    result.checks["composite"] = checksum(second[:10] + second[13:20] + second[21:43], second[43])

    if result.checks["passport_number"] and re.fullmatch(r"[A-Z0-9]+<*", second[:9]):
        put("passport_number", second[:9].rstrip("<"), confidence)
    if re.fullmatch(r"[A-Z]{3}", second[10:13]):
        put("nationality", second[10:13], confidence)
    if second[20] in {"M", "F", "X"}:
        put("sex", second[20], confidence)

    for name, raw in (("date_of_birth", second[13:19]), ("expiry_date", second[21:27])):
        result.raw_dates[name] = raw
        if not result.checks[name] or not re.fullmatch(r"\d{6}", raw):
            result.errors.append(name + "_unreadable")
            continue
        try:
            # 2000 is used only to check month/day, not to assign a century.
            date(2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:6]))
        except ValueError:
            result.checks[name + "_calendar"] = False
            result.errors.append(name + "_invalid_calendar_date")
            continue
        result.checks[name + "_calendar"] = True
        # YYMMDD cannot prove a century. Preserve evidence, leave ISO field null.
        result.errors.append(name + "_century_requires_confirmation")
    if any(value is False for value in result.checks.values()):
        result.errors.append("mrz_structure_or_checksum_failed")
    return result

"""Development only. Input is restricted to synthetic/specimen fixtures."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from app.document_engine.engine import DocumentEngine
from app.document_engine.models import ProcessingContext
from app.document_engine.visual_dates import extract_issue_date
from app.document_engine.paddle_provider import PaddleOCRProvider

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / ".document-lab" / "fixtures"
FIRST = "P<UTO" + "SYNTHETIC<<DEMO<ONLY".ljust(39, "<")
SECOND = "TEST000017UTO0001018X3001019" + "<" * 14 + "06"


def generate(with_issue_date=False, with_layout=False):
    from PIL import Image, ImageDraw, ImageFont
    FIXTURES.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1700, 560) if with_layout else (1700, 380), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 44)
    small = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 24)
    draw.text((60, 35), "SYNTHETIC TEST ONLY - NOT A DOCUMENT", fill="black", font=small)
    if with_layout:
        draw.text((60, 100), "Date of issue", fill="black", font=small)
        draw.text((700, 120), "AUTHORITY", fill="black", font=small)
        draw.text((60, 145), "15.01.2020", fill="black", font=small)
    elif with_issue_date:
        draw.text((60, 75), "Date of issue: 2020-01-15", fill="black", font=small)
    draw.text((60, 300 if with_layout else 130), FIRST, fill="black", font=font)
    draw.text((60, 390 if with_layout else 220), SECOND, fill="black", font=font)
    path = FIXTURES / ("synthetic-td3-layout.png" if with_layout else "synthetic-td3-issue.png" if with_issue_date else "synthetic-td3.png")
    image.save(path)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?")
    fixture_type = parser.add_mutually_exclusive_group(required=True)
    fixture_type.add_argument("--synthetic", action="store_true")
    fixture_type.add_argument("--specimen", action="store_true", help="Only a visibly marked public specimen fixture, never a real passport.")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--issue-date-sample", action="store_true", help="Generate a labelled synthetic issue-date example.")
    parser.add_argument("--layout-sample", action="store_true", help="Generate separated label/date blocks and an unrelated column.")
    parser.add_argument("--document-type", choices=["passport","visa"], default="passport")
    arguments = parser.parse_args()
    if arguments.generate and not arguments.synthetic:
        parser.error("Generated fixtures require --synthetic")
    if arguments.document_type=="visa":
        from scripts.visa_fixture import generate as generate_visa
        path=generate_visa() if arguments.generate else Path(arguments.image or "")
    else:
        path = generate(arguments.issue_date_sample, arguments.layout_sample) if arguments.generate else Path(arguments.image or "")
    path = path.resolve()
    if not path.is_relative_to(FIXTURES.resolve()) or not path.is_file():
        parser.error("Use only a synthetic/specimen image inside .document-lab/fixtures/")
    if arguments.document_type=="visa":
        from app.visa_engine.engine import VisaEngine
        report=VisaEngine(PaddleOCRProvider(),prepare_images=True).process(path)
        report["field_sources"]={key:value["source"] for key,value in report["extracted_fields"].items()}
        report["confidence"]={key:value["confidence"] for key,value in report["extracted_fields"].items()}
        report["notice"]="SYNTHETIC/SPECIMEN ONLY. Not an authenticity decision."
        (ROOT/".document-lab"/(path.stem+"-result.json")).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return
    context = ProcessingContext("passport", "RU")
    started = perf_counter()
    output = PaddleOCRProvider().extract(path, context)

    class CapturedProvider:
        def extract(self, path, context):
            return output

    result = DocumentEngine(CapturedProvider()).process(path, context)
    report = asdict(result)
    # Inspect the visual subprocessor even when damaged MRZ prevents passport
    # autofill. This dev diagnostic never bypasses the production TD3 gate.
    visual_started = perf_counter()
    visual = extract_issue_date(output.lines,
                                birth_date=result.mrz.fields["date_of_birth"].value,
                                expiry_date=result.mrz.fields["expiry_date"].value)
    report["issue_date_analysis"] = asdict(visual)
    report["issue_date_analysis"]["processing_seconds"] = round(perf_counter() - visual_started, 6)
    report["issue_date_analysis"]["diagnostic_only"] = True
    report["detected_document_type"] = result.detection.get("detected_document_type")
    report["mrz_found"] = result.mrz.found
    report["mrz_checksum_summary"] = result.mrz.checks
    report["ocr_blocks"] = [asdict(line) for line in output.lines]
    report["ocr_text"] = "\n".join(line.text for line in output.lines)
    report["processing_seconds"] = round(perf_counter() - started, 3)
    report["mrz_structure_consistent"] = result.mrz.structure_consistent
    report["notice"] = "DEV FIXTURE ONLY. No authenticity or legal validity decision."
    print(json.dumps(report, ensure_ascii=False, indent=2))
    (ROOT / ".document-lab" / (path.stem + "-result.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

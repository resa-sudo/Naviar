"""Optional local PaddleOCR adapter; importing this file never imports Paddle."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from .models import OCRLine, OCRResult, ProcessingContext

ROOT = Path(__file__).resolve().parents[2]
LAB_DIRECTORY = ROOT / ".document-lab"


class PaddleOCRProvider:
    def extract(self, path: Path, context: ProcessingContext) -> OCRResult:
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            return OCRResult([], ["ocr_images_only"])
        models = LAB_DIRECTORY / "models"
        if not all((models / name / "inference.yml").is_file() for name in
                   ("PP-OCRv5_mobile_det", "en_PP-OCRv5_mobile_rec")):
            return OCRResult([], ["ocr_models_missing"])
        work = LAB_DIRECTORY / "work"
        work.mkdir(parents=True, exist_ok=True)
        # Inference is isolated so native OCR output cannot enter server logs.
        with tempfile.TemporaryDirectory(dir=work) as directory:
            output = Path(directory) / "result.json"
            try:
                process = subprocess.run(
                    [sys.executable, "-m", "app.document_engine.paddle_worker", str(path.resolve()), str(output)],
                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=120, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if process.returncode != 0 or not output.is_file():
                    return OCRResult([], ["local_ocr_failed"])
                result = json.loads(output.read_text(encoding="utf-8"))
                return OCRResult([OCRLine(**item) for item in result["lines"]], result["errors"])
            except subprocess.TimeoutExpired:
                return OCRResult([], ["ocr_timeout"])

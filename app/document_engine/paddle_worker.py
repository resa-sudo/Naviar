"""Private offline inference process. No document text is printed."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / ".document-lab"
os.environ.update({
    "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
    "DISABLE_MODEL_SOURCE_CHECK": "True",
    "HF_HUB_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "PADDLE_PDX_CACHE_HOME": str(LAB / "cache"),
    "GLOG_minloglevel": "3",
})


def deny_network(event, args):
    # Applies only to this dedicated process, not to FastAPI's local socket.
    if event in {"socket.connect", "socket.connect_ex", "socket.sendto", "socket.getaddrinfo"}:
        raise RuntimeError("network_disabled_for_local_ocr")


def recognize(path: Path):
    sys.addaudithook(deny_network)
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(path) as image:
        if image.width * image.height > Image.MAX_IMAGE_PIXELS:
            return {"lines": [], "errors": ["image_dimensions_too_large"]}
        image.verify()
    from paddleocr import PaddleOCR
    pipeline = PaddleOCR(
        device="cpu",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_detection_model_dir=str(LAB / "models" / "PP-OCRv5_mobile_det"),
        text_recognition_model_name="en_PP-OCRv5_mobile_rec",
        text_recognition_model_dir=str(LAB / "models" / "en_PP-OCRv5_mobile_rec"),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        cpu_threads=4,
        enable_mkldnn=False,
    )
    lines = []
    for page in pipeline.predict(str(path), text_det_limit_side_len=1800, text_det_limit_type="max"):
        texts = page["rec_texts"]
        scores = page["rec_scores"]
        boxes = page["rec_boxes"]
        ordered = sorted(zip(texts, scores, boxes), key=lambda item: (float(item[2][1]), float(item[2][0])))
        for text, score, box in ordered:
            lines.append({"text": str(text), "confidence": float(score), "bbox": [float(value) for value in box]})
    return {"lines": lines, "errors": []}


if __name__ == "__main__":
    destination = Path(sys.argv[2])
    try:
        result = recognize(Path(sys.argv[1]))
    except Exception:
        result = {"lines": [], "errors": ["local_ocr_failed"]}
    destination.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

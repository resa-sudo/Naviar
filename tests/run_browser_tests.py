"""Optional isolated Chrome smoke test: python tests/run_browser_tests.py.
Requires the existing local Node.js and Chrome installations; no test packages.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def wait_for(url):
    for _ in range(100):
        try:
            with urlopen(url, timeout=.3) as response:
                return json.load(response)
        except OSError:
            time.sleep(.1)
    raise RuntimeError("Test process did not become ready")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", action="store_true", help="Also exercise installed OCR with the generated synthetic fixture.")
    parser.add_argument("--visa-specimen", action="store_true", help="Also test the locally reviewed public visa fixture; requires --ocr.")
    options = parser.parse_args()
    if options.visa_specimen and not options.ocr:
        parser.error("--visa-specimen requires --ocr")
    if not CHROME.is_file():
        raise RuntimeError("Chrome is required for the optional browser test.")
    with tempfile.TemporaryDirectory(prefix="naviar-browser-test-") as folder:
        port, debug_port = free_port(), free_port()
        storage = Path(folder) / "uploads"
        command = (
            "from pathlib import Path; import app.documents as documents; "
            f"documents.UPLOAD_DIRECTORY=Path({str(storage)!r}); "
            "import app.deadline_api as planning; "
            f"planning.STATE_DIRECTORY=Path({str(Path(folder) / 'planning')!r}); "
            "import app.student_api as student; "
            f"student.STATE_DIRECTORY=Path({str(Path(folder) / 'student')!r}); "
            "from datetime import date; original_rules=student.rule_results; "
            "student.rule_results=lambda context:original_rules(context,today=date(2026,9,29)); "
            "original_evaluate=planning.evaluate_context; "
            "planning.evaluate_context=lambda context:original_evaluate(context,today=date(2026,9,29)); "
            "from app.main import app; "
            + ("from app.visa_engine.engine import VisaEngine; from scripts.visa_fixture import SyntheticVisaProvider; app.state.visa_engine=VisaEngine(SyntheticVisaProvider()); " if not options.ocr else "")
            + f"import uvicorn; uvicorn.run(app,host='127.0.0.1',port={port},log_level='error')"
        )
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        server = subprocess.Popen([sys.executable, "-c", command], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            wait_for(f"http://127.0.0.1:{port}/api/documents")
            browser = subprocess.Popen([
                str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={Path(folder) / 'browser'}", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            wait_for(f"http://127.0.0.1:{debug_port}/json/list")
            environment = dict(os.environ, NAVIAR_TEST_URL=f"http://127.0.0.1:{port}", NAVIAR_DEBUG_PORT=str(debug_port))
            if options.ocr:
                environment["NAVIAR_TEST_OCR"] = "1"
            if options.visa_specimen:
                environment["NAVIAR_TEST_VISA_SPECIMEN"]="1"
            subprocess.run(["node", "tests/check_ui.mjs"], cwd=ROOT, env=environment, check=True, timeout=360)
            # No uploaded files, fields, status, temporary index or deletion backups.
            assert json.loads((storage / "index.json").read_text()) == {}
            assert [path.name for path in storage.iterdir()] == ["index.json"]
            print("PASS: temporary storage contains no remaining documents or passport data.")
        finally:
            if browser is not None:
                try:
                    browser.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    browser.terminate()
                    browser.wait(timeout=10)
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()

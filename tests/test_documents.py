"""Run: .venv\\Scripts\\python.exe -m unittest discover -s tests -v
All files and the server used here are isolated in a temporary directory.
"""
import base64
import http.client
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jC1sAAAAASUVORK5CYII=")


def demo_pdf():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for number, content in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(number).encode() + b" 0 obj\n" + content + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 5\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return data + f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="naviar-tests-")
        cls.storage = Path(cls.temp.name) / "uploads"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.start_server()

    @classmethod
    def start_server(cls):
        code = (
            "from pathlib import Path; import app.documents as documents; "
            f"documents.UPLOAD_DIRECTORY=Path({str(cls.storage)!r}); "
            "from app.main import app; "
            "from app.document_engine.engine import DocumentEngine; "
            "from app.document_engine.models import OCRLine, OCRResult; "
            "first='P<UTO'+'SYNTHETIC<<DEMO<ONLY'.ljust(39,'<'); "
            "second='TEST000017UTO0001018X3001019'+'<'*14+'06'; "
            "provider=type('SyntheticProvider',(),{'extract':lambda self,path,context:OCRResult([OCRLine(first),OCRLine(second)]) if path.suffix=='.png' else OCRResult([OCRLine('SYNTHETIC CERTIFICATE')]) if path.suffix=='.jpg' else OCRResult([],['synthetic_no_text'])})(); "
            "app.state.document_engine=DocumentEngine(provider); "
            f"import uvicorn; uvicorn.run(app, host='127.0.0.1', port={cls.port}, log_level='error')"
        )
        cls.server = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urlopen(cls.base + "/api/documents", timeout=.3):
                    return
            except OSError:
                time.sleep(.1)
        raise RuntimeError("Test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.temp.cleanup()

    def api(self, path="", method="GET", body=None, headers=None):
        req = Request(self.base + "/api/documents" + path, data=body, method=method, headers=headers or {})
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as failure:
            response = failure
        with response:
            return response.status, response.read(), response.headers

    def upload(self, kind="passport", name="demo.png", mime="image/png", data=PNG, method="POST"):
        boundary = "naviar-test-boundary"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + data + f"\r\n--{boundary}--\r\n".encode())
        return self.api("/" + kind, method, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def setUp(self):
        for record in json.loads(self.api()[1]):
            if record['type']=='medical_certificates':
                self.api('/medical_certificates/'+record['document_id'],'DELETE')
        for kind in ("passport", "visa", "migration_card", "registration"):
            self.api("/" + kind, "DELETE")

    def test_upload_view_persistence_and_delete(self):
        self.assertEqual(self.upload()[0], 201)
        self.assertEqual(self.upload("visa", "demo.pdf", "application/pdf", demo_pdf())[0], 201)
        self.assertEqual(len(json.loads(self.api()[1])), 2)
        status, data, headers = self.api("/passport/file")
        self.assertEqual(status, 200)
        self.assertEqual(data, PNG)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(self.api("/visa/file")[1], demo_pdf())
        index = json.loads((self.storage / "index.json").read_text())
        stored = self.storage / index["passport"]["stored_name"]
        self.assertNotEqual(stored.name, "demo.png")
        self.assertTrue(stored.is_file())
        self.server.terminate()
        self.server.wait(timeout=10)
        type(self).start_server()
        self.assertEqual(len(json.loads(self.api()[1])), 2)
        self.assertEqual(self.api("/passport", "DELETE")[0], 204)
        self.assertFalse(stored.exists())
        self.assertEqual(self.api("/passport/file")[0], 404)
        self.assertEqual(len(json.loads(self.api()[1])), 1)

    def test_reject_types_signatures_empty_paths_and_duplicates(self):
        for name, mime, data in [
            ("demo.html", "text/html", b"<script>alert(1)</script>"),
            ("demo.png.exe", "image/png", PNG),
            ("demo.png", "application/pdf", PNG),
            ("fake.png", "image/png", b"not an image"),
            ("fake.pdf", "application/pdf", b"<html>not a PDF</html>"),
        ]:
            with self.subTest(name=name, mime=mime):
                self.assertEqual(self.upload(name=name, mime=mime, data=data)[0], 415)
        self.assertEqual(self.upload(data=b"")[0], 400)
        self.assertEqual(self.upload(name="../escape.png")[0], 400)
        self.assertEqual(self.upload(name="C:escape.png")[0], 400)
        self.assertEqual(self.upload(kind="unknown")[0], 422)
        self.assertEqual(self.upload()[0], 201)
        self.assertEqual(self.upload()[0], 409)
        self.assertEqual(len(json.loads(self.api()[1])), 1)
        self.assertEqual(len(list(self.storage.glob("*.png"))), 1)

    def test_size_boundary_and_request_limit(self):
        limit = 10 * 1024 * 1024
        pdf = demo_pdf()
        padded = pdf[:-6] + b" " * (limit - len(pdf)) + pdf[-6:]
        self.assertEqual(len(padded), limit)
        self.assertEqual(self.upload(name="limit.pdf", mime="application/pdf", data=padded)[0], 201)
        self.api("/passport", "DELETE")
        self.assertEqual(self.upload(name="large.pdf", mime="application/pdf", data=padded + b" ")[0], 413)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("POST", "/api/documents/passport")
        connection.putheader("Content-Length", str(limit + 65537))
        connection.putheader("Content-Type", "multipart/form-data; boundary=test")
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 413)
        connection.close()
        self.assertEqual(json.loads(self.api()[1]), [])

    def test_cross_site_and_static_access(self):
        self.assertEqual(self.api("/passport", "POST", b"", {"Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.api("/passport", "DELETE", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        with self.assertRaises(HTTPError) as failure:
            urlopen(self.base + "/static/../data/uploads/index.json")
        self.assertEqual(failure.exception.code, 404)
        failure.exception.close()


    def confirmation(self, data, document_id=None):
        if document_id is None:
            documents = json.loads(self.api()[1])
            document_id = next(item["document_id"] for item in documents if item["type"] == "passport")
        return self.api("/passport/data", "PUT", json.dumps({"document_id": document_id, "data": data}).encode(), {"Content-Type": "application/json"})

    @staticmethod
    def demo_passport():
        return {
            "last_name": "Fictional",
            "first_name": "Demo",
            "middle_name": "",
            "citizenship": "Test country",
            "passport_number": "TEST-0000",
            "birth_date": "2000-01-01",
            "issue_date": "2020-01-01",
            "expiry_date": "2030-01-01",
        }

    def test_passport_confirmation_edit_restart_delete_and_reupload(self):
        self.assertEqual(self.api("/passport/data")[0], 404)
        self.assertEqual(self.confirmation(self.demo_passport(), "0" * 32)[0], 404)
        status, uploaded, _ = self.upload()
        self.assertEqual(status, 201)
        uploaded = json.loads(uploaded)
        self.assertEqual(uploaded["status"], "needs_confirmation")
        self.assertIsNone(json.loads(self.api("/passport/data")[1])["data"])
        data = self.demo_passport()
        status, response, headers = self.confirmation(data)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["status"], "verified")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(self.api("/passport/data")[1])["data"], data)
        self.assertNotIn("passport_data", json.loads(self.api()[1])[0])
        self.assertNotIn(data["passport_number"].encode(), self.api()[1])
        data["first_name"] = "EditedDemo"
        self.assertEqual(self.confirmation(data)[0], 200)
        self.server.terminate()
        self.server.wait(timeout=10)
        type(self).start_server()
        self.assertEqual(json.loads(self.api("/passport/data")[1])["data"], data)
        index = json.loads((self.storage / "index.json").read_text())
        file_path = self.storage / index["passport"]["stored_name"]
        self.assertEqual(self.api("/passport", "DELETE")[0], 204)
        self.assertFalse(file_path.exists())
        self.assertEqual(json.loads((self.storage / "index.json").read_text()), {})
        self.assertFalse(list(self.storage.glob("*.tmp")))
        self.assertFalse(list(self.storage.glob("*.deleting")))
        self.assertEqual(self.api("/passport/data")[0], 404)
        self.assertEqual(self.upload()[0], 201)
        fresh = json.loads(self.api("/passport/data")[1])
        self.assertEqual(fresh["document"]["status"], "needs_confirmation")
        self.assertIsNone(fresh["data"])
        self.assertEqual(self.confirmation(data, uploaded["document_id"])[0], 409)
        self.assertIsNone(json.loads(self.api("/passport/data")[1])["data"])

    def test_required_fields_dates_and_private_validation_errors(self):
        self.upload()
        data = self.demo_passport()
        for field in data:
            if field == "middle_name":
                continue
            invalid = dict(data)
            del invalid[field]
            with self.subTest(missing=field):
                status, response, _ = self.confirmation(invalid)
                self.assertEqual(status, 422)
                self.assertNotIn(b'"input"', response)
                self.assertNotIn(data["passport_number"].encode(), response)
        for field, value in [
            ("last_name", "   "),
            ("first_name", "A" * 101),
            ("passport_number", " "),
            ("birth_date", "2099-01-01"),
            ("issue_date", "2099-01-01"),
            ("expiry_date", data["issue_date"]),
            ("expiry_date", "2019-01-01"),
            ("birth_date", "2000-02-30"),
            ("birth_date", 946684800),
        ]:
            with self.subTest(field=field, value_type=type(value).__name__):
                invalid = dict(data, **{field: value})
                self.assertEqual(self.confirmation(invalid)[0], 422)
        self.assertEqual(json.loads(self.api()[1])[0]["status"], "needs_confirmation")
        self.assertIsNone(json.loads(self.api("/passport/data")[1])["data"])
        without_optional = dict(data)
        del without_optional["middle_name"]
        self.assertEqual(self.confirmation(without_optional)[0], 200)
        self.assertEqual(self.confirmation(dict(data, expiry_date="2010-01-01"))[0], 422)
        self.assertEqual(json.loads(self.api("/passport/data")[1])["data"], data)
        self.assertEqual(self.api("/passport/data", "PUT", b"{}", {"Content-Type": "application/json", "Origin": "https://example.org"})[0], 403)

    def test_existing_uploads_default_to_needs_confirmation(self):
        self.upload()
        path = self.storage / "index.json"
        index = json.loads(path.read_text())
        del index["passport"]["status"]
        path.write_text(json.dumps(index), encoding="utf-8")
        self.assertEqual(json.loads(self.api()[1])[0]["status"], "needs_confirmation")
        self.assertEqual(self.api("/passport/file")[1], PNG)
        self.assertIsNone(json.loads(self.api("/passport/data")[1])["data"])
        self.assertEqual(self.upload("visa", "demo.pdf", "application/pdf", demo_pdf())[0], 201)
        self.assertEqual(next(item for item in json.loads(self.api()[1]) if item["type"] == "visa")["status"], "needs_confirmation")


    def process_passport(self, document_id=None, **context):
        if document_id is None:
            document_id = next(item["document_id"] for item in json.loads(self.api()[1]) if item["type"] == "passport")
        return self.api("/passport/process", "POST", json.dumps({"document_id": document_id, **context}).encode(), {"Content-Type": "application/json"})

    def test_processing_prefill_requires_confirmation_and_persists(self):
        self.assertEqual(self.process_passport("0" * 32)[0], 404)
        self.upload()
        status, response, _ = self.process_passport(country_of_study="KZ", issuing_country="UTO")
        self.assertEqual(status, 200)
        result = json.loads(response)
        self.assertEqual(result["document"]["status"], "needs_confirmation")
        self.assertEqual(result["data"]["last_name"], "SYNTHETIC")
        self.assertEqual(result["data"]["passport_number"], "TEST00001")
        self.assertIsNone(result["data"]["issue_date"])
        self.assertEqual(result["data"]["birth_date"], "2000-01-01")
        self.assertEqual(result["data"]["expiry_date"], "2030-01-01")
        self.assertEqual(result["extraction"]["status"], "partial")
        self.assertTrue(result["extraction"]["checks"]["composite"])
        index = json.loads((self.storage / "index.json").read_text())
        self.assertNotIn("passport_data", index["passport"])
        self.assertEqual(index["passport"]["extraction"]["context"]["country_of_study"], "KZ")
        self.server.terminate()
        self.server.wait(timeout=10)
        type(self).start_server()
        self.assertEqual(json.loads(self.api("/passport/data")[1])["data"], result["data"])
        self.assertEqual(self.confirmation(self.demo_passport())[0], 200)
        self.assertEqual(self.process_passport()[0], 409)
        self.assertEqual(json.loads(self.api("/passport/data")[1])["data"], self.demo_passport())
        self.assertEqual(self.api("/passport", "DELETE")[0], 204)
        self.assertEqual(json.loads((self.storage / "index.json").read_text()), {})

    def test_unsupported_result_keeps_manual_confirmation(self):
        # A synthetic JPEG header is sufficient for this injected-provider API test.
        self.assertEqual(self.upload(name="certificate.jpg", mime="image/jpeg", data=b"\xff\xd8\xff" + b"SYNTHETIC" + b"\xff\xd9")[0], 201)
        status, response, _ = self.process_passport()
        self.assertEqual(status, 200)
        result = json.loads(response)
        self.assertEqual(result["extraction"]["processing_status"], "unsupported_or_not_passport")
        self.assertEqual(result["document"]["status"], "needs_confirmation")
        self.assertTrue(all(value is None for value in result["data"].values()))
        self.assertNotIn("visual_date_candidates", result["extraction"])
        self.assertEqual(self.confirmation(self.demo_passport())[0], 200)

    def test_processing_failure_keeps_manual_entry(self):
        self.upload(name="synthetic.pdf", mime="application/pdf", data=demo_pdf())
        status, response, _ = self.process_passport()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["document"]["status"], "processing_error")
        self.assertIsNone(json.loads(response)["data"]["last_name"])
        self.assertEqual(self.confirmation(self.demo_passport())[0], 200)
        self.assertEqual(json.loads(self.api()[1])[0]["status"], "verified")
        self.assertEqual(self.api("/migration_card/process", "POST", b"{}", {"Content-Type": "application/json"})[0], 404)

    def medical_files(self):
        return [record for record in json.loads(self.api()[1]) if record['type']=='medical_certificates']

    slots=('medical_hiv_certificate','medical_infectious_diseases_certificate','medical_drug_screening_certificate')

    def upload_slot(self, slot=0, **kwargs):
        return self.upload('medical_certificates?medical_type='+self.slots[slot], **kwargs)

    def test_medical_each_slot_accepts_all_formats(self):
        fixtures=[('exam.png','image/png',PNG),('exam.jpg','image/jpeg',b'\xff\xd8\xffDEMO\xff\xd9'),('exam.jpeg','image/jpeg',b'\xff\xd8\xffDEMO\xff\xd9'),('exam.pdf','application/pdf',demo_pdf())]
        for slot in range(3):
            for name,mime,content in fixtures:
                with self.subTest(slot=slot,name=name):
                    status,body,_=self.upload_slot(slot,name=name,mime=mime,data=content)
                    self.assertEqual(status,201)
                    record=json.loads(body)
                    self.assertEqual(record['medical_type'],self.slots[slot])
                    self.assertEqual(record['original_filename'],name)
                    self.assertEqual(record['file_id'],record['document_id'])
                    self.assertTrue(record['uploaded_at'])
                    self.assertEqual(self.api(record['url'].removeprefix('/api/documents'))[1],content)
                    self.api('/medical_certificates/'+record['document_id'],'DELETE')

    def test_medical_three_slots_exist_and_persist(self):
        slots=json.loads(self.api('/medical_certificates/slots')[1])
        self.assertEqual(len(slots),3)
        self.assertTrue(all(s['file_id'] is None and s['status']=='not_uploaded' for s in slots))
        for count in range(3):
            self.upload_slot(count)
            current=json.loads(self.api('/medical_certificates/slots')[1])
            self.assertEqual(sum(s['file_id'] is not None for s in current),count+1)
        self.assertEqual(len({r['file_id'] for r in self.medical_files()}),3)
        self.server.terminate(); self.server.wait(timeout=10); type(self).start_server()
        self.assertEqual(len(self.medical_files()),3)

    def test_medical_delete_only_target_slot(self):
        self.upload('passport'); self.upload('visa')
        for slot in range(3): self.upload_slot(slot)
        files=self.medical_files(); before={r['file_id']:self.api(r['url'].removeprefix('/api/documents'))[1] for r in files}
        self.assertEqual(self.api('/medical_certificates/'+files[1]['file_id'],'DELETE')[0],204)
        for record in (files[0],files[2]):
            self.assertEqual(self.api(record['url'].removeprefix('/api/documents'))[1],before[record['file_id']])
        self.assertEqual(self.api('/passport/file')[1],PNG)
        self.assertEqual(self.api('/visa/file')[1],PNG)
        self.assertEqual(len(self.medical_files()),2)

    def test_medical_replacement_isolated_and_rejects_slot_change(self):
        for slot in range(3): self.upload_slot(slot)
        files=self.medical_files(); old=files[0]
        path='medical_certificates/'+old['file_id']
        self.assertEqual(self.upload(path+'?medical_type='+self.slots[1],method='PUT')[0],409)
        self.assertEqual(self.upload(path,'bad.pdf','application/pdf',b'bad',method='PUT')[0],415)
        self.assertEqual(self.api(old['url'].removeprefix('/api/documents'))[1],PNG)
        status,body,_=self.upload(path,'new.pdf','application/pdf',demo_pdf(),method='PUT')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['medical_type'],self.slots[0])
        self.assertEqual(self.api(old['url'].removeprefix('/api/documents'))[0],404)
        self.assertEqual(len(self.medical_files()),3)
        for sibling in files[1:]: self.assertIn(sibling['file_id'],[r['file_id'] for r in self.medical_files()])

    def test_medical_occupied_slot_cannot_accumulate_files(self):
        self.upload_slot()
        self.assertEqual(self.upload_slot()[0],409)
        self.assertEqual(len(self.medical_files()),1)
        self.assertEqual(len(list(self.storage.glob('*.png'))),1)

    def test_medical_cannot_target_other_category(self):
        self.upload('passport'); passport=json.loads(self.api()[1])[0]
        path='/medical_certificates/'+passport['document_id']
        self.assertEqual(self.api(path,'DELETE')[0],404)
        self.assertEqual(self.api(path+'/file')[0],404)
        self.assertEqual(self.upload(path.lstrip('/'),method='PUT')[0],404)
        self.assertEqual(self.api('/passport/file')[1],PNG)

    def test_medical_reject_group_delete_and_invalid_id(self):
        self.upload_slot()
        self.assertEqual(self.api('/medical_certificates','DELETE')[0],409)
        for identity in ('not-an-id','0'*32):
            self.assertEqual(self.api('/medical_certificates/'+identity,'DELETE')[0],404)
        self.assertEqual(len(self.medical_files()),1)

    def test_medical_all_legacy_types_preserved_unassigned(self):
        for legacy in ('medical_exam_certificate','additional_medical_certificate','other_medical_document','other_supported_medical_document'):
            self.upload_slot()
            path=self.storage/'index.json'; index=json.loads(path.read_text())
            record=next(r for r in index['medical_certificates'] if r['medical_type']==self.slots[0])
            record['medical_type']=legacy; path.write_text(json.dumps(index))
        before={p.name:p.read_bytes() for p in self.storage.iterdir()}
        self.assertEqual(len(self.medical_files()),4)
        self.assertTrue(all(r['legacy'] for r in self.medical_files()))
        self.assertTrue(all(r['file_id'] is None for r in json.loads(self.api('/medical_certificates/slots')[1])))
        self.assertEqual({p.name:p.read_bytes() for p in self.storage.iterdir()},before)
        self.upload_slot()
        self.assertEqual(len(self.medical_files()),5)
        for record in self.medical_files(): self.assertEqual(self.api(record['url'].removeprefix('/api/documents'))[1],PNG)

    def test_medical_legacy_singleton_read_without_rewrite(self):
        self.upload_slot(); path=self.storage/'index.json'; index=json.loads(path.read_text())
        record=index['medical_certificates'][0]; record.pop('medical_type')
        index['medical_certificates']=record; path.write_text(json.dumps(index)); before=path.read_bytes()
        self.assertTrue(self.medical_files()[0]['legacy'])
        self.assertEqual(path.read_bytes(),before)
        self.upload_slot()
        self.assertEqual(len(self.medical_files()),2)

    def test_medical_rejects_generic_types_paths_and_bad_content(self):
        self.assertEqual(self.upload('medical_certificates')[0],422)
        for generic in ('medical_exam_certificate','additional_medical_certificate','other_supported_medical_document','arbitrary'):
            self.assertEqual(self.upload('medical_certificates?medical_type='+generic)[0],422)
        self.assertEqual(self.upload_slot(name='../bad.png')[0],400)
        self.assertEqual(self.upload_slot(name='bad.exe',mime='application/octet-stream',data=b'bad')[0],415)
        self.assertEqual(self.upload_slot(data=b'bad')[0],415)
        self.assertEqual(self.upload_slot(data=PNG+b'0'*(10*1024*1024))[0],413)
        self.assertEqual(self.medical_files(),[])

    def test_medical_independent_dates_persist_and_remaining(self):
        from datetime import date
        for slot in range(3): self.upload_slot(slot)
        file=self.medical_files()[0]; endpoint='/medical_certificates/'+file['file_id']+'/dates'
        dates={'issue_date':'2026-09-01','valid_until':'2026-10-30'}
        status,body,_=self.api(endpoint,'PATCH',json.dumps(dates).encode(),{'Content-Type':'application/json'})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['days_remaining'],(date(2026,10,30)-date.today()).days)
        self.assertTrue(all(r['issue_date'] is None for r in self.medical_files() if r['file_id']!=file['file_id']))
        self.server.terminate(); self.server.wait(timeout=10); type(self).start_server()
        self.assertEqual(next(r for r in self.medical_files() if r['file_id']==file['file_id'])['valid_until'],dates['valid_until'])
        for invalid in ({'issue_date':'2026-10-30','valid_until':'2026-09-01'},{'issue_date':'not-a-date'}):
            status,body,_=self.api(endpoint,'PATCH',json.dumps(invalid).encode(),{'Content-Type':'application/json'})
            self.assertEqual(status,422); self.assertNotIn(b'not-a-date',body)



if __name__ == "__main__":
    unittest.main()

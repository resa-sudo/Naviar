"""HTTP integration, all document/profile storage isolated from user data."""
import json
from pathlib import Path
import subprocess,sys,time,unittest
from urllib.request import urlopen,Request
from unittest.mock import patch
import test_documents as fixtures
from app import documents,student_api
from app.visa_api import process_visa,confirm_visa,ProcessingRequest
from app.visa_engine.models import VisaConfirmation
from types import SimpleNamespace

class VisaAPITests(unittest.TestCase):
    setUpClass=classmethod(fixtures.DocumentTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.DocumentTests.tearDownClass.__func__)
    api=fixtures.DocumentTests.api
    upload=fixtures.DocumentTests.upload
    setUp=fixtures.DocumentTests.setUp

    @classmethod
    def start_server(cls):
        code=("from pathlib import Path; import app.documents as d; import app.student_api as s; "
              f"d.UPLOAD_DIRECTORY=Path({str(cls.storage)!r}); s.STATE_DIRECTORY=Path({str(cls.storage.parent/'student')!r}); "
              "from app.main import app; from app.visa_engine.engine import VisaEngine; from scripts.visa_fixture import SyntheticVisaProvider; "
              "app.state.visa_engine=VisaEngine(SyntheticVisaProvider()); "
              f"import uvicorn; uvicorn.run(app,host='127.0.0.1',port={cls.port},log_level='error')")
        cls.server=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urlopen(cls.base+'/api/documents',timeout=.3): return
            except OSError: time.sleep(.1)
        raise RuntimeError('Test server did not start')

    def json_api(self,path,method='GET',data=None):
        status,body,_=self.api('/visa/'+path,method,json.dumps(data).encode() if data is not None else None,{'Content-Type':'application/json'})
        return status,json.loads(body)

    def uploaded(self,**kwargs):
        return json.loads(self.upload(kind='visa',**kwargs)[1])['document_id']

    def test_ocr_confirmation_context_deadline_and_persistence(self):
        profile=dict(citizenship='tm',university='rudn',degree='bachelor',language='ru')
        with urlopen(Request(self.base+'/api/student/profile',data=json.dumps(profile).encode(),method='PUT',headers={'Content-Type':'application/json'})): pass
        identity=self.uploaded();status,processed=self.json_api('process','POST',dict(document_id=identity))
        self.assertEqual(status,200);self.assertEqual(processed['document']['status'],'needs_confirmation')
        self.assertNotIn('ocr_blocks',processed['extraction']);self.assertNotIn('date_candidates',processed['extraction'])
        with urlopen(self.base+'/api/student/context') as response: before=json.load(response)
        self.assertFalse(before['context']['visa']['valid_until']['confirmed'])
        data=processed['data'];data['visa_number']='MANUAL0001'
        status,confirmed=self.json_api('data','PUT',dict(document_id=identity,data=data))
        self.assertEqual(status,200);self.assertEqual(confirmed['document']['status'],'verified')
        self.assertEqual(confirmed['fields']['visa_number']['source'],'manual')
        self.assertFalse(confirmed['fields']['valid_until']['needs_confirmation'])
        self.server.terminate();self.server.wait(timeout=10);type(self).start_server()
        self.assertEqual(self.json_api('data')[1]['data']['visa_number'],'MANUAL0001')
        with urlopen(self.base+'/api/student/context') as response: context=json.load(response)
        visa=context['context']['visa'];self.assertTrue(visa['confirmed']['value'])
        self.assertEqual(visa['visa_number']['source'],'manual_confirmed')
        self.assertEqual(visa['valid_until']['source'],'visa_ocr')
        self.assertEqual(visa['expiry_date']['value'],'2026-10-30')
        self.assertTrue(any(row['result']['deadline_date']=='2026-10-02' for row in context['rules']['procedures']))
        self.assertTrue(context['next_actions'])
        self.assertEqual(self.json_api('process','POST',dict(document_id=identity))[0],409)

    def test_repeat_ocr_and_legacy_manual_preserved(self):
        identity=self.uploaded()
        correction={'field':'expiry_date','value':'2026-11-30','confirmed':True}
        with urlopen(Request(self.base+'/api/student/documents/visa/'+identity+'/field',data=json.dumps(correction).encode(),method='PATCH',headers={'Content-Type':'application/json'})): pass
        for _ in range(2):
            status,result=self.json_api('process','POST',dict(document_id=identity))
            self.assertEqual(status,200);self.assertEqual(result['data']['valid_until'],'2026-11-30')
            self.assertEqual(result['document']['status'],'needs_confirmation')
            with urlopen(self.base+'/api/student/context') as response: snapshot=json.load(response)
            if snapshot['context']:
                self.assertEqual(snapshot['context']['visa']['expiry_date']['value'],'2026-11-30')
                self.assertTrue(snapshot['context']['visa']['expiry_date']['confirmed'])

    def test_unsupported_pdf_and_manual_fallback(self):
        identity=self.uploaded(name='demo.pdf',mime='application/pdf',data=fixtures.demo_pdf())
        status,result=self.json_api('process','POST',dict(document_id=identity))
        self.assertEqual(result['extraction']['processing_status'],'failed')
        self.assertIn('ocr_images_only',result['extraction']['errors'])
        self.assertEqual(self.json_api('data','PUT',dict(document_id=identity,data={'valid_until':'2026-10-30'}))[0],200)

    def test_random_image_unsupported(self):
        identity=self.uploaded(name='demo.jpg',mime='image/jpeg',data=b'\xff\xd8\xffTEST\xff\xd9')
        result=self.json_api('process','POST',dict(document_id=identity))[1]
        self.assertEqual(result['extraction']['processing_status'],'unsupported_or_not_visa')
        self.assertTrue(all(v is None for v in result['data'].values()))

    def test_stale_form_and_sanitized_validation(self):
        identity=self.uploaded()
        self.assertEqual(self.json_api('process','POST',dict(document_id='0'*32))[0],409)
        self.assertEqual(self.json_api('data','PUT',dict(document_id='0'*32,data={'visa_number':'DEMO'}))[0],409)
        status,result=self.json_api('data','PUT',dict(document_id=identity,data={'visa_number':'SECRET\nVALUE'}))
        self.assertEqual(status,422);self.assertNotIn('SECRET',json.dumps(result))

    def test_edit_confirmed_and_delete(self):
        identity=self.uploaded()
        for expiry in ['2026-10-30','2026-11-30']:
            result=self.json_api('data','PUT',dict(document_id=identity,data={'valid_until':expiry}))[1]
            self.assertEqual(result['data']['valid_until'],expiry)
        self.assertEqual(self.api('/visa','DELETE')[0],204)
        self.assertEqual(self.json_api('data')[0],404)

class VisaRaceTests(unittest.TestCase):
    def test_confirmation_during_processing_wins(self):
        import tempfile
        from scripts.visa_fixture import SyntheticVisaProvider
        from app.visa_engine.engine import VisaEngine
        with tempfile.TemporaryDirectory() as folder, patch.object(documents,'UPLOAD_DIRECTORY',Path(folder)):
            record=documents.save_document('visa','demo.png','image/png',fixtures.PNG)
            identity=record['document_id']
            class Engine:
                def process(self,path):
                    confirm_visa(VisaConfirmation(document_id=identity,data={'valid_until':'2026-12-30'}))
                    return VisaEngine(SyntheticVisaProvider()).process(path)
            result=process_visa(ProcessingRequest(document_id=identity),SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(visa_engine=Engine()))))
            self.assertEqual(result['document']['status'],'verified');self.assertEqual(result['data']['valid_until'],'2026-12-30')

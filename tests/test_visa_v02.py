"""Synthetic low-resolution/layout regressions; never reads working uploads."""
from dataclasses import asdict
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.document_engine.models import OCRLine,OCRResult,ProcessingContext
from app.visa_engine.models import FIELD_NAMES
from app.visa_engine.engine import VisaEngine
from app.visa_engine.detection import detect_visa,mrz_like_pairs
from app.visa_engine.visual import extract_visual,header_number_candidates
from app.visa_engine.preprocessing import read_visa_image,scale_factor
from app.visa_engine.mrz import parse_mrz
from scripts.visa_fixture import mrz_rows,layout


def small_layout():
    first,second=mrz_rows()
    # Missing characters: detection must not reconstruct them.
    return [OCRLine('VISA',.99,(20,20,100,50)),
            OCRLine('12',.99,(210,20,240,50)),OCRLine('3456789',.99,(245,20,365,50)),
            OCRLine('15.09.26/30.10.26',.99,(150,100,340,125)),
            OCRLine(first[:-1],.98,(15,300,580,325)),OCRLine(second[:-1],.99,(15,340,580,365))]

class VisaV02Tests(unittest.TestCase):
    def run_engine(self,lines,size=(600,400)):
        provider=type('Provider',(),{'extract':lambda self,*args:OCRResult(lines)})()
        with patch('app.visa_engine.preprocessing.read_visa_image',return_value=(OCRResult(lines),{'image_size':list(size)},None)):
            return VisaEngine(provider,prepare_images=True).process(Path('synthetic.png'))

    def test_supported_partial_without_valid_mrz(self):
        result=self.run_engine(small_layout())
        self.assertEqual(result['processing_status'],'supported_partial')
        self.assertEqual(result['detected_document_type'],'visa')
        self.assertEqual(result['extracted_fields']['visa_number']['value'],'123456789')
        self.assertEqual(result['extracted_fields']['visa_number']['source'],'visual_ocr')
        self.assertTrue(result['mrz_found']);self.assertFalse(result['mrz']['valid'])
        self.assertTrue(all(field['needs_confirmation'] for field in result['extracted_fields'].values()))

    def test_short_dates_not_guessed(self):
        fields=self.run_engine(small_layout())['extracted_fields']
        for key in ('issue_date','valid_from','valid_until'): self.assertIsNone(fields[key]['value'])

    def test_visa_word_and_numbers_without_mrz_insufficient(self):
        result=self.run_engine(small_layout()[:4])
        self.assertEqual(result['processing_status'],'unsupported_or_not_visa')
        self.assertIsNone(result['extracted_fields']['visa_number']['value'])
        self.assertIn('insufficient_independent_visa_evidence',result['detection']['reasons'])

    def test_passport_mrz_not_visa_evidence(self):
        lines=small_layout();first=lines[4];lines[4]=OCRLine('P'+first.text[1:],first.confidence,first.bbox)
        self.assertEqual(self.run_engine(lines)['processing_status'],'unsupported_or_not_visa')

    def test_random_nonvisa(self):
        lines=[OCRLine('CERTIFICATE',.99,(10,10,180,40)),OCRLine('123456789',.99,(220,10,400,40)),OCRLine('2026-10-30',.99,(30,80,200,110))]
        self.assertEqual(self.run_engine(lines)['processing_status'],'unsupported_or_not_visa')

    def test_two_header_numbers_not_selected(self):
        base=small_layout();lines=[base[0],OCRLine('123456789',.99,(130,20,220,50)),OCRLine('987654321',.99,(240,20,365,50)),*base[3:]]
        result=self.run_engine(lines)
        self.assertIsNone(result['extracted_fields']['visa_number']['value'])
        self.assertEqual(result['processing_status'],'supported_partial')

    def test_header_date_not_serial(self):
        lines=small_layout();lines[1:3]=[OCRLine('30102026',.99,(210,20,365,50))]
        self.assertEqual(header_number_candidates(lines,(600,400)),[])

    def test_low_confidence_header_not_used(self):
        for index in (0,2):
            lines=small_layout();line=lines[index];lines[index]=OCRLine(line.text,.89,line.bbox)
            self.assertIsNone(self.run_engine(lines)['extracted_fields']['visa_number']['value'])

    def test_weak_or_nonheader_geometry(self):
        for box in [(245,180,365,210),(500,20,600,50)]:
            lines=small_layout();lines[1:3]=[OCRLine('123456789',.99,box)]
            self.assertIsNone(self.run_engine(lines)['extracted_fields']['visa_number']['value'])

    def test_bad_mrz_layout_not_evidence(self):
        lines=small_layout();last=lines[-1];lines[-1]=OCRLine(last.text,last.confidence,(200,380,580,399))
        self.assertEqual(mrz_like_pairs(lines,(600,400)),[])

    def test_labels_and_confidence_reported(self):
        result=self.run_engine(layout(False),(1750,1140))
        self.assertEqual(result['processing_status'],'success')
        self.assertTrue(result['detection']['matched_labels'])
        self.assertTrue(all('confidence' in label and 'bbox' in label for label in result['detection']['matched_labels']))

    def test_scale_policy_bounded(self):
        self.assertEqual(scale_factor(600,401),3);self.assertEqual(scale_factor(900,600),2)
        self.assertEqual(scale_factor(1750,1140),1)

    def test_preprocessing_preserves_original_and_cleans_copies(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'original.png';Image.new('RGB',(600,400),'white').save(path)
            digest=hashlib.sha256(path.read_bytes()).hexdigest();seen=[]
            class Provider:
                def extract(self,copy,context):
                    seen.append(copy)
                    with Image.open(copy) as image: assert image.size==(1800,1200)
                    return OCRResult([OCRLine('unrelated',.99,(30,60,300,120))])
            output,info,recovery=read_visa_image(Provider(),path,ProcessingContext('visa'))
            self.assertEqual(info['upscale_factor'],3);self.assertEqual(output.lines[0].bbox,(10,20,100,40))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            self.assertTrue(all(not p.exists() for p in seen));self.assertIsNone(recovery)

    def test_mrz_crop_whitelist_no_repair_and_cleanup(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'original.png';Image.new('RGB',(600,400),'white').save(path);seen=[]
            class Provider:
                def extract(self,copy,context):
                    seen.append(copy)
                    if len(seen)==1:
                        return OCRResult([OCRLine(b.text,b.confidence,tuple(v*3 for v in b.bbox)) for b in small_layout()])
                    return OCRResult([OCRLine('V<ABC'+('X'*34)+'?',.99,(0,0,1600,70))])
            output,info,recovery=read_visa_image(Provider(),path,ProcessingContext('visa'))
            self.assertEqual(len(seen),2);self.assertEqual(recovery.lines,[])
            self.assertTrue(info['mrz_recovery']['raw_blocks'][0]['text'].endswith('?'))
            self.assertTrue(info['mrz_recovery']['rejected_lines'])
            self.assertTrue(all(not p.exists() for p in seen))

    def test_crop_failure_preserves_visual_result(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'original.png';Image.new('RGB',(600,400),'white').save(path)
            class Provider:
                calls=0
                def extract(self,copy,context):
                    self.calls+=1
                    if self.calls>1: raise RuntimeError('private path')
                    return OCRResult([OCRLine(b.text,b.confidence,tuple(v*3 for v in b.bbox)) for b in small_layout()])
            result=VisaEngine(Provider(),prepare_images=True).process(path)
            self.assertEqual(result['processing_status'],'supported_partial')
            self.assertEqual(result['extracted_fields']['visa_number']['value'],'123456789')
            self.assertIn('mrz_crop_failed',result['errors']);self.assertNotIn('private path',str(result))

    def test_public_demo_captured_blocks_optional(self):
        path=Path('.document-lab/visa-v02/upscale-3-blocks.json')
        metadata=Path('.document-lab/fixtures/russian-public-visa.provenance.json')
        if not path.exists() or not metadata.exists(): self.skipTest('Public demo not installed; synthetic suite is standalone')
        lines=[OCRLine(b['text'],b['confidence'],tuple(v/3 for v in b['bbox'])) for b in json.loads(path.read_text(encoding='utf-8'))['lines']]
        result=self.run_engine(lines,(600,401))
        self.assertEqual(result['processing_status'],'supported_partial')
        self.assertEqual(result['extracted_fields']['visa_number']['value'],json.loads(metadata.read_text(encoding='utf-8'))['expected_fields']['visa_number'])

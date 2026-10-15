"""Visa orchestration using the same local provider as Passport OCR."""
from dataclasses import asdict
from datetime import date
from time import perf_counter
import re
from app.document_engine.models import ExtractedField, ProcessingContext
from .models import FIELD_NAMES, MAIN_FIELDS
from .visual import extract_visual,header_number_candidates
from .detection import detect_visa
from .mrz import parse_mrz

class VisaEngine:
    def __init__(self,provider,prepare_images=False):
        self.provider=provider
        self.prepare_images=prepare_images

    def process(self,path,context=None):
        started=perf_counter()
        context=context or ProcessingContext('visa','RU')
        fields={key:ExtractedField() for key in FIELD_NAMES}
        result=dict(processing_status='failed',detected_document_type='unknown',mrz_found=False,mrz_format=None,
                    errors=[],ocr_blocks=[],date_candidates={},entries_candidates=[],visa_type_candidates=[])
        try:
            recovery=None
            if self.prepare_images:
                from .preprocessing import read_visa_image
                output,image_analysis,recovery=read_visa_image(self.provider,path,context)
                result['image_analysis']=image_analysis
            else:
                output=self.provider.extract(path,context)
                image_analysis={}
            image_size=image_analysis.get('image_size')
            result['ocr_blocks']=[asdict(line) for line in output.lines]
            result['errors']=list(output.errors)
            if recovery is not None: result['errors'].extend(recovery.errors)
            if not output.lines and not output.errors:
                result['processing_status']='unsupported_or_not_visa'
                result['detection']=detect_visa([],fields,{},image_size)
            if output.lines:
                fields,candidates=extract_visual(output.lines)
                mrz=parse_mrz(output.lines)
                if recovery is not None:
                    recovered=parse_mrz(recovery.lines)
                    result['mrz_recovery_result']=recovered
                    if recovered.get('valid'): mrz=recovered
                result.update(mrz_found=mrz['found'],mrz_format=mrz['format'],mrz=mrz,
                    date_candidates={key:candidates[key] for key in ('issue_date','valid_from','valid_until')},
                    entries_candidates=candidates['entries'],visa_type_candidates=candidates['visa_type'],candidates=candidates)
                headers=header_number_candidates(output.lines,image_size)
                detection=detect_visa(output.lines,fields,mrz,image_size,headers)
                result['detection']=detection
                result['header_number_candidates']=headers
                pairs=detection['mrz_like_pairs']
                result['mrz_found']=bool(mrz.get('found') or pairs)
                result['mrz_raw_lines']=pairs[0]['raw_lines'] if len(pairs)==1 else []
                if not detection['supported']:
                    fields={key:ExtractedField() for key in FIELD_NAMES}
                    result['processing_status']='unsupported_or_not_visa'
                else:
                    # Header serial fallback is never used without independent MRV-like evidence.
                    values={item['value'] for item in headers}
                    if len(pairs)==1 and len(values)==1 and fields['visa_number'].value is None:
                        chosen=max(headers,key=lambda item:item['score'])
                        fields['visa_number']=ExtractedField(chosen['value'],chosen['score'],'visual_ocr',True)
                        chosen['selected']=True
                    result['detected_document_type']='visa'
                    if mrz.get('valid'):
                        score=mrz.get('confidence')
                        # Unknown/low OCR confidence cannot supply unchecked MRZ fields.
                        if score is not None and score>=.90:
                            national=mrz['citizenship']
                            if re.fullmatch('[A-Z]{3}',national) and national not in ('XXX',):
                                if fields['citizenship'].value not in (None,national):
                                    fields['citizenship']=ExtractedField();result['errors'].append('citizenship_conflict')
                                else: fields['citizenship']=ExtractedField(national,score,'mrz',True)
                            # Disambiguate number role only with an agreeing labelled visual field.
                            for key in ('visa_number','passport_number_if_present'):
                                if fields[key].value==mrz['document_number']:
                                    fields[key]=ExtractedField(mrz['document_number'],min(score,fields[key].confidence),'mrz',True)
                            expiry=fields['valid_until']
                            if expiry.value:
                                if date.fromisoformat(expiry.value).strftime('%y%m%d')==mrz['valid_until_raw']:
                                    fields['valid_until']=ExtractedField(expiry.value,min(score,expiry.confidence),'mrz',True)
                                else:
                                    fields['valid_until']=ExtractedField();result['errors'].append('expiry_conflict')
                            else: result['errors'].append('mrz_expiry_century_unresolved')
                    issue=fields['issue_date'].value;start=fields['valid_from'].value;end=fields['valid_until'].value
                    if issue and issue>date.today().isoformat():
                        fields['issue_date']=ExtractedField();result['errors'].append('issue_date_in_future')
                    if end and any(v and v>end for v in (issue,start)):
                        for key in ('issue_date','valid_from','valid_until'): fields[key]=ExtractedField()
                        result['errors'].append('conflicting_date_order')
                    result['processing_status']='success' if all(fields[k].value for k in MAIN_FIELDS) else 'supported_partial' if detection['basis']=='combined_evidence' else 'partial'
        except Exception:
            # No provider exception, path or recognized text in public errors/logs.
            fields={key:ExtractedField() for key in FIELD_NAMES}
            result.update(processing_status='failed',errors=['ocr_failed'])
        result['extracted_fields']={key:asdict(value) for key,value in fields.items()}
        result['processing_seconds']=round(perf_counter()-started,3)
        return result

"""Bounded visa-only OCR copies. The original file is never changed."""
from dataclasses import asdict
from pathlib import Path
import re
import tempfile
from time import perf_counter
from app.document_engine.models import OCRLine,OCRResult
from .mrz import parse_mrz
from .detection import mrz_like_pairs,visa_markers,DATE_TOKEN

MAX_PIXELS=20_000_000

def scale_factor(width,height):
    longest=max(width,height)
    return 3 if longest<=600 else 2 if longest<=900 else 1

def remap(lines,factor,offset_y=0):
    return [OCRLine(line.text,line.confidence,
        (line.bbox[0]/factor,line.bbox[1]/factor+offset_y,line.bbox[2]/factor,line.bbox[3]/factor+offset_y) if line.bbox else None)
        for line in lines]

def read_visa_image(provider,path,context):
    started=perf_counter()
    diagnostics=dict(preprocessing='none',passes=[],mrz_recovery=None)
    if path.suffix.lower() not in {'.jpg','.jpeg','.png'}:
        return provider.extract(path,context),diagnostics,None
    from PIL import Image
    with Image.open(path) as source:
        if source.width*source.height>MAX_PIXELS: raise ValueError('image_dimensions_too_large')
        source.load()
        factor=scale_factor(*source.size)
        diagnostics.update(image_size=list(source.size),upscale_factor=factor,preprocessing='lanczos_upscale' if factor>1 else 'none',coordinate_space='original_image')
        # OS temporary directory, removed on success and failure. Never static/uploads.
        with tempfile.TemporaryDirectory(prefix='naviar-visa-ocr-') as folder:
            work=Path(folder)/'visual.png'
            if factor>1:
                source.resize((source.width*factor,source.height*factor),Image.Resampling.LANCZOS).save(work)
            before=perf_counter()
            output=provider.extract(work if factor>1 else path,context)
            output.lines=remap(output.lines,factor)
            diagnostics['passes'].append(dict(name='visual',scale=factor,processing_seconds=round(perf_counter()-before,3),blocks=len(output.lines)))
            recovery=None
            pairs=mrz_like_pairs(output.lines,source.size)
            possible=bool(pairs or (visa_markers(output.lines) and any(DATE_TOKEN.search(line.text) for line in output.lines)))
            if not output.errors and not parse_mrz(output.lines).get('valid') and possible:
                if pairs:
                    top=max(0,int(min(p['bbox'][1] for p in pairs)-source.height*.04))
                else: top=int(source.height*.62)
                crop=source.crop((0,top,source.width,source.height))
                crop_factor=scale_factor(*crop.size)
                crop_path=Path(folder)/'mrz.png'
                crop.resize((crop.width*crop_factor,crop.height*crop_factor),Image.Resampling.LANCZOS).save(crop_path)
                before=perf_counter()
                try: recovery=provider.extract(crop_path,context)
                except Exception: recovery=OCRResult([], ["mrz_crop_failed"])
                raw_lines=remap(recovery.lines,crop_factor,top)
                accepted=[];rejected=[]
                for line in raw_lines:
                    compact=re.sub(r'\s+','',line.text.upper())
                    if re.fullmatch(r'[A-Z0-9<]{30,50}',compact): accepted.append(line)
                    else: rejected.append(dict(raw_text=line.text,reason='outside_mrz_whitelist_or_length'))
                recovery.lines=accepted
                diagnostics['mrz_recovery']=dict(crop_box=[0,top,source.width,source.height],scale=crop_factor,
                    raw_blocks=[asdict(line) for line in raw_lines],rejected_lines=rejected,
                    whitelist='A-Z 0-9 <',whitelist_mode='acceptance_filter_no_character_repair',errors=recovery.errors,
                    processing_seconds=round(perf_counter()-before,3))
                diagnostics['passes'].append(dict(name='mrz_crop',scale=crop_factor,processing_seconds=diagnostics['mrz_recovery']['processing_seconds'],blocks=len(raw_lines)))
    diagnostics['processing_seconds']=round(perf_counter()-started,3)
    return output,diagnostics,recovery

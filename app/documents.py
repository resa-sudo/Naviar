"""Local, single-user demo storage. Never use for real identity documents."""

from datetime import date, datetime, timezone
import json
import re
from enum import Enum
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.visa_engine.models import VisaData
from app.medical_models import MedicalFileDates
from app.document_models import DocumentStatus, PassportConfirmation, PassportData

UPLOAD_DIRECTORY = Path(__file__).resolve().parent.parent / "data" / "uploads"
MAX_FILE_SIZE = 10 * 1024 * 1024
storage_lock = RLock()  # Run this local MVP with one server worker.
router = APIRouter(prefix="/api/documents", tags=["documents"])
FORMATS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}
SAFE_NAME = re.compile(r"[a-f0-9]{32}\.(jpg|png|pdf)")


class DocumentType(str, Enum):
    passport = "passport"
    visa = "visa"
    migration_card = "migration_card"
    registration = "registration"
    medical_certificates = "medical_certificates"


class MedicalDocumentType(str, Enum):
    medical_hiv_certificate = 'medical_hiv_certificate'
    medical_infectious_diseases_certificate = 'medical_infectious_diseases_certificate'
    medical_drug_screening_certificate = 'medical_drug_screening_certificate'


LEGACY_MEDICAL_TYPES = {'medical_exam_certificate', 'additional_medical_certificate',
                        'other_supported_medical_document', 'other_medical_document', 'legacy_unassigned'}


def records_for(kind, value):
    return value if kind == 'medical_certificates' else [value]


def read_index():
    path = UPLOAD_DIRECTORY / "index.json"
    if not path.exists():
        return {}
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(index, dict):
            raise ValueError("Invalid index")
        for kind, value in index.items():
            DocumentType(kind)
            # Read the previous one-file medical schema without rewriting user data.
            if kind == 'medical_certificates' and isinstance(value, dict):
                value = [value]
                index[kind] = value
            for record in records_for(kind, value):
                if not SAFE_NAME.fullmatch(record['stored_name']):
                    raise ValueError('Invalid stored name')
                if record['content_type'] not in FORMATS.values():
                    raise ValueError('Invalid type')
                if kind == 'medical_certificates':
                    record.setdefault('medical_type', 'legacy_unassigned')
                    if record['medical_type'] not in LEGACY_MEDICAL_TYPES:
                        MedicalDocumentType(record['medical_type'])
                        MedicalFileDates.model_validate({key:record.get(key) for key in ('issue_date','valid_until')})
                status = DocumentStatus(record.get('status', 'needs_confirmation'))
                if status == DocumentStatus.verified:
                    if kind == 'passport':
                        PassportData.model_validate(record['passport_data'])
                    elif kind == 'visa':
                        VisaData.model_validate(record['visa_data'])
                    else:
                        raise ValueError('Unsupported verified document')
        return index
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(500, "storage_error") from None


def write_index(index):
    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = UPLOAD_DIRECTORY / "index.tmp"
    temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(UPLOAD_DIRECTORY / "index.json")


def stored_path(record):
    name = record["stored_name"]
    if not SAFE_NAME.fullmatch(name):
        raise HTTPException(500, "storage_error")
    path = (UPLOAD_DIRECTORY / name).resolve()
    if path.parent != UPLOAD_DIRECTORY.resolve():
        raise HTTPException(500, "storage_error")
    return path


def medical_metadata(record):
    until = date.fromisoformat(record['valid_until']) if record.get('valid_until') else None
    return dict(medical_type=record['medical_type'],
                legacy=record['medical_type'] in LEGACY_MEDICAL_TYPES,
                file_id=Path(record['stored_name']).stem, original_filename=record['name'],
                uploaded_at=record.get('uploaded_at'), issue_date=record.get('issue_date'),
                valid_until=record.get('valid_until'), days_remaining=(until-date.today()).days if until else None)


def public_record(kind, record):
    # Never send passport fields in the dashboard list.
    return {
        "type": kind,
        "document_id": Path(record["stored_name"]).stem,
        "name": record["name"],
        "size": record["size"],
        "content_type": record["content_type"],
        "url": f"/api/documents/{kind}/{Path(record["stored_name"]).stem}/file" if kind == "medical_certificates" else f"/api/documents/{kind}/file",
        **(medical_metadata(record) if kind == "medical_certificates" else {}),
        "status": record.get("status", DocumentStatus.needs_confirmation.value),
    }


def validate_file(filename, content_type, content):
    # Original names are display text only; reject submitted paths on every OS.
    if not filename or len(filename) > 180 or any(character in filename for character in '/\\:') or any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise HTTPException(400, "invalid_filename")
    extension = Path(filename).suffix.lower()
    if extension not in FORMATS or content_type != FORMATS[extension]:
        raise HTTPException(415, "unsupported_type")
    if not content:
        raise HTTPException(400, "empty_file")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "file_too_large")
    # Basic signatures, not malware scanning or complete format validation.
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n") and content[12:16] == b"IHDR" and content.endswith(b"\x00\x00\x00\x00IEND\xaeB" + bytes([96, 130])),
        "application/pdf": content.startswith(b"%PDF-") and b"%%EOF" in content[-1024:],
    }
    if not signatures[content_type]:
        raise HTTPException(415, "invalid_content")
    return {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}[content_type]


def medical_record(index, document_id):
    if not re.fullmatch(r'[a-f0-9]{32}', document_id):
        raise HTTPException(404, 'document_not_found')
    record = next((item for item in index.get('medical_certificates', [])
                   if Path(item['stored_name']).stem == document_id), None)
    if record is None:
        raise HTTPException(404, 'document_not_found')
    return record


def save_document(kind, filename, content_type, content, medical_type=None, replace_id=None):
    extension = validate_file(filename, content_type, content)
    with storage_lock:
        index = read_index()
        original = dict(index)
        old = medical_record(index, replace_id) if replace_id else None
        if kind != 'medical_certificates' and kind in index:
            raise HTTPException(409, 'document_exists')
        UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
        record = {'stored_name': uuid4().hex + extension, 'name': filename,
                  'content_type': content_type, 'size': len(content),
                  'status': DocumentStatus.needs_confirmation.value}
        if kind == 'medical_certificates':
            chosen = medical_type or (old or {}).get('medical_type')
            if chosen is None:
                raise HTTPException(422, 'medical_slot_required')
            if chosen in LEGACY_MEDICAL_TYPES:
                raise HTTPException(409, 'legacy_medical_unassigned')
            chosen = MedicalDocumentType(chosen).value
            if old and old['medical_type'] != chosen:
                raise HTTPException(409, 'medical_slot_mismatch')
            if any(item is not old and item['medical_type'] == chosen for item in index.get(kind, [])):
                raise HTTPException(409, 'medical_slot_occupied')
            record.update(medical_type=chosen, status='uploaded', uploaded_at=datetime.now(timezone.utc).isoformat(), issue_date=None, valid_until=None)
            index[kind] = [item for item in index.get(kind, []) if item is not old] + [record]
        else:
            index[kind] = record
        path = stored_path(record)
        old_path = stored_path(old) if old else None
        backup = old_path.with_suffix('.replacing') if old_path else None
        committed = False
        try:
            with path.open('xb') as output:
                output.write(content)
            if old_path and old_path.exists():
                old_path.replace(backup)
            write_index(index)
            committed = True
            if backup:
                backup.unlink(missing_ok=True)
        except OSError:
            if backup and backup.exists():
                backup.replace(old_path)
            path.unlink(missing_ok=True)
            if committed:
                write_index(original)
            raise HTTPException(500, 'storage_error') from None
        return public_record(kind, record)


def file_response(record):
    if not record or not stored_path(record).is_file():
        raise HTTPException(404, 'document_not_found')
    return FileResponse(stored_path(record), media_type=record['content_type'], filename=record['name'], content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store', 'Content-Security-Policy': "sandbox; default-src 'none'"})


def remove_stored_record(record, index, original):
    path = stored_path(record)
    backup = path.with_suffix('.deleting')
    existed = path.exists()
    try:
        if existed:
            path.replace(backup)
        write_index(index)
    except OSError:
        if existed and backup.exists():
            backup.replace(path)
        raise HTTPException(500, 'storage_error') from None
    try:
        backup.unlink(missing_ok=True)
    except OSError:
        backup.replace(path)
        write_index(original)
        raise HTTPException(500, 'storage_error') from None


@router.get('')
def list_documents():
    with storage_lock:
        return [public_record(kind, record) for kind, value in read_index().items()
                for record in records_for(kind, value) if stored_path(record).is_file()]


async def receive_document(kind, request, medical_type=None, replace_id=None):
    # One file per request retains the existing bounded multipart pipeline.
    if request.headers.get('content-type', '').split(';', 1)[0].lower() != 'multipart/form-data':
        raise HTTPException(415, 'unsupported_type')
    async with request.form(max_files=1, max_fields=0) as form:
        file = form.get('file')
        if not isinstance(file, UploadFile) or len(form.multi_items()) != 1:
            raise HTTPException(400, 'file_required')
        content = await file.read(MAX_FILE_SIZE + 1)
        return await run_in_threadpool(save_document, kind, file.filename, file.content_type, content, medical_type, replace_id)


@router.post('/{kind}', status_code=201)
async def upload_document(kind: DocumentType, request: Request, medical_type: MedicalDocumentType | None = None):
    return await receive_document(kind.value, request, medical_type)


@router.get('/medical_certificates/slots')
def medical_slots():
    with storage_lock:
        files = {record['medical_type']: record for record in list_documents()
                 if record['type'] == 'medical_certificates' and not record['legacy']}
        return [dict(medical_type=slot.value, status='not_uploaded', file_id=None,
                     original_filename=None, uploaded_at=None, issue_date=None,
                     valid_until=None, days_remaining=None) if slot.value not in files
                else files[slot.value] for slot in MedicalDocumentType]


@router.patch('/medical_certificates/{document_id}/dates')
def save_medical_dates(document_id: str, dates: MedicalFileDates):
    with storage_lock:
        index = read_index()
        record = medical_record(index, document_id)
        if record['medical_type'] in LEGACY_MEDICAL_TYPES:
            raise HTTPException(409, 'legacy_medical_unassigned')
        record.update(dates.model_dump(mode='json'))
        try:
            write_index(index)
        except OSError:
            raise HTTPException(500, 'storage_error') from None
        return public_record('medical_certificates', record)


@router.get('/medical_certificates/{document_id}/file')
def view_medical_file(document_id: str):
    with storage_lock:
        return file_response(medical_record(read_index(), document_id))


@router.put('/medical_certificates/{document_id}')
async def replace_medical_file(document_id: str, request: Request, medical_type: MedicalDocumentType | None = None):
    return await receive_document('medical_certificates', request, medical_type, document_id)


@router.delete('/medical_certificates/{document_id}', status_code=204)
def delete_medical_file(document_id: str):
    with storage_lock:
        index = read_index()
        original = dict(index)
        record = medical_record(index, document_id)
        remaining = [item for item in index['medical_certificates'] if item is not record]
        if remaining:
            index['medical_certificates'] = remaining
        else:
            del index['medical_certificates']
        remove_stored_record(record, index, original)


@router.get('/{kind}/file')
def view_document(kind: DocumentType):
    with storage_lock:
        record = read_index().get(kind.value)
        if kind == DocumentType.medical_certificates:
            if not record:
                raise HTTPException(404, 'document_not_found')
            if len(record) != 1:
                raise HTTPException(409, 'medical_file_id_required')
            record = record[0]
        return file_response(record)


@router.delete('/{kind}', status_code=204)
def delete_document(kind: DocumentType):
    # Medical mutations must name an individual file; never delete a whole group.
    if kind == DocumentType.medical_certificates:
        raise HTTPException(409, 'medical_file_id_required')
    with storage_lock:
        index = read_index()
        original = dict(index)
        record = index.pop(kind.value, None)
        if record is None:
            raise HTTPException(404, 'document_not_found')
        remove_stored_record(record, index, original)


def require_passport(index):
    record = index.get("passport")
    if record is None or not stored_path(record).is_file():
        raise HTTPException(404, "document_not_found")
    return record


@router.get("/passport/data")
def get_passport_data():
    with storage_lock:
        record = require_passport(read_index())
        from app.document_processing import processing_view
        return processing_view(record)


@router.put("/passport/data")
def confirm_passport_data(confirmation: PassportConfirmation):
    with storage_lock:
        index = read_index()
        record = require_passport(index)
        if confirmation.document_id != Path(record["stored_name"]).stem:
            raise HTTPException(409, "document_changed")
        record["passport_data"] = confirmation.data.model_dump(mode="json")
        record["status"] = DocumentStatus.verified.value
        try:
            write_index(index)
        except OSError:
            raise HTTPException(500, "storage_error") from None
        return public_record("passport", record)

"""Thin NAVIAR integration. The document engine itself does not know storage."""
from dataclasses import asdict
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app import documents
from app.document_engine.models import ProcessingContext
from app.document_models import DocumentStatus

router = APIRouter(prefix="/api/documents", tags=["document-processing"])


class PassportProcessingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    country_of_study: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    issuing_country: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


def processing_view(record):
    extraction = record.get("extraction")
    data = record.get("passport_data")
    if data is None and extraction:
        fields = extraction["mrz"]["fields"]
        mapping = {
            "last_name": "surname", "first_name": "given_names",
            "citizenship": "nationality", "passport_number": "passport_number",
            "birth_date": "date_of_birth", "expiry_date": "expiry_date",
            "issue_date": "date_of_issue",
        }
        data = {name: fields.get(source, {}).get("value") for name, source in mapping.items()}
        data.update(middle_name=None)
    summary = None
    if extraction:
        summary = {
            "status": extraction["status"],
            "processing_status": extraction["status"],
            "detected_document_type": extraction.get("detection", {}).get("detected_document_type"),
            "fields": extraction["mrz"]["fields"],
            "checks": extraction["mrz"]["checks"],
            "raw_dates": extraction["mrz"]["raw_dates"],
            "errors": extraction["errors"],
        }
    return {"document": documents.public_record("passport", record), "data": data, "extraction": summary}


@router.post("/passport/process")
def process_passport(body: PassportProcessingRequest, request: Request):
    with documents.storage_lock:
        index = documents.read_index()
        record = documents.require_passport(index)
        if Path(record["stored_name"]).stem != body.document_id:
            raise HTTPException(409, "document_changed")
        if record.get("status") == DocumentStatus.verified.value:
            raise HTTPException(409, "already_verified")
        if record.get("status") == DocumentStatus.processing.value:
            raise HTTPException(409, "processing_in_progress")
        path = documents.stored_path(record)
        record["status"] = DocumentStatus.processing.value
        try:
            documents.write_index(index)
        except OSError:
            raise HTTPException(500, "storage_error") from None

    context = ProcessingContext("passport", body.country_of_study, body.issuing_country)
    # The engine catches provider failures; no OCR output is sent to logs.
    result = request.app.state.document_engine.process(path, context)

    with documents.storage_lock:
        index = documents.read_index()
        record = documents.require_passport(index)
        if Path(record["stored_name"]).stem != body.document_id:
            raise HTTPException(409, "document_changed")
        # A simultaneous manual confirmation always takes precedence over OCR.
        if record.get("status") == DocumentStatus.verified.value:
            return processing_view(record)
        record["extraction"] = asdict(result)
        record["status"] = (DocumentStatus.processing_error.value if result.status == "failed"
                            else DocumentStatus.needs_confirmation.value)
        try:
            documents.write_index(index)
        except OSError:
            raise HTTPException(500, "storage_error") from None
        return processing_view(record)

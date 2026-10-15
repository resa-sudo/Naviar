"""NAVIAR Student: student interface and local demo documents."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.documents import MAX_FILE_SIZE, router as documents_router
from app.document_processing import router as processing_router
from app.deadline_api import router as deadlines_router
from app.student_api import router as student_router
from app.visa_api import router as visa_router
from app.visa_engine.engine import VisaEngine
from app.document_engine.engine import DocumentEngine
from app.document_engine.paddle_provider import PaddleOCRProvider

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"

app = FastAPI(title="NAVIAR Student", version="0.1.0")
app.add_middleware(RequestBodyLimitMiddleware, max_body_size=MAX_FILE_SIZE + 64 * 1024)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
app.include_router(documents_router)
app.include_router(processing_router)
app.include_router(deadlines_router)
app.include_router(student_router)
app.include_router(visa_router)
app.state.document_engine = DocumentEngine(PaddleOCRProvider())
app.state.visa_engine = VisaEngine(PaddleOCRProvider(),prepare_images=True)
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")


@app.middleware("http")
async def protect_local_api(request, call_next):
    # Reject cross-site browser mutations; this is not authentication.
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        expected_origin = str(request.base_url).rstrip("/")
        if (origin and origin != expected_origin) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "origin_not_allowed"}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/", include_in_schema=False)
def student_app():
    return FileResponse(STATIC_DIRECTORY / "index.html")


@app.exception_handler(RequestValidationError)
async def validation_error(request, exception):
    if request.url.path.startswith("/api/documents/visa/") or request.url.path.startswith("/api/student/") or request.url.path.startswith("/api/documents/medical_certificates/") or request.url.path == "/api/documents/passport/data" or request.url.path.startswith("/api/deadlines/"):
        # Pydantic errors contain submitted input by default. Return codes only.
        fields = []
        for error in exception.errors():
            location = error.get("loc", ())
            code = error["type"]
            if code == "value_error":
                message = str(error.get("ctx", {}).get("error", ""))
                if message in {"date_in_future", "expiry_must_follow_issue", "invalid_date", "invalid_text"}:
                    code = message
            fields.append({"field": str(location[-1]) if location else "form", "code": code})
        return JSONResponse(
            {"detail": "validation_error", "fields": fields},
            status_code=422,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    return await request_validation_exception_handler(request, exception)

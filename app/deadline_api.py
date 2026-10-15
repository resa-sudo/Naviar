"""Local single-user demo planning, separate from uploaded documents."""
import json
from pathlib import Path
from threading import RLock
from fastapi import APIRouter, HTTPException
from .deadlines.models import StudentContext
from .deadlines.rules import evaluate_context

router = APIRouter(prefix='/api/deadlines', tags=['deadlines'])
STATE_DIRECTORY = Path(__file__).resolve().parents[1] / 'data' / 'planning'
lock = RLock()


@router.get('/state')
def get_state():
    with lock:
        path = STATE_DIRECTORY / 'context.json'
        if not path.exists():
            return {'context':None}
        try:
            context = StudentContext.model_validate_json(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise HTTPException(500,'planning_storage_error') from None
        return {'context':context.model_dump(mode='json')}


@router.post('/calculate')
def calculate(context: StudentContext):
    return planning_result(context)


@router.put('/state')
def save_state(context: StudentContext):
    with lock:
        try:
            STATE_DIRECTORY.mkdir(parents=True,exist_ok=True)
            temporary = STATE_DIRECTORY / 'context.tmp'
            temporary.write_text(context.model_dump_json(indent=2),encoding='utf-8')
            temporary.replace(STATE_DIRECTORY / 'context.json')
        except OSError:
            raise HTTPException(500,'planning_storage_error') from None
    return planning_result(context)


def planning_result(context):
    result = evaluate_context(context)
    from .documents import list_documents
    result['medical_certificates']['files'] = [record['document_id'] for record in list_documents() if record['type'] == 'medical_certificates']
    return result

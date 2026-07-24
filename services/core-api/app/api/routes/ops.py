from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.ops_store import ops_store

router = APIRouter(prefix="/ops", tags=["ops"])


class WorkflowUpdate(BaseModel):
    status: Literal["ACTIVE", "PAUSED"]


class DocumentCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=40)
    content: str = Field(min_length=10, max_length=10_000)
    source: str = Field(default="직접 입력", max_length=80)
    status: Literal["DRAFT", "PUBLISHED"] = "DRAFT"


class DocumentUpdate(BaseModel):
    status: Literal["DRAFT", "PUBLISHED", "ARCHIVED"]


@router.get("/workflows")
async def list_workflows() -> list[dict[str, object]]:
    return ops_store.list_workflows()


@router.patch("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, payload: WorkflowUpdate) -> dict[str, object]:
    workflow = ops_store.update_workflow(workflow_id, payload.status)
    if workflow is None:
        raise HTTPException(status_code=404, detail="워크플로를 찾을 수 없습니다.")
    return workflow


@router.get("/knowledge-documents")
async def list_documents() -> list[dict[str, object]]:
    return ops_store.list_documents()


@router.post("/knowledge-documents", status_code=201)
async def create_document(payload: DocumentCreate) -> dict[str, object]:
    return ops_store.create_document(payload.model_dump())


@router.patch("/knowledge-documents/{document_id}")
async def update_document(document_id: str, payload: DocumentUpdate) -> dict[str, object]:
    document = ops_store.update_document(document_id, payload.status)
    if document is None:
        raise HTTPException(status_code=404, detail="지식 문서를 찾을 수 없습니다.")
    return document


@router.get("/integrations")
async def list_integrations() -> list[dict[str, object]]:
    return ops_store.list_integrations()


@router.post("/integrations/{integration_id}/check")
async def check_integration(integration_id: str) -> dict[str, object]:
    discord_ready = bool(get_settings().discord_webhook_url)
    integration = ops_store.check_integration(integration_id, discord_ready=discord_ready)
    if integration is None:
        raise HTTPException(status_code=404, detail="연동을 찾을 수 없습니다.")
    return integration


@router.get("/failed-jobs")
async def list_failed_jobs() -> list[dict[str, object]]:
    return ops_store.list_failed_jobs()


@router.post("/failed-jobs/{job_id}/retry")
async def retry_failed_job(job_id: str) -> dict[str, object]:
    discord_ready = bool(get_settings().discord_webhook_url)
    job = ops_store.retry_failed_job(job_id, discord_ready=discord_ready)
    if job is None:
        raise HTTPException(status_code=404, detail="실패 작업을 찾을 수 없습니다.")
    return job


@router.get("/audit-logs")
async def list_audit_logs() -> list[dict[str, object]]:
    return ops_store.list_audit_logs()

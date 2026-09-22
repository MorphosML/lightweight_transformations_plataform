from __future__ import annotations

import uuid
from typing import Any

try:
    from fastapi import Depends, FastAPI, HTTPException, status
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    # Minimal fallback stubs for environments where fastapi is not installed
    class FastAPI:  # type: ignore
        def __init__(self, *args, **kwargs): pass
        def get(self, *args, **kwargs): return lambda f: f
        def post(self, *args, **kwargs): return lambda f: f
    def Depends(f): return f  # type: ignore
    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    class status:  # type: ignore
        HTTP_404_NOT_FOUND = 404
        HTTP_400_BAD_REQUEST = 400
        HTTP_201_CREATED = 201

from openflow_engine.errors import CycleError, PipelineExecutionError
from .deps import TenantContext, get_tenant_context
from .schemas import (
    PipelineCreate,
    PipelineResponse,
    PreviewRequest,
    RunPipelineRequest,
)
from .service import PipelineService

app = FastAPI(
    title="OpenFlow ELT Platform API",
    description="Multi-tenant DAG execution and transformation engine with PySpark support",
    version="0.1.0",
)

# In-memory storage of pipeline definitions for demonstration/testing
_PIPELINES_DB: dict[str, dict[str, Any]] = {}
pipeline_service = PipelineService()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "openflow-api"}


@app.post("/api/v1/pipelines", status_code=status.HTTP_201_CREATED)
def create_pipeline(
    payload: PipelineCreate,
    tenant: TenantContext = Depends(get_tenant_context),
) -> PipelineResponse:
    # 1. Validate graph cycle detection on save (R2)
    try:
        payload.graph.validate_acyclic()
    except CycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid graph: {exc}",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    pipeline_id = str(uuid.uuid4())
    record = {
        "id": pipeline_id,
        "org_id": tenant.org_id,
        "project_id": tenant.project_id,
        "name": payload.name,
        "description": payload.description,
        "graph_json": payload.graph.model_dump() if hasattr(payload.graph, "model_dump") else payload.graph.dict(),
        "version": 1,
    }
    _PIPELINES_DB[pipeline_id] = record

    return PipelineResponse(**record)


@app.get("/api/v1/pipelines/{pipeline_id}")
def get_pipeline(
    pipeline_id: str,
    tenant: TenantContext = Depends(get_tenant_context),
) -> PipelineResponse:
    record = _PIPELINES_DB.get(pipeline_id)
    # Enforce tenant isolation (S3)
    if not record or record["org_id"] != tenant.org_id or record["project_id"] != tenant.project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline {pipeline_id} not found in this project",
        )
    return PipelineResponse(**record)


@app.post("/api/v1/pipelines/{pipeline_id}/run")
def run_pipeline(
    pipeline_id: str,
    req: RunPipelineRequest = RunPipelineRequest(),
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    pipeline = get_pipeline(pipeline_id, tenant)
    try:
        result = pipeline_service.execute_pipeline(
            graph_dict=pipeline.graph_json,
            tenant=tenant,
            engine=req.engine,
        )
        return {
            "status": "succeeded",
            "pipeline_id": pipeline_id,
            "engine": req.engine,
            "logs": [
                {
                    "node_id": l.node_id,
                    "status": l.status,
                    "duration_ms": l.duration_ms,
                    "rows": l.rows,
                    "error": l.error,
                }
                for l in result.logs
            ],
        }
    except PipelineExecutionError as exc:
        return {
            "status": "failed",
            "pipeline_id": pipeline_id,
            "engine": req.engine,
            "error": str(exc),
            "logs": [
                {
                    "node_id": l.node_id,
                    "status": l.status,
                    "duration_ms": l.duration_ms,
                    "rows": l.rows,
                    "error": l.error,
                }
                for l in exc.logs  # type: ignore
            ],
        }


@app.post("/api/v1/pipelines/{pipeline_id}/preview")
def preview_pipeline_node(
    pipeline_id: str,
    req: PreviewRequest,
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    pipeline = get_pipeline(pipeline_id, tenant)
    try:
        records = pipeline_service.preview_node(
            graph_dict=pipeline.graph_json,
            tenant=tenant,
            target_node_id=req.node_id,
            limit=min(req.limit, 100),  # Safe bounded preview (A6)
            engine=req.engine,
        )
        return {
            "node_id": req.node_id,
            "row_count": len(records),
            "data": records,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Preview failed: {exc}",
        )

from __future__ import annotations

import io
import os
import uuid
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

import pandas as pd

try:
    from fastapi import Depends, FastAPI, HTTPException, status
    from fastapi.responses import HTMLResponse
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
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
    class HTMLResponse:  # type: ignore
        def __init__(self, content: str): self.content = content

from openflow_engine.connectors import InMemoryConnector
from openflow_engine.errors import CycleError, PipelineExecutionError
from .code_executor import CodeExecutor, ExecutionOutput
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
    description="Multi-tenant DAG execution, transformation studio, and ingestion engine with PySpark",
    version="0.1.0",
)

# Shared in-memory connector and pipeline store
shared_connector = InMemoryConnector()
pipeline_service = PipelineService(default_connector=shared_connector)
_PIPELINES_DB: dict[str, dict[str, Any]] = {}

STATIC_INDEX_PATH = Path(__file__).parent / "static" / "index.html"


# UI Routes
@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def serve_ui() -> Any:
    """Serves the interactive Ingestion & Transformation UI."""
    if STATIC_INDEX_PATH.exists():
        return HTMLResponse(content=STATIC_INDEX_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>OpenFlow Ingestion Studio UI file not found</h1>")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "openflow-api"}


# Ingestion Schemas & Endpoints
class LoadPresetRequest(BaseModel):
    preset: str = "ecommerce"


class UploadDatasetRequest(BaseModel):
    filename: str
    content: str


class TransformExecuteRequest(BaseModel):
    dataset_key: str
    engine: Literal["pyspark", "pandas", "ast_filter", "sql"] = "pyspark"
    code: str
    limit: int = 100


def _generate_preset_dataframe(preset_name: str) -> tuple[str, pd.DataFrame]:
    import numpy as np

    if preset_name == "iot_sensors":
        key = "iot_telemetry.csv"
        rows = 100
        df = pd.DataFrame(
            {
                "device_id": [f"sensor-{i%10 + 1:03d}" for i in range(rows)],
                "temperature": [round(20.0 + (i * 0.3) % 15.0, 2) for i in range(rows)],
                "humidity": [round(45.0 + (i * 0.5) % 35.0, 2) for i in range(rows)],
                "battery_pct": [100 - (i % 60) for i in range(rows)],
                "alert": ["Normal" if i % 7 != 0 else "High Temp" for i in range(rows)],
            }
        )
    elif preset_name == "customers":
        key = "customer_demographics.csv"
        rows = 100
        df = pd.DataFrame(
            {
                "customer_id": [1000 + i for i in range(rows)],
                "age": [18 + (i % 55) for i in range(rows)],
                "country": [["USA", "Germany", "France", "Japan", "Brazil"][i % 5] for i in range(rows)],
                "plan_type": [["Basic", "Pro", "Enterprise"][i % 3] for i in range(rows)],
                "monthly_spend": [round(29.0 + (i * 3.7) % 300.0, 2) for i in range(rows)],
                "churn_risk": ["Low" if i % 4 != 0 else "High" for i in range(rows)],
            }
        )
    else:  # default ecommerce
        key = "ecommerce_sales.csv"
        rows = 100
        df = pd.DataFrame(
            {
                "order_id": [5000 + i for i in range(rows)],
                "customer_id": [1000 + (i % 30) for i in range(rows)],
                "country": [["USA", "Canada", "UK", "Germany", "Japan"][i % 5] for i in range(rows)],
                "category": [["Electronics", "Clothing", "Home", "Books", "Sports"][i % 5] for i in range(rows)],
                "amount": [round(15.0 + (i * 7.5) % 450.0, 2) for i in range(rows)],
                "status": [["Completed", "Completed", "Pending", "Cancelled"][i % 4] for i in range(rows)],
            }
        )
    return key, df


@app.post("/api/v1/ingest/load-preset")
def load_preset(
    payload: LoadPresetRequest,
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    key, df = _generate_preset_dataframe(payload.preset)
    shared_connector.write(tenant.org_id, key, df, tenant.project_id)
    return {
        "status": "ingested",
        "key": key,
        "row_count": len(df),
        "columns": list(df.columns),
    }


@app.post("/api/v1/ingest/upload")
def upload_dataset(
    payload: UploadDatasetRequest,
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    try:
        if payload.filename.endswith(".json") or payload.content.strip().startswith("["):
            df = pd.read_json(io.StringIO(payload.content))
        else:
            df = pd.read_csv(io.StringIO(payload.content))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse uploaded data: {exc}",
        )

    clean_key = payload.filename.lstrip("/")
    shared_connector.write(tenant.org_id, clean_key, df, tenant.project_id)
    return {
        "status": "ingested",
        "key": clean_key,
        "row_count": len(df),
        "columns": list(df.columns),
    }


@app.post("/api/v1/transform/execute")
def execute_transform(
    payload: TransformExecuteRequest,
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    # 1. Read the ingested dataset from tenant connector
    try:
        df = shared_connector.read(tenant.org_id, payload.dataset_key, tenant.project_id)
    except KeyError:
        # If not yet loaded, auto-load preset or raise
        _, df = _generate_preset_dataframe("ecommerce")
        shared_connector.write(tenant.org_id, payload.dataset_key, df, tenant.project_id)

    # 2. Execute user code
    result = CodeExecutor.execute(
        code=payload.code,
        engine=payload.engine,
        df=df,
        limit=payload.limit,
    )

    return {
        "status": result.status,
        "duration_ms": result.duration_ms,
        "row_count": result.row_count,
        "columns": result.columns,
        "schema": result.schema,
        "records": result.records,
        "error": result.error,
        "engine_details": result.engine_details,
    }


# Pipeline Endpoints
@app.post("/api/v1/pipelines", status_code=status.HTTP_201_CREATED)
def create_pipeline(
    payload: PipelineCreate,
    tenant: TenantContext = Depends(get_tenant_context),
) -> PipelineResponse:
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
            limit=min(req.limit, 100),
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

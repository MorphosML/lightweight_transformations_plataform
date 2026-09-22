from __future__ import annotations

import datetime
import os
import time
from typing import Any

from openflow_engine.connectors import ObjectStorageConnector
from openflow_engine.errors import PipelineExecutionError
from openflow_engine.pyspark_engine import SparkConnectionConfig
from .deps import TenantContext
from .models import Execution, Pipeline
from .service import PipelineService

try:
    from celery import Celery
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    class Celery:  # type: ignore
        def __init__(self, *args, **kwargs): pass
        def task(self, *args, **kwargs): return lambda f: f

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///openflow.db")
SPARK_CONNECT_URL = os.getenv("SPARK_CONNECT_URL")

celery_app = Celery(
    "openflow_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)


def get_db_session():
    """Provides a managed SQLAlchemy database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(DATABASE_URL.replace("+asyncpg", ""))
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


@celery_app.task(name="openflow.execute_pipeline")
def execute_pipeline_task(
    pipeline_id: str,
    org_id: str,
    project_id: str,
    engine_type: str = "pandas",
) -> dict[str, Any]:
    """Celery task executing a pipeline with full session lifecycle and execution tracking (M1)."""
    session = get_db_session()
    tenant = TenantContext(org_id=org_id, project_id=project_id)

    # 1. Fetch Pipeline record using SQLAlchemy 2.0 session.get
    pipeline = session.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.org_id != org_id or pipeline.project_id != project_id:
        session.close()
        raise ValueError(f"Pipeline {pipeline_id} not found for tenant {org_id}")

    # 2. Create Execution record
    execution = Execution(
        pipeline_id=pipeline_id,
        org_id=org_id,
        project_id=project_id,
        status="running",
        engine=engine_type,
        logs=[],
        created_at=datetime.datetime.utcnow(),
    )
    session.add(execution)
    session.commit()
    session.refresh(execution)

    start_time = time.perf_counter()
    service = PipelineService()
    spark_cfg = SparkConnectionConfig(connect_url=SPARK_CONNECT_URL) if SPARK_CONNECT_URL else None

    try:
        runner = service.build_runner(
            graph_dict=pipeline.graph_json,
            tenant=tenant,
            engine=engine_type,
            spark_config=spark_cfg,
        )
        run_result = runner.run()

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        execution.status = "succeeded"
        execution.duration_ms = round(duration_ms, 2)
        execution.finished_at = datetime.datetime.utcnow()
        execution.logs = [
            {
                "node_id": l.node_id,
                "status": l.status,
                "duration_ms": l.duration_ms,
                "rows": l.rows,
                "error": l.error,
            }
            for l in run_result.logs
        ]
        session.commit()
        return {"status": "succeeded", "execution_id": execution.id}

    except PipelineExecutionError as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        execution.status = "failed"
        execution.duration_ms = round(duration_ms, 2)
        execution.finished_at = datetime.datetime.utcnow()
        execution.logs = [
            {
                "node_id": l.node_id,
                "status": l.status,
                "duration_ms": l.duration_ms,
                "rows": l.rows,
                "error": l.error,
            }
            for l in exc.logs  # type: ignore
        ]
        session.commit()
        return {"status": "failed", "execution_id": execution.id, "error": str(exc)}

    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        execution.status = "failed"
        execution.duration_ms = round(duration_ms, 2)
        execution.finished_at = datetime.datetime.utcnow()
        session.commit()
        return {"status": "failed", "execution_id": execution.id, "error": str(exc)}

    finally:
        session.close()


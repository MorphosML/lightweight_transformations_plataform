from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd


class BaseConnector(ABC):
    """Abstract connector interface enforcing tenant and project key isolation.
    
    Eliminates arbitrary server filesystem paths (S2, A1) and ensures all I/O
    is scoped to the tenant namespace across both Pandas and PySpark engines.
    """

    @abstractmethod
    def read(self, tenant_id: str, key: str, project_id: str | None = None) -> pd.DataFrame:
        """Reads a table as a pandas DataFrame."""
        ...

    @abstractmethod
    def write(
        self,
        tenant_id: str,
        key: str,
        frame: pd.DataFrame,
        project_id: str | None = None,
    ) -> None:
        """Writes a pandas DataFrame to the scoped key."""
        ...

    @abstractmethod
    def read_spark(self, tenant_id: str, key: str, spark: Any, project_id: str | None = None) -> Any:
        """Reads a table as a PySpark DataFrame."""
        ...

    @abstractmethod
    def write_spark(
        self,
        tenant_id: str,
        key: str,
        df: Any,
        project_id: str | None = None,
        mode: str = "overwrite",
    ) -> None:
        """Writes a PySpark DataFrame to the scoped key."""
        ...

    @staticmethod
    def validate_and_scope_key(tenant_id: str, key: str, project_id: str | None = None) -> str:
        """Validates key syntax and guarantees isolation under tenant/project namespace."""
        tenant = tenant_id.strip() if tenant_id else ""
        if not tenant:
            raise ValueError("tenant_id must be provided and non-empty")
        
        # Strip leading slashes and whitespace
        clean_key = key.strip().lstrip("/")
        if not clean_key:
            raise ValueError("key must be non-empty")

        parts = clean_key.split("/")
        if ".." in parts or "." in parts:
            raise ValueError("path traversal characters are forbidden in connector keys")

        if project_id and project_id.strip():
            project = project_id.strip().lstrip("/")
            return f"{tenant}/{project}/{clean_key}"
        return f"{tenant}/{clean_key}"


class InMemoryConnector(BaseConnector):
    """In-memory storage connector for tests and local development."""

    def __init__(self, objects: Mapping[str, pd.DataFrame] | None = None) -> None:
        self._objects: dict[str, pd.DataFrame] = {
            key: value.copy() for key, value in (objects or {}).items()
        }

    def read(self, tenant_id: str, key: str, project_id: str | None = None) -> pd.DataFrame:
        scoped_key = self.validate_and_scope_key(tenant_id, key, project_id)
        if scoped_key not in self._objects:
            raise KeyError(f"object not found for tenant: {scoped_key}")
        return self._objects[scoped_key].copy()

    def write(
        self,
        tenant_id: str,
        key: str,
        frame: pd.DataFrame,
        project_id: str | None = None,
    ) -> None:
        scoped_key = self.validate_and_scope_key(tenant_id, key, project_id)
        self._objects[scoped_key] = frame.copy()

    def read_spark(self, tenant_id: str, key: str, spark: Any, project_id: str | None = None) -> Any:
        frame = self.read(tenant_id, key, project_id)
        return spark.createDataFrame(frame)

    def write_spark(
        self,
        tenant_id: str,
        key: str,
        df: Any,
        project_id: str | None = None,
        mode: str = "overwrite",
    ) -> None:
        # Collect to pandas for in-memory storage (used in testing/dev)
        frame = df.toPandas()
        self.write(tenant_id, key, frame, project_id)


class ObjectStorageConnector(BaseConnector):
    """Scoped Object Storage connector (S3 / GCS / Azure Blob / MinIO / Local Lakehouse).
    
    All reads and writes are rooted in a secure base directory or object storage bucket
    prefixed with the tenant ID.
    """

    def __init__(self, base_uri: str) -> None:
        self.base_uri = base_uri.rstrip("/")

    def _resolved_path(self, tenant_id: str, key: str, project_id: str | None = None) -> str:
        scoped_key = self.validate_and_scope_key(tenant_id, key, project_id)
        return f"{self.base_uri}/{scoped_key}"

    def read(self, tenant_id: str, key: str, project_id: str | None = None) -> pd.DataFrame:
        path = self._resolved_path(tenant_id, key, project_id)
        if path.endswith(".csv"):
            return pd.read_csv(path)
        if path.endswith(".parquet") or path.endswith(".pq"):
            return pd.read_parquet(path)
        if path.endswith(".json"):
            return pd.read_json(path)
        # Default to parquet or csv
        return pd.read_csv(path)

    def write(
        self,
        tenant_id: str,
        key: str,
        frame: pd.DataFrame,
        project_id: str | None = None,
    ) -> None:
        path = self._resolved_path(tenant_id, key, project_id)
        # Ensure parent directory exists if using local filesystem URI
        if not (path.startswith("s3://") or path.startswith("gs://") or path.startswith("abfss://")):
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        if path.endswith(".csv"):
            frame.to_csv(path, index=False)
        elif path.endswith(".parquet") or path.endswith(".pq"):
            frame.to_parquet(path, index=False)
        elif path.endswith(".json"):
            frame.to_json(path, orient="records")
        else:
            frame.to_csv(path, index=False)

    def read_spark(self, tenant_id: str, key: str, spark: Any, project_id: str | None = None) -> Any:
        path = self._resolved_path(tenant_id, key, project_id)
        if path.endswith(".csv"):
            return spark.read.option("header", "true").option("inferSchema", "true").csv(path)
        if path.endswith(".parquet") or path.endswith(".pq"):
            return spark.read.parquet(path)
        if path.endswith(".json"):
            return spark.read.json(path)
        return spark.read.load(path)

    def write_spark(
        self,
        tenant_id: str,
        key: str,
        df: Any,
        project_id: str | None = None,
        mode: str = "overwrite",
    ) -> None:
        path = self._resolved_path(tenant_id, key, project_id)
        writer = df.write.mode(mode)
        if path.endswith(".csv"):
            writer.option("header", "true").csv(path)
        elif path.endswith(".parquet") or path.endswith(".pq"):
            writer.parquet(path)
        elif path.endswith(".json"):
            writer.json(path)
        else:
            writer.save(path)

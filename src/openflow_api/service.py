from __future__ import annotations

from typing import Any

from openflow_engine.connectors import BaseConnector, InMemoryConnector, ObjectStorageConnector
from openflow_engine.errors import CycleError, PipelineExecutionError
from openflow_engine.nodes import FilterNode, InputNode, JoinNode, Node, OutputNode, TransformNode, UnionNode
from openflow_engine.pyspark_engine import PySparkPipelineRunner, SparkConnectionConfig
from openflow_engine.runner import Edge, PipelineRunner, RunResult
from .deps import TenantContext


class PipelineService:
    """Instantiates and executes pipelines with strict tenant isolation."""

    def __init__(self, default_connector: BaseConnector | None = None) -> None:
        self.default_connector = default_connector or InMemoryConnector()

    def build_runner(
        self,
        graph_dict: dict[str, Any],
        tenant: TenantContext,
        engine: str = "pandas",
        connector: BaseConnector | None = None,
        spark_config: SparkConnectionConfig | None = None,
    ) -> PipelineRunner | PySparkPipelineRunner:
        active_connector = connector or self.default_connector
        nodes: dict[str, Node] = {}
        raw_nodes = graph_dict.get("nodes", [])

        for node_def in raw_nodes:
            nid = node_def["id"]
            data = node_def.get("data", {})
            ntype = data.get("type") or node_def.get("type")
            config = data.get("config", {})

            if ntype in ("input", "input_csv", "input_parquet"):
                # Enforce tenant-scoped object key
                key = config.get("key") or config.get("path", "")
                nodes[nid] = InputNode(
                    connector=active_connector,
                    tenant_id=tenant.org_id,
                    project_id=tenant.project_id,
                    key=key,
                )
            elif ntype == "filter":
                condition = config.get("condition", "")
                nodes[nid] = FilterNode(condition=condition)
            elif ntype == "join":
                on = config.get("on", [])
                how = config.get("how", "inner")
                nodes[nid] = JoinNode(on=on, how=how)
            elif ntype == "union":
                nodes[nid] = UnionNode()
            elif ntype == "transform":
                nodes[nid] = TransformNode(
                    select_columns=config.get("select_columns"),
                    rename_columns=config.get("rename_columns"),
                    drop_columns=config.get("drop_columns"),
                )
            elif ntype in ("output", "output_csv", "output_parquet"):
                key = config.get("key") or config.get("path", "")
                nodes[nid] = OutputNode(
                    connector=active_connector,
                    tenant_id=tenant.org_id,
                    project_id=tenant.project_id,
                    key=key,
                )
            else:
                raise ValueError(f"unsupported node type: {ntype!r} for node {nid!r}")

        edges: list[Edge] = []
        for edge_def in graph_dict.get("edges", []):
            edges.append(
                Edge(
                    source=edge_def["source"],
                    target=edge_def["target"],
                    target_port=edge_def.get("target_port") or edge_def.get("targetHandle"),
                )
            )

        if engine == "spark":
            return PySparkPipelineRunner(
                nodes=nodes,
                edges=edges,
                spark_config=spark_config,
            )
        return PipelineRunner(nodes=nodes, edges=edges)

    def execute_pipeline(
        self,
        graph_dict: dict[str, Any],
        tenant: TenantContext,
        engine: str = "pandas",
        connector: BaseConnector | None = None,
    ) -> RunResult:
        runner = self.build_runner(graph_dict, tenant, engine=engine, connector=connector)
        return runner.run()

    def preview_node(
        self,
        graph_dict: dict[str, Any],
        tenant: TenantContext,
        target_node_id: str,
        limit: int = 100,
        engine: str = "pandas",
        connector: BaseConnector | None = None,
    ) -> list[dict[str, Any]]:
        """Safely previews up to `limit` rows of a target node."""
        runner = self.build_runner(graph_dict, tenant, engine=engine, connector=connector)
        preview_df = runner.preview(target_node_id, limit=limit)
        return preview_df.to_dict(orient="records")  # type: ignore

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

from .errors import CycleError, PipelineExecutionError
from .nodes import Node


@dataclass
class NodeLog:
    node_id: str
    status: str
    duration_ms: float = 0.0
    rows: int | None = None
    error: str | None = None


@dataclass
class RunResult:
    outputs: dict[str, pd.DataFrame]
    logs: list[NodeLog] = field(default_factory=list)


@dataclass
class Edge:
    source: str
    target: str
    target_port: str | None = None


class PipelineRunner:
    """DAG execution engine supporting Kahn's topological sort, cycle detection,
    multi-input port routing, and detailed per-node telemetry.
    """

    def __init__(
        self,
        nodes: dict[str, Node],
        edges: Sequence[tuple[str, str] | tuple[str, str, str] | dict[str, Any] | Edge],
    ) -> None:
        self.nodes = nodes
        self.edges = self._normalize_edges(edges)
        self.parents = self._build_parent_map()
        self.order = self._build_order()

    def run(self) -> RunResult:
        """Executes the pipeline using the Pandas engine."""
        results: dict[str, pd.DataFrame] = {}
        logs: list[NodeLog] = []

        for node_id in self.order:
            node = self.nodes[node_id]
            incoming_edges = self.parents[node_id]

            # Route inputs by port or sequence
            inputs: list[pd.DataFrame] | dict[str, pd.DataFrame]
            if any(e.target_port is not None for e in incoming_edges):
                inputs = {
                    (e.target_port or f"input_{i}"): results[e.source]
                    for i, e in enumerate(incoming_edges)
                }
            else:
                inputs = [results[e.source] for e in incoming_edges]

            start_time = time.perf_counter()
            try:
                result = node.execute(inputs)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                row_count = len(result) if hasattr(result, "__len__") else None

                results[node_id] = result
                logs.append(
                    NodeLog(
                        node_id=node_id,
                        status="succeeded",
                        duration_ms=round(duration_ms, 2),
                        rows=row_count,
                    )
                )
            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                logs.append(
                    NodeLog(
                        node_id=node_id,
                        status="failed",
                        duration_ms=round(duration_ms, 2),
                        error=str(exc),
                    )
                )
                raise PipelineExecutionError(f"node {node_id!r} failed: {exc}", logs) from exc

        return RunResult(outputs=results, logs=logs)

    def run_spark(self, spark: Any) -> RunResult:
        """Executes the pipeline using the PySpark engine."""
        spark_dfs: dict[str, Any] = {}
        logs: list[NodeLog] = []
        final_pandas_outputs: dict[str, pd.DataFrame] = {}

        for node_id in self.order:
            node = self.nodes[node_id]
            incoming_edges = self.parents[node_id]

            if any(e.target_port is not None for e in incoming_edges):
                inputs = {
                    (e.target_port or f"input_{i}"): spark_dfs[e.source]
                    for i, e in enumerate(incoming_edges)
                }
            else:
                inputs = [spark_dfs[e.source] for e in incoming_edges]

            start_time = time.perf_counter()
            try:
                result_df = node.execute_spark(inputs, spark)
                spark_dfs[node_id] = result_df
                duration_ms = (time.perf_counter() - start_time) * 1000.0

                logs.append(
                    NodeLog(
                        node_id=node_id,
                        status="succeeded",
                        duration_ms=round(duration_ms, 2),
                    )
                )
            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                logs.append(
                    NodeLog(
                        node_id=node_id,
                        status="failed",
                        duration_ms=round(duration_ms, 2),
                        error=str(exc),
                    )
                )
                raise PipelineExecutionError(f"spark node {node_id!r} failed: {exc}", logs) from exc

        return RunResult(outputs=final_pandas_outputs, logs=logs)

    def preview(self, target_node_id: str, limit: int = 100) -> pd.DataFrame:
        """Safely executes only upstream dependencies of the target node and bounds output.
        
        Fixes A6 by bounding data size and stopping upstream once the preview target is reached.
        """
        if target_node_id not in self.nodes:
            raise ValueError(f"target node {target_node_id!r} not in pipeline")

        # Find all upstream nodes of target_node_id
        upstream: set[str] = set()
        stack = [target_node_id]
        while stack:
            curr = stack.pop()
            upstream.add(curr)
            for edge in self.parents[curr]:
                if edge.source not in upstream:
                    stack.append(edge.source)

        # Run topologically only for upstream nodes
        results: dict[str, pd.DataFrame] = {}
        for node_id in self.order:
            if node_id not in upstream:
                continue
            node = self.nodes[node_id]
            incoming = self.parents[node_id]
            if any(e.target_port is not None for e in incoming):
                inputs = {
                    (e.target_port or f"input_{i}"): results[e.source]
                    for i, e in enumerate(incoming)
                }
            else:
                inputs = [results[e.source] for e in incoming]

            df = node.execute(inputs)
            results[node_id] = df
            if node_id == target_node_id:
                return df.head(limit)

        return results[target_node_id].head(limit)

    def _normalize_edges(
        self,
        edges: Sequence[tuple[str, str] | tuple[str, str, str] | dict[str, Any] | Edge],
    ) -> list[Edge]:
        normalized: list[Edge] = []
        for e in edges:
            if isinstance(e, Edge):
                normalized.append(e)
            elif isinstance(e, dict):
                normalized.append(
                    Edge(
                        source=e["source"],
                        target=e["target"],
                        target_port=e.get("target_port") or e.get("targetHandle"),
                    )
                )
            elif len(e) == 2:
                normalized.append(Edge(source=e[0], target=e[1]))
            elif len(e) == 3:
                normalized.append(Edge(source=e[0], target=e[1], target_port=e[2]))
            else:
                raise ValueError(f"invalid edge format: {e!r}")
        return normalized

    def _build_parent_map(self) -> dict[str, list[Edge]]:
        parents: dict[str, list[Edge]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ValueError(f"edge references unknown node: {edge.source!r} -> {edge.target!r}")
            parents[edge.target].append(edge)
        return parents

    def _build_order(self) -> list[str]:
        children: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        indegree: dict[str, int] = {node_id: len(parents) for node_id, parents in self.parents.items()}

        for edge in self.edges:
            children[edge.source].append(edge.target)

        ready = [node_id for node_id, deg in indegree.items() if deg == 0]
        order: list[str] = []

        while ready:
            node_id = ready.pop(0)
            order.append(node_id)
            for child_id in children[node_id]:
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    ready.append(child_id)

        if len(order) != len(self.nodes):
            raise CycleError("pipeline graph contains a cycle")

        return order

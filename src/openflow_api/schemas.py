from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from openflow_engine.errors import CycleError
from openflow_engine.runner import PipelineRunner


class NodeData(BaseModel):
    label: str | None = None
    type: str  # input, filter, join, union, transform, output
    config: dict[str, Any] = Field(default_factory=dict)


class GraphNode(BaseModel):
    id: str
    type: str | None = None
    data: NodeData
    position: dict[str, float] | None = None


class GraphEdge(BaseModel):
    id: str | None = None
    source: str
    target: str
    sourceHandle: str | None = None
    targetHandle: str | None = None
    target_port: str | None = None


class PipelineGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]

    def validate_acyclic(self) -> None:
        """Validates that the graph is a valid DAG and contains no cycles (R2)."""
        node_ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in node_ids:
                raise ValueError(f"edge references unknown source node: {e.source}")
            if e.target not in node_ids:
                raise ValueError(f"edge references unknown target node: {e.target}")

        # Build dummy runner to trigger Kahn's cycle detection
        dummy_nodes = {n.id: None for n in self.nodes}  # type: ignore
        edge_tuples = [(e.source, e.target) for e in self.edges]

        # Use cycle check logic
        indegree = {nid: 0 for nid in dummy_nodes}
        children: dict[str, list[str]] = {nid: [] for nid in dummy_nodes}
        for src, tgt in edge_tuples:
            indegree[tgt] += 1
            children[src].append(tgt)

        ready = [nid for nid, deg in indegree.items() if deg == 0]
        visited_count = 0
        while ready:
            curr = ready.pop(0)
            visited_count += 1
            for child in children[curr]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)

        if visited_count != len(self.nodes):
            raise CycleError("pipeline graph contains a cycle")


class PipelineCreate(BaseModel):
    name: str
    description: str | None = None
    graph: PipelineGraph


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    graph: PipelineGraph | None = None


class PipelineResponse(BaseModel):
    id: str
    org_id: str
    project_id: str
    name: str
    description: str | None = None
    graph_json: dict[str, Any]
    version: int


class RunPipelineRequest(BaseModel):
    engine: Literal["pandas", "spark"] = "pandas"


class PreviewRequest(BaseModel):
    node_id: str
    limit: int = 100
    engine: Literal["pandas", "spark"] = "pandas"


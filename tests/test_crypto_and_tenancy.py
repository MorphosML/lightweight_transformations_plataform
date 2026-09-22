import pytest
from openflow_api.crypto import SecretsManager
from openflow_api.deps import TenantContext, get_tenant_context
from openflow_api.schemas import GraphEdge, GraphNode, NodeData, PipelineGraph
from openflow_engine.errors import CycleError


def test_secrets_manager_roundtrip() -> None:
    key = SecretsManager.generate_new_key()
    manager = SecretsManager(primary_key=key)

    secret = "my-super-secret-s3-token-12345"
    encrypted = manager.encrypt(secret)

    assert encrypted != secret
    assert manager.decrypt(encrypted) == secret


def test_tenant_context_enforcement() -> None:
    # Valid headers
    ctx = get_tenant_context(x_org_id="org-123", x_project_id="proj-456")
    assert ctx.org_id == "org-123"
    assert ctx.project_id == "proj-456"

    # Missing org header raises 401
    with pytest.raises(Exception) as exc:
        get_tenant_context(x_org_id="", x_project_id="proj-456")
    assert "401" in str(exc.value) or "Missing required tenant header" in str(exc.value)

    # Missing project header raises 400
    with pytest.raises(Exception) as exc:
        get_tenant_context(x_org_id="org-123", x_project_id="")
    assert "400" in str(exc.value) or "Missing required project header" in str(exc.value)


def test_pipeline_graph_validates_acyclic_on_schema() -> None:
    cyclic_graph = PipelineGraph(
        nodes=[
            GraphNode(id="A", data=NodeData(type="filter")),
            GraphNode(id="B", data=NodeData(type="filter")),
        ],
        edges=[
            GraphEdge(source="A", target="B"),
            GraphEdge(source="B", target="A"),
        ],
    )

    with pytest.raises(CycleError):
        cyclic_graph.validate_acyclic()

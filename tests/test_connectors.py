import pandas as pd
import pytest

from openflow_engine import InMemoryConnector


def test_connector_isolates_tenant_keys() -> None:
    connector = InMemoryConnector()
    connector.write("tenant-a", "result.csv", pd.DataFrame({"value": [1]}))

    assert connector.read("tenant-a", "result.csv")["value"].tolist() == [1]
    with pytest.raises(KeyError):
        connector.read("tenant-b", "result.csv")


def test_connector_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        InMemoryConnector().write("tenant-a", "../other.csv", pd.DataFrame())

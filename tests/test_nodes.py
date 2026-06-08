import pytest
from scripts.brandkit.nodes import find_node_by_title, NodeNotFound

WF = {
    "1": {"class_type": "KSampler", "inputs": {"seed": 0}, "_meta": {"title": "brand:sampler"}},
    "2": {"class_type": "SaveImage", "inputs": {}, "_meta": {"title": "brand:save"}},
    "3": {"class_type": "VAEDecode", "inputs": {}},  # no title
}

def test_find_returns_id_and_node():
    nid, node = find_node_by_title(WF, "brand:sampler")
    assert nid == "1" and node["class_type"] == "KSampler"

def test_missing_title_raises_clear_error():
    with pytest.raises(NodeNotFound) as e:
        find_node_by_title(WF, "brand:nope")
    assert "brand:nope" in str(e.value)

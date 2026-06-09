from pathlib import Path
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.threed import build
from scripts.brandkit.nodes import find_node_by_title

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_3d_fills_image_seed_octree_model():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="", negative="", seed=42, from_image="rover.png", octree=128)
    assert find_node_by_title(wf, "brand:load_image")[1]["inputs"]["image"] == "rover.png"
    assert find_node_by_title(wf, "brand:sampler")[1]["inputs"]["seed"] == 42
    assert find_node_by_title(wf, "brand:decode")[1]["inputs"]["octree_resolution"] == 128
    assert find_node_by_title(wf, "brand:ckpt")[1]["inputs"]["ckpt_name"] == "hunyuan_3d_v2.1.safetensors"

def test_3d_uses_manifest_steps_cfg_and_default_octree():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="", negative="", seed=1, from_image="r.png")
    s = find_node_by_title(wf, "brand:sampler")[1]["inputs"]
    assert s["steps"] == 30 and s["cfg"] == 5.0
    assert find_node_by_title(wf, "brand:decode")[1]["inputs"]["octree_resolution"] == 256

def test_3d_requires_from_image():
    import pytest
    m = load_manifest(FIX)
    with pytest.raises(ValueError):
        build(ROOT, m, positive="", negative="", seed=1)

def test_3d_model_override():
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="", negative="", seed=1, from_image="r.png", model="other3d.safetensors")
    assert find_node_by_title(wf, "brand:ckpt")[1]["inputs"]["ckpt_name"] == "other3d.safetensors"

def test_resolved_model_matches_graph_ckpt():
    # B6: the resolver is the single source of truth — equal to what build() wrote
    from scripts.brandkit.threed import resolved_model
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="", negative="", seed=1, from_image="r.png")
    assert resolved_model(m) == find_node_by_title(wf, "brand:ckpt")[1]["inputs"]["ckpt_name"]
    wf2 = build(ROOT, m, positive="", negative="", seed=1, from_image="r.png", model="x3d.safetensors")
    assert resolved_model(m, "x3d.safetensors") == "x3d.safetensors" == \
        find_node_by_title(wf2, "brand:ckpt")[1]["inputs"]["ckpt_name"]

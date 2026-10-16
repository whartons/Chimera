"""3D: native TRELLIS.2 (the default, textured) and Pixal3D share one ComfyUI 0.40 graph (background
cut-out, structure -> shape -> texture stages, remesh + UV unwrap + PBR bake); Hunyuan3D 2.1 stays as the
fast shape-only option."""
import json
from pathlib import Path
from scripts.brandkit import threed
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.nodes import find_node_by_title

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"
SAMPLERS = ("brand:sampler_structure", "brand:sampler_shape", "brand:sampler_upsample", "brand:sampler_texture")


def _in(wf, title):
    return find_node_by_title(wf, title)[1]["inputs"]


def _upstream(wf, nid):
    """Every node id that feeds `nid`, transitively."""
    seen, stack = set(), [nid]
    while stack:
        for v in wf[stack.pop()]["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in seen:
                seen.add(v[0])
                stack.append(v[0])
    return seen


def test_trellis2_is_the_default_and_builds_the_native_textured_graph():
    m = load_manifest(FIX)
    assert threed.resolved_model(m) == threed.TRELLIS2_MODEL == "trellis_2_int8_convrot.safetensors"
    wf = threed.build(ROOT, m, seed=100, from_image="rover.png")
    assert _in(wf, "brand:load_image")["image"] == "rover.png"
    assert _in(wf, "brand:use_trellis2")["value"] is True
    assert _in(wf, "brand:trellis2_model")["unet_name"] == threed.TRELLIS2_MODEL
    assert [_in(wf, t)["seed"] for t in SAMPLERS] == [100, 101, 102, 103]
    assert _in(wf, "brand:remove_background")["switch"] is True
    save_id, save = find_node_by_title(wf, "brand:save")
    assert save["class_type"] == "Save3DAdvanced"
    kinds = {wf[n]["class_type"] for n in _upstream(wf, save_id)}
    assert {"ApplyTextureToMesh", "BakeTextureFromVoxel", "UnwrapMesh", "RemoveBackground"} <= kinds


def test_pixal3d_flips_the_switch_and_loads_its_model():
    wf = threed.build(ROOT, load_manifest(FIX), seed=1, from_image="r.png", model="pixal3d")
    assert _in(wf, "brand:use_trellis2")["value"] is False
    assert _in(wf, "brand:pixal3d_model")["unet_name"] == threed.PIXAL3D_MODEL


def test_hunyuan21_keeps_the_shape_only_graph():
    wf = threed.build(ROOT, load_manifest(FIX), seed=7, from_image="r.png", model="hunyuan21", octree=128)
    assert _in(wf, "brand:ckpt")["ckpt_name"] == threed.HUNYUAN3D_MODEL
    assert _in(wf, "brand:decode")["octree_resolution"] == 128


def test_short_names_resolve_to_file_names_so_sidecars_record_the_file(tmp_path):
    m = load_manifest(FIX)
    assert threed.resolved_model(m, "TRELLIS2") == threed.TRELLIS2_MODEL
    assert threed.resolved_model(m, "pixal3d") == threed.PIXAL3D_MODEL
    assert threed.resolved_model(m, "hunyuan21") == threed.HUNYUAN3D_MODEL
    assert threed.resolved_model(m, "custom3d.safetensors") == "custom3d.safetensors"
    p = tmp_path / "b.yaml"
    p.write_text("name: B\nthreed: { model: pixal3d }\n")      # a brand may pin a short name too
    assert threed.resolved_model(load_manifest(p)) == threed.PIXAL3D_MODEL


def test_which_models_come_out_textured():
    assert threed.is_textured(threed.TRELLIS2_MODEL) and threed.is_textured(threed.PIXAL3D_MODEL)
    assert not threed.is_textured(threed.HUNYUAN3D_MODEL)
    assert not threed.is_textured("custom3d.safetensors")


def test_the_native_template_carries_no_preview_nodes():
    # the official graph's previews were rewired out: in ComfyUI 0.40 a PreviewImage passes its input
    # through, so the bake chain used them as sources; the template wires the real sources instead
    wf = json.loads((ROOT / "workflows" / "templates" / "brand-3d-trellis2.json").read_text(encoding="utf-8"))
    assert not [n for n in wf.values() if "Preview" in n["class_type"]]

from pathlib import Path
import pytest
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.workflow import build_workflow

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def test_txt2img_injects_prompt_size_seed_and_model():
    m = load_manifest(FIX)
    wf = build_workflow(ROOT, m, mode="txt2img", positive="hello world", negative="bad", seed=123)
    assert wf["4"]["inputs"]["text"] == "hello world"
    assert wf["6"]["inputs"]["text"] == "bad"
    assert wf["7"]["inputs"]["width"] == 768 and wf["7"]["inputs"]["height"] == 512
    assert wf["8"]["inputs"]["seed"] == 123 and wf["8"]["inputs"]["steps"] == 12
    assert wf["5"]["inputs"]["guidance"] == 3.0
    assert wf["1"]["inputs"]["unet_name"] == "flux2_dev_fp8mixed.safetensors"

def test_lora_injected_when_set():
    m = load_manifest(FIX)  # lora.file = "lora/test.safetensors"
    wf = build_workflow(ROOT, m, mode="txt2img", positive="x", negative="", seed=1)
    lora_nodes = [n for n in wf.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert len(lora_nodes) == 1
    ln = lora_nodes[0]
    assert ln["inputs"]["lora_name"].endswith("test.safetensors")
    assert ln["inputs"]["strength_model"] == 0.7
    # sampler.model now points at the LoRA node (id 99), not UNETLoader (id 1)
    assert wf["8"]["inputs"]["model"] == ["99", 0]

def test_no_lora_node_when_unset(tmp_path):
    p = tmp_path / "b.yaml"; p.write_text("name: B\nstyle: x\n")
    m = load_manifest(p)
    wf = build_workflow(ROOT, m, mode="txt2img", positive="x", negative="", seed=1)
    assert not any(n["class_type"] == "LoraLoaderModelOnly" for n in wf.values())
    assert wf["8"]["inputs"]["model"] == ["1", 0]

def test_logo_overlay_sets_image_scale_and_position():
    m = load_manifest(FIX)  # logo bottom-right, scale 0.2, margin 0.05
    wf = build_workflow(ROOT, m, mode="logo", positive="scene", negative="", seed=1,
                        logo_image="primary.png")
    assert wf["11"]["inputs"]["image"] == "primary.png"
    # image AND mask are scaled by the same factor, and the mask is inverted to a
    # source-alpha (LoadImage gives 1-alpha) so only the logo pixels composite.
    assert wf["12"]["inputs"]["scale_by"] == 0.2
    assert wf["18"]["inputs"]["scale_by"] == 0.2
    assert wf["16"]["class_type"] == "InvertMask"
    assert wf["13"]["inputs"]["mask"] == ["19", 0]
    # bottom-right => positive x and y offsets exist (filled by filler)
    assert isinstance(wf["13"]["inputs"]["x"], int) and isinstance(wf["13"]["inputs"]["y"], int)

def test_logo_overlay_uses_exact_px_for_placement():
    m = load_manifest(FIX)  # canvas 768x512, scale 0.2, margin 0.05, bottom-right
    wf = build_workflow(ROOT, m, mode="logo", positive="x", negative="", seed=1,
                        logo_image="primary.png", logo_px=(100, 100))
    # bottom-right: x = 768 - 100 - int(768*0.05); y = 512 - 100 - int(512*0.05)
    assert wf["13"]["inputs"]["x"] == 768 - 100 - 38
    assert wf["13"]["inputs"]["y"] == 512 - 100 - 25

def test_product_mockup_sets_image():
    m = load_manifest(FIX)
    wf = build_workflow(ROOT, m, mode="product", positive="on a desk", negative="", seed=1,
                        product_image="rig.png")
    assert wf["14"]["inputs"]["image"] == "rig.png"
    assert wf["8"]["inputs"]["latent_image"] == ["15", 0]

def test_product_mode_requires_image():
    m = load_manifest(FIX)
    with pytest.raises(ValueError):
        build_workflow(ROOT, m, mode="product", positive="x", negative="", seed=1)

def test_logo_top_left_and_center_placement(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("name: B\nstyle: x\n"
                 "defaults: { width: 1000, height: 800 }\n"
                 "logo: { position: top-left, scale: 0.2, margin: 0.05 }\n")
    m = load_manifest(p)
    wf = build_workflow(ROOT, m, mode="logo", positive="x", negative="", seed=1,
                        logo_image="l.png", logo_px=(100, 100))
    # top-left => x=margin_px, y=margin_px
    assert wf["13"]["inputs"]["x"] == int(1000 * 0.05)
    assert wf["13"]["inputs"]["y"] == int(800 * 0.05)
    m.logo.position = "center"
    wf = build_workflow(ROOT, m, mode="logo", positive="x", negative="", seed=1,
                        logo_image="l.png", logo_px=(100, 100))
    assert wf["13"]["inputs"]["x"] == (1000 - 100) // 2
    assert wf["13"]["inputs"]["y"] == (800 - 100) // 2

def test_flux_model_override_reaches_unet_and_matches_sidecar(tmp_path):
    # a Z-Image-default brand overridden to a FLUX model: the FLUX checkpoint must land in
    # brand:unet (not the brand default), and equal what the sidecar records via resolve_image_model
    # — i.e. graph and sidecar share one resolved value (no FLUX-override drift).
    from scripts.brandkit.workflow import build, resolve_image_model
    from scripts.brandkit.nodes import find_node_by_title
    p = tmp_path / "b.yaml"; p.write_text("name: B\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\n")
    m = load_manifest(p)
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img",
               model="flux2_dev_fp8mixed.safetensors")
    unet = find_node_by_title(wf, "brand:unet")[1]["inputs"]["unet_name"]
    assert unet == "flux2_dev_fp8mixed.safetensors"
    assert unet == resolve_image_model("txt2img", None, "flux2_dev_fp8mixed.safetensors")


def test_build_contract_txt2img():
    from scripts.brandkit.workflow import build
    from scripts.brandkit.nodes import find_node_by_title
    m = load_manifest(FIX)
    wf = build(ROOT, m, positive="hello", negative="bad", seed=5, watermark=False, mode="txt2img")
    _, sampler = find_node_by_title(wf, "brand:sampler")
    assert sampler["inputs"]["seed"] == 5
    _, pos = find_node_by_title(wf, "brand:positive")
    assert pos["inputs"]["text"] == "hello"

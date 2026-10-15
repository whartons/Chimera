"""image --upscale: SeedVR2 7B (one-step diffusion upscaler) is the default; an ESRGAN-style model name
(e.g. 4x-UltraSharp.pth) selects the classic ESRGAN pass. Both splice in just before brand:save."""
from pathlib import Path
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.nodes import find_node_by_title
from scripts.brandkit.workflow import build, resolved_upscale_model, DEFAULT_UPSCALE_MODEL

ROOT = Path(__file__).resolve().parents[1]


def _m(tmp, model="z_image_turbo_nvfp4.safetensors", extra=""):
    p = tmp / "b.yaml"
    p.write_text(f"name: B\ndefaults: {{ model: {model}, width: 1024, height: 1024 }}\n{extra}")
    return load_manifest(p)


def _node(wf, title):
    return find_node_by_title(wf, title)


def test_seedvr2_is_the_default_upscaler():
    assert DEFAULT_UPSCALE_MODEL == "seedvr2_7b_int8_convrot.safetensors"


def test_default_upscale_splices_the_seedvr2_chain_before_save(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="x", negative="", seed=42, mode="txt2img", upscale=True)
    decode_id, _ = _node(wf, "brand:decode")
    unet_id, unet = _node(wf, "brand:upscale_model")
    assert unet["class_type"] == "UNETLoader" and unet["inputs"]["unet_name"] == DEFAULT_UPSCALE_MODEL
    vae_id, vae = _node(wf, "brand:upscale_vae")
    assert vae["inputs"]["vae_name"] == "seedvr2_ema_vae_fp16.safetensors"
    resize_id, resize = _node(wf, "brand:upscale_resize")
    assert resize["inputs"]["input"] == [decode_id, 0]           # takes over what fed save
    assert resize["inputs"]["resize_type"] == "scale by multiplier" and resize["inputs"]["resize_type.multiplier"] == 4
    s = _node(wf, "brand:upscale_sampler")[1]["inputs"]
    assert s["steps"] == 1 and s["cfg"] == 1.0 and s["seed"] == 42 and s["model"] == [unet_id, 0]
    cond = s["positive"][0]
    assert s["positive"] == [cond, 0] and s["negative"] == [cond, 1]
    assert wf[cond]["class_type"] == "SeedVR2Conditioning" and wf[cond]["inputs"]["model"] == [unet_id, 0]
    post_id, post = _node(wf, "brand:upscale")
    assert post["class_type"] == "SeedVR2PostProcessing"
    assert post["inputs"]["original_resized_images"] == [resize_id, 0]
    assert _node(wf, "brand:save")[1]["inputs"]["images"] == [post_id, 0]
    tiled = [n for n in wf.values() if n["class_type"] in ("VAEEncodeTiled", "VAEDecodeTiled")]
    assert len(tiled) == 2 and all(n["inputs"]["vae"] == [vae_id, 0] for n in tiled)


def test_an_esrgan_model_name_selects_the_esrgan_pass(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="x", negative="", seed=1, mode="txt2img", upscale=True,
               upscale_model="4x-UltraSharp.pth")
    loader = _node(wf, "brand:upscale_model")[1]
    assert loader["class_type"] == "UpscaleModelLoader" and loader["inputs"]["model_name"] == "4x-UltraSharp.pth"
    assert not [n for n in wf.values() if n["class_type"].startswith("SeedVR2")]
    assert _node(wf, "brand:save")[1]["inputs"]["images"] == ["81", 0]


def test_seedvr2_upscales_the_watermarked_image(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="x", negative="", seed=1, mode="txt2img", upscale=True,
               watermark=True, watermark_logo="primary.png", logo_px=(120, 120))
    comp_id, _ = _node(wf, "brand:watermark_composite")
    assert _node(wf, "brand:upscale_resize")[1]["inputs"]["input"] == [comp_id, 0]


def test_seedvr2_splices_into_qwen_product_and_logo_graphs(tmp_path):
    m = _m(tmp_path, model="qwen_image_2.1_int8_convrot.safetensors")
    for mode, asset in (("product", "rover.png"), ("logo", "primary.png")):
        wf = build(ROOT, m, positive="x", negative="", seed=1, mode=mode, asset=asset, upscale=True,
                   logo_px=(100, 100))
        post_id, _ = _node(wf, "brand:upscale")
        assert _node(wf, "brand:save")[1]["inputs"]["images"] == [post_id, 0]


def test_a_brand_can_pin_its_upscaler(tmp_path):
    assert resolved_upscale_model(_m(tmp_path)) == DEFAULT_UPSCALE_MODEL
    p = tmp_path / "pinned.yaml"
    p.write_text("name: P\ndefaults: { model: z_image_turbo_nvfp4.safetensors, upscale_model: 4x-UltraSharp.pth }\n")
    assert resolved_upscale_model(load_manifest(p)) == "4x-UltraSharp.pth"

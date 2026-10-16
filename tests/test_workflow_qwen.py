"""Qwen-Image-2.1 family (the default image backend): txt2img, logo overlay, and product as a
reference-image edit of the product photo; relight still resolves to FLUX.2."""
from pathlib import Path
from scripts.brandkit.manifest import load_manifest, default_manifest
from scripts.brandkit.workflow import build, resolve_image_model, needs_free_before
from scripts.brandkit.nodes import find_node_by_title
from scripts.brandkit.sidecar import graph_prompts

ROOT = Path(__file__).resolve().parents[1]
QWEN = "qwen_image_2.1_int8_convrot.safetensors"


def _m(tmp, model=QWEN, extra=""):
    p = tmp / "b.yaml"
    p.write_text(f"name: B\ndefaults: {{ model: {model}, width: 1216, height: 832, steps: 99, guidance: 7 }}\n"
                 + extra)
    return load_manifest(p)


def _inputs(wf, title):
    return find_node_by_title(wf, title)[1]["inputs"]


def _is_qwen(wf):
    return find_node_by_title(wf, "brand:positive")[1]["class_type"] == "TextEncodeQwenImage21"


def test_qwen_txt2img_fills_prompts_seed_size_and_its_validated_sampler(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="a rover", negative="blurry", seed=11, mode="txt2img")
    assert _inputs(wf, "brand:unet")["unet_name"] == QWEN
    enc_id, enc = find_node_by_title(wf, "brand:positive")
    assert enc["inputs"]["prompt"] == "a rover" and enc["inputs"]["negative_prompt"] == "blurry"
    s = _inputs(wf, "brand:sampler")
    # 25 steps / CFG 1 are the validated Qwen-Image-2.1 settings; a brand's FLUX steps/guidance don't apply
    assert s["seed"] == 11 and s["steps"] == 25 and s["cfg"] == 1.0
    assert s["positive"] == [enc_id, 0] and s["negative"] == [enc_id, 1]
    assert (_inputs(wf, "brand:latent")["width"], _inputs(wf, "brand:latent")["height"]) == (1216, 832)


def test_qwen_logo_overlay_composites_the_logo(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="bg", negative="", seed=1, mode="logo", asset="primary.png",
               logo_px=(120, 120))
    assert _is_qwen(wf)
    assert _inputs(wf, "brand:logo_load")["image"] == "primary.png"
    assert _inputs(wf, "brand:save")["images"][0] == find_node_by_title(wf, "brand:logo_composite")[0]


def test_qwen_product_is_a_reference_edit_of_the_product_photo(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="hero shot", negative="", seed=3, mode="product", asset="rover.png")
    load_id, load = find_node_by_title(wf, "brand:product_load")
    assert load["inputs"]["image"] == "rover.png"
    vae_id, _ = find_node_by_title(wf, "brand:vae")
    enc = _inputs(wf, "brand:positive")
    assert enc["images.image_1"] == [load_id, 0] and enc["vae"] == [vae_id, 0]
    lat_id, _ = find_node_by_title(wf, "brand:latent")   # a fresh latent at the brand size, not img2img
    assert _inputs(wf, "brand:sampler")["latent_image"] == [lat_id, 0]


def test_qwen_product_watermark_ignores_the_product_photo_size(tmp_path):
    # generate.py passes the product photo's native size as the canvas (right for the img2img
    # families); a Qwen edit renders at the brand size, so the watermark must place on that instead.
    m = _m(tmp_path)
    kw = dict(positive="x", negative="", seed=1, mode="product", asset="rover.png", watermark=True,
              watermark_logo="primary.png", logo_px=(100, 100))
    with_photo = build(ROOT, m, canvas=(4000, 3000), **kw)
    brand_size = build(ROOT, m, **kw)
    pos = lambda wf: (_inputs(wf, "brand:watermark_composite")["x"], _inputs(wf, "brand:watermark_composite")["y"])
    assert pos(with_photo) == pos(brand_size)


def test_qwen_relight_still_resolves_to_flux2_and_qwen_needs_no_free_first():
    assert resolve_image_model("relight", None, QWEN) == "flux2_dev_fp8mixed.safetensors"
    assert resolve_image_model("txt2img", None, QWEN) == QWEN
    assert needs_free_before("txt2img", None, QWEN) is False


def test_qwen_lora_splices_between_the_unet_and_the_cache(tmp_path):
    wf = build(ROOT, _m(tmp_path, extra="lora: { file: lora/brand_q.safetensors, strength: 0.7 }\n"),
               positive="x", negative="", seed=1, mode="txt2img")
    unet_id, _ = find_node_by_title(wf, "brand:unet")
    assert _inputs(wf, "brand:lora")["model"] == [unet_id, 0]
    assert _inputs(wf, "brand:model_cache")["model"] == ["99", 0]


def test_qwen_watermark_then_upscale_splice_like_the_other_families(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="x", negative="", seed=1, mode="txt2img", watermark=True,
               watermark_logo="primary.png", logo_px=(120, 120), upscale=True)
    assert _is_qwen(wf)
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    assert _inputs(wf, "brand:upscale_resize")["input"] == [cid, 0]      # SeedVR2 (the default upscaler)
    assert _inputs(wf, "brand:save")["images"] == [find_node_by_title(wf, "brand:upscale")[0], 0]


def test_the_sidecar_records_the_qwen_prompt_and_negative(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="a rover", negative="blurry", seed=1, mode="txt2img")
    assert _is_qwen(wf) and graph_prompts(wf, "image", "txt2img") == ("a rover", "blurry")


def test_qwen_is_the_default_for_brandless_runs_new_brands_and_unpinned_brands(tmp_path):
    assert default_manifest().defaults.model == QWEN
    assert load_manifest(ROOT / "brands" / "_template" / "brand.yaml").defaults.model == QWEN
    p = tmp_path / "b.yaml"
    p.write_text("name: Unpinned\n")
    assert load_manifest(p).defaults.model == QWEN

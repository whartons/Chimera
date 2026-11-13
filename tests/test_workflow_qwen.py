"""Qwen-Image-2.1 family (the default image backend): txt2img, logo overlay, product as a reference-image edit
of the product photo, and relight as the same edit when --model asks for it (FLUX.2 stays the default relight)."""
from pathlib import Path
from scripts.brandkit.manifest import load_manifest, default_manifest
from scripts.brandkit.workflow import (DEFAULT_RELIGHT_MODEL, build, image_model, needs_free_before,
                                       resolve_image_model)
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


FLUX2 = "flux2_dev_fp8mixed.safetensors"


def test_relight_stays_flux2_by_default_and_runs_on_qwen_when_asked():
    # 2026-11-12 bake-off: the Qwen edit relights more faithfully and keeps more detail in ~18 GB; FLUX.2
    # does multi-light briefs better, so it stays the default and Qwen is the --model choice
    assert image_model("relight", None, QWEN) == DEFAULT_RELIGHT_MODEL   # a brand's default Qwen relights on FLUX.2
    assert image_model("relight", None, FLUX2) == FLUX2                   # a FLUX.2 brand relights on its own model
    assert image_model("relight", QWEN, FLUX2) == QWEN                    # --model qwen_image... picks the Qwen edit
    assert image_model("txt2img", None, QWEN) == QWEN
    assert resolve_image_model("relight", None, QWEN) == QWEN
    assert resolve_image_model("relight", None, "z_image_turbo_nvfp4.safetensors") == DEFAULT_RELIGHT_MODEL
    assert needs_free_before("txt2img", None, QWEN) is False and needs_free_before("relight", None, QWEN) is False


def test_qwen_relight_is_a_reference_edit_at_the_sources_size(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="blue hour", negative="", seed=5, mode="relight", asset="lamp.png",
               model=QWEN, canvas=(1662, 930))
    assert _is_qwen(wf) and _inputs(wf, "brand:unet")["unet_name"] == QWEN
    load_id, load = find_node_by_title(wf, "brand:relight_load")
    assert load["inputs"]["image"] == "lamp.png" and _inputs(wf, "brand:positive")["images.image_1"] == [load_id, 0]
    lat = _inputs(wf, "brand:latent")
    assert (lat["width"], lat["height"]) == (1648, 928)                # the source's frame, snapped to 16
    assert _inputs(wf, "brand:save")["filename_prefix"] == "brand_qwen_relight"


def test_a_brands_default_qwen_relights_on_flux2(tmp_path):
    wf = build(ROOT, _m(tmp_path), positive="blue hour", negative="", seed=5, mode="relight", asset="lamp.png")
    assert _inputs(wf, "brand:unet")["unet_name"] == DEFAULT_RELIGHT_MODEL and not _is_qwen(wf)


def test_qwen_relight_places_the_watermark_on_the_source_sized_frame(tmp_path):
    m = _m(tmp_path)
    kw = dict(positive="x", negative="", seed=1, mode="relight", asset="lamp.png", model=QWEN, watermark=True,
              watermark_logo="primary.png", logo_px=(100, 100))
    from scripts.brandkit.watermark import logo_geometry
    w = m.watermark
    at = lambda size: logo_geometry(size, logo_px=(100, 100), scale=w.scale, margin=w.margin, position=w.position)[:2]
    wide = _inputs(build(ROOT, m, canvas=(1670, 930), **kw), "brand:watermark_composite")
    assert (wide["x"], wide["y"]) == at((1664, 928))                    # the snapped source frame
    brand = _inputs(build(ROOT, m, **kw), "brand:watermark_composite")    # no readable size: the brand's
    assert (brand["x"], brand["y"]) == at((1216, 832))


def test_the_sidecar_records_the_relight_model_the_graph_loads():
    from argparse import Namespace
    from scripts.brandkit.replay import resolve_model_used
    m = default_manifest()
    ask = lambda model: Namespace(modality="image", mode="relight", variant=None, model=model)
    assert resolve_model_used(ask(None), m) == DEFAULT_RELIGHT_MODEL and resolve_model_used(ask(QWEN), m) == QWEN


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

from pathlib import Path
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.workflow import build
from scripts.brandkit.nodes import find_node_by_title

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "brand.yaml"

def _m(tmp, model):
    p = tmp / "b.yaml"
    p.write_text(f"name: B\ndefaults: {{ model: {model}, width: 1024, height: 1024, steps: 99, guidance: 7 }}\n")
    return load_manifest(p)

def test_zimage_family_txt2img_fills_positive_seed_size_turbo(tmp_path):
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="a rover", negative="ignored", seed=11, mode="txt2img")
    assert find_node_by_title(wf, "brand:unet")[1]["inputs"]["unet_name"] == "z_image_turbo_nvfp4.safetensors"
    assert find_node_by_title(wf, "brand:positive")[1]["inputs"]["text"] == "a rover"
    s = find_node_by_title(wf, "brand:sampler")[1]["inputs"]
    assert s["seed"] == 11 and s["steps"] == 8 and s["cfg"] == 1.0
    lat = find_node_by_title(wf, "brand:latent")[1]["inputs"]
    assert lat["width"] == 1024 and lat["height"] == 1024
    assert "text" not in find_node_by_title(wf, "brand:negative")[1]["inputs"]

def test_zimage_variant_base_switches_model_and_steps(tmp_path):
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img", variant="base")
    assert find_node_by_title(wf, "brand:unet")[1]["inputs"]["unet_name"] == "z_image_bf16.safetensors"
    s = find_node_by_title(wf, "brand:sampler")[1]["inputs"]
    assert s["steps"] == 25 and s["cfg"] == 4.0

def test_zimage_product_uses_base_model_even_with_turbo_default(tmp_path):
    # product img2img must use the BASE model + base settings regardless of the brand's
    # default (turbo) txt2img model — running the turbo checkpoint at base steps degrades output.
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="hero", negative="", seed=3, mode="product", asset="rover.png")
    assert find_node_by_title(wf, "brand:unet")[1]["inputs"]["unet_name"] == "z_image_bf16.safetensors"
    s = find_node_by_title(wf, "brand:sampler")[1]["inputs"]
    assert s["steps"] == 25 and s["cfg"] == 4.0

def test_zimage_product_is_img2img_with_encoded_latent(tmp_path):
    m = _m(tmp_path, "z_image_bf16.safetensors")
    wf = build(ROOT, m, positive="hero", negative="", seed=3, mode="product", asset="rover.png")
    assert find_node_by_title(wf, "brand:product_load")[1]["inputs"]["image"] == "rover.png"
    enc_id, _ = find_node_by_title(wf, "brand:product_encode")
    assert find_node_by_title(wf, "brand:sampler")[1]["inputs"]["latent_image"] == [enc_id, 0]

def test_zimage_logo_overlay_places_logo(tmp_path):
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="bg", negative="", seed=1, mode="logo", asset="primary.png",
               logo_px=(120, 120))
    assert find_node_by_title(wf, "brand:logo_load")[1]["inputs"]["image"] == "primary.png"
    assert find_node_by_title(wf, "brand:save")[1]["inputs"]["images"][0] == \
        find_node_by_title(wf, "brand:logo_composite")[0]

def test_resolve_image_model_reflects_variant_not_default():
    from scripts.brandkit.workflow import resolve_image_model
    # product always resolves to the base file even when the brand default is turbo
    assert resolve_image_model("product", None, "z_image_turbo_nvfp4.safetensors") == "z_image_bf16.safetensors"
    assert resolve_image_model("txt2img", None, "z_image_turbo_nvfp4.safetensors") == "z_image_turbo_nvfp4.safetensors"
    assert resolve_image_model("txt2img", "base", "z_image_turbo_nvfp4.safetensors") == "z_image_bf16.safetensors"
    # FLUX.2 / non-z_image models pass through unchanged
    assert resolve_image_model("txt2img", None, "flux2_dev_fp8mixed.safetensors") == "flux2_dev_fp8mixed.safetensors"

def test_flux2_family_still_uses_flux_template(tmp_path):
    m = _m(tmp_path, "flux2_dev_fp8mixed.safetensors")
    wf = build(ROOT, m, positive="x", negative="bad", seed=1, mode="txt2img")
    assert find_node_by_title(wf, "brand:guidance")[1]["inputs"]["guidance"] == 7
    assert find_node_by_title(wf, "brand:negative")[1]["inputs"]["text"] == "bad"
    assert find_node_by_title(wf, "brand:sampler")[1]["inputs"]["steps"] == 99

def test_zimage_lora_preserves_model_sampling_chain(tmp_path):
    # On Z-Image the chain is unet -> ModelSamplingAuraFlow (brand:model_sampling) -> sampler.
    # Splicing a LoRA must keep that intermediary: unet -> lora -> model_sampling -> sampler.
    p = tmp_path / "b.yaml"
    p.write_text("name: B\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\n"
                 "lora: { file: lora/brand_z.safetensors, strength: 0.6 }\n")
    m = load_manifest(p)
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img")
    unet_id, _ = find_node_by_title(wf, "brand:unet")
    # the LoRA reads straight off the unet's MODEL edge
    lora = find_node_by_title(wf, "brand:lora")[1]
    assert lora["inputs"]["model"] == [unet_id, 0]
    assert lora["inputs"]["lora_name"].endswith("brand_z.safetensors")
    assert lora["inputs"]["strength_model"] == 0.6
    # ModelSamplingAuraFlow now reads the LoRA (not the unet), and still feeds the sampler
    ms_id, ms = find_node_by_title(wf, "brand:model_sampling")
    assert ms["inputs"]["model"] == ["99", 0]
    # the sampler reads from ModelSamplingAuraFlow, NOT directly from the LoRA
    sampler = find_node_by_title(wf, "brand:sampler")[1]
    assert sampler["inputs"]["model"] == [ms_id, 0]

def test_zimage_txt2img_watermark_over_decode(tmp_path):
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img", watermark=True,
               watermark_logo="primary.png", logo_px=(120, 120))
    cid, _ = find_node_by_title(wf, "brand:watermark_composite")
    assert find_node_by_title(wf, "brand:save")[1]["inputs"]["images"] == [cid, 0]

def test_upscale_off_by_default_no_nodes(tmp_path):
    from scripts.brandkit.nodes import NodeNotFound
    import pytest
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img")
    with pytest.raises(NodeNotFound):
        find_node_by_title(wf, "brand:upscale")
    decode_id, _ = find_node_by_title(wf, "brand:decode")
    assert find_node_by_title(wf, "brand:save")[1]["inputs"]["images"] == [decode_id, 0]

def test_upscale_splices_before_save(tmp_path):
    from scripts.brandkit.workflow import DEFAULT_UPSCALE_MODEL
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img", upscale=True)
    decode_id, _ = find_node_by_title(wf, "brand:decode")
    # loader feeds the upscale node, which takes over what fed save (the decode)
    assert find_node_by_title(wf, "brand:upscale_model")[1]["inputs"]["model_name"] == DEFAULT_UPSCALE_MODEL
    up = find_node_by_title(wf, "brand:upscale")[1]
    assert up["inputs"]["image"] == [decode_id, 0]
    assert up["inputs"]["upscale_model"] == ["80", 0]
    assert find_node_by_title(wf, "brand:save")[1]["inputs"]["images"] == ["81", 0]

def test_upscale_model_override(tmp_path):
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img",
               upscale=True, upscale_model="4x_foo.pth")
    assert find_node_by_title(wf, "brand:upscale_model")[1]["inputs"]["model_name"] == "4x_foo.pth"

def test_resolved_upscale_model_matches_graph(tmp_path):
    # B6: image upscaler resolver is the single source of truth — equal to what build() wrote
    from scripts.brandkit.workflow import resolved_upscale_model, DEFAULT_UPSCALE_MODEL
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img", upscale=True)
    assert resolved_upscale_model(m) == DEFAULT_UPSCALE_MODEL == \
        find_node_by_title(wf, "brand:upscale_model")[1]["inputs"]["model_name"]
    wf2 = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img",
                upscale=True, upscale_model="cli.pth")
    assert resolved_upscale_model(m, "cli.pth") == "cli.pth" == \
        find_node_by_title(wf2, "brand:upscale_model")[1]["inputs"]["model_name"]

def test_upscale_works_in_product_mode(tmp_path):
    # upscale must splice in for product img2img too, not just txt2img
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="product",
               asset="rover.png", upscale=True)
    find_node_by_title(wf, "brand:upscale")  # node exists (raises NodeNotFound otherwise)
    assert find_node_by_title(wf, "brand:save")[1]["inputs"]["images"] == ["81", 0]

def test_upscale_after_watermark_takes_over_composite(tmp_path):
    # pins the order decode -> composite(96) -> upscale(81) -> save when both are on
    m = _m(tmp_path, "z_image_turbo_nvfp4.safetensors")
    wf = build(ROOT, m, positive="x", negative="", seed=1, mode="txt2img", watermark=True,
               watermark_logo="primary.png", logo_px=(120, 120), upscale=True)
    assert find_node_by_title(wf, "brand:upscale")[1]["inputs"]["image"] == ["96", 0]
    assert find_node_by_title(wf, "brand:save")[1]["inputs"]["images"] == ["81", 0]

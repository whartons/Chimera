"""Load a brand workflow template and fill it from a manifest + render args.
Nodes are addressed by stable _meta.title (see nodes.find_node_by_title), not numeric id."""
from __future__ import annotations
from pathlib import Path
from .manifest import BrandManifest
from .nodes import find_node_by_title, NodeNotFound, assert_free_ids, load_template, model_file, node as _n
from .watermark import logo_geometry

_TEMPLATES = {
    "flux2": {"txt2img": "brand-txt2img.json", "logo": "brand-logo-overlay.json",
              "product": "brand-product-mockup.json", "relight": "brand-flux2-relight.json"},
    "zimage": {"txt2img": "brand-zimage-txt2img.json", "logo": "brand-zimage-logo-overlay.json",
               "product": "brand-zimage-product.json"},
    # Qwen-Image-2.1: product is a reference-image EDIT (the photo is a reference to the text encoder),
    # not img2img, so the product keeps its identity in the new scene.
    "qwen": {"txt2img": "brand-qwen-image-txt2img.json", "logo": "brand-qwen-image-logo-overlay.json",
             "product": "brand-qwen-image-product.json"},
}
# Qwen-Image-2.1's validated sampler settings (official template: euler/simple, 25 steps, CFG 1). Like
# the Z-Image variants they are fixed per model; a brand's FLUX.2 steps/guidance don't apply.
_QWEN = {"steps": 25, "cfg": 1.0}
# Relight (FLUX.2 ReferenceLatent edit) is a FLUX.2-only capability — Z-Image has no equivalent edit
# node here. When relight is requested without a FLUX.2 model, fall back to this default so the mode
# "just works" rather than erroring on a Z-Image brand default. (resolve_image_model enforces this for
# both the graph and the sidecar; see build_workflow.)
DEFAULT_RELIGHT_MODEL = "flux2_dev_fp8mixed.safetensors"
# Z-Image fidelity variants: model + KSampler steps/cfg (validated values).
_ZIMAGE_VARIANTS = {
    "turbo": {"model": "z_image_turbo_nvfp4.safetensors", "steps": 8, "cfg": 1.0},
    "base":  {"model": "z_image_bf16.safetensors", "steps": 25, "cfg": 4.0},
}
# Default upscaler for the opt-in image --upscale pass: SeedVR2 7B, a one-step diffusion upscaler that
# restores real detail (the 2026-10 review: ESRGAN/UltraSharp invents textures — crosshatch on fabric,
# speckles on skin). It lives in models/diffusion_models/ with its VAE in models/vae/. An ESRGAN-style
# model name (e.g. 4x-UltraSharp.pth, in models/upscale_models/) selects the classic ESRGAN pass.
DEFAULT_UPSCALE_MODEL = "seedvr2_7b_int8_convrot.safetensors"
SEEDVR2_VAE = "seedvr2_ema_vae_fp16.safetensors"
UPSCALE_FACTOR = 4


def family(model):
    """'zimage' | 'qwen' | 'flux2' (anything else runs the FLUX.2 graph), from the model's file name."""
    name = model_file(model)
    if name.startswith("z_image"):
        return "zimage"
    if name.startswith("qwen_image"):
        return "qwen"
    return "flux2"


def _load_template(repo_root: Path, fam: str, mode: str) -> dict:
    modes = _TEMPLATES[fam]
    if mode not in modes:
        raise ValueError(f"unknown mode {mode!r}; expected one of {list(modes)}")
    return load_template(repo_root, modes[mode])


def _apply_common(wf: dict, m: BrandManifest, positive: str, negative: str, seed: int, model: str):
    # `model` is the already-resolved checkpoint (honors a --model override; equals what the sidecar
    # records via resolve_image_model). Writing m.defaults.model here would ignore the override and
    # drift from the sidecar — so write the resolved value.
    d = m.defaults
    _n(wf, "brand:unet")["inputs"]["unet_name"] = model
    _n(wf, "brand:positive")["inputs"]["text"] = positive
    _n(wf, "brand:negative")["inputs"]["text"] = negative
    _n(wf, "brand:guidance")["inputs"]["guidance"] = d.guidance
    s = _n(wf, "brand:sampler")
    s["inputs"]["seed"] = seed
    s["inputs"]["steps"] = d.steps
    try:
        lat = _n(wf, "brand:latent")
        lat["inputs"]["width"] = d.width
        lat["inputs"]["height"] = d.height
    except NodeNotFound:
        pass  # product template has no empty-latent node


def _zimage_variant(mode, variant, model):
    """Resolve the Z-Image fidelity variant. Explicit --variant wins; else product img2img
    always needs base fidelity; else infer from the (manifest/--model) model name; else turbo."""
    if variant:
        return variant
    if mode == "product":
        return "base"
    name = (model or "").lower()
    if "turbo" in name:
        return "turbo"
    if "bf16" in name or "base" in name:
        return "base"
    return "turbo"


def resolve_image_model(mode, variant, model):
    """The model file the image graph will actually load — for the sidecar. Z-Image's variant
    determines the file (e.g. product/--variant base -> z_image_bf16, not the brand's turbo
    default); FLUX.2 (and anything non-z_image) loads the given model name as-is. `relight` is a
    FLUX.2 (ReferenceLatent) capability, so a non-FLUX.2 model resolves to DEFAULT_RELIGHT_MODEL —
    keeping the graph and the sidecar in agreement on a single source of truth."""
    if mode == "relight" and family(model) != "flux2":
        return DEFAULT_RELIGHT_MODEL
    if family(model) == "zimage":
        return _ZIMAGE_VARIANTS[_zimage_variant(mode, variant, model)]["model"]
    return model


def needs_free_before(mode, variant, model):
    """True when the image graph loads FLUX.2: its ~33 GB bf16 text encoder (beside a ~32 GB fp8
    diffusion model) is disk-streamed by ComfyUI 0.40's comfy-aimdo, and that load fails with Windows
    error 1450 ("HostBuffer.read_file_slice failed") while other models are still staged — freeing
    first fixes it (2026-10-14 smoke). Z-Image graphs keep the fast back-to-back default."""
    return family(resolve_image_model(mode, variant, model)) == "flux2"


def resolved_upscale_model(manifest, upscale_model=None):
    """The upscaler the image --upscale pass will load: explicit override, else the brand's
    defaults.upscale_model, else DEFAULT_UPSCALE_MODEL (SeedVR2). Single source of truth shared by
    build() and the sidecar (model selection itself is resolve_image_model). Parallels
    video.resolved_upscale_model."""
    return upscale_model or manifest.defaults.upscale_model or DEFAULT_UPSCALE_MODEL


def _is_seedvr2(model_name):
    return "seedvr2" in (model_name or "").lower()


def _apply_zimage(wf, m, positive, seed, mode, variant, model):
    variant = _zimage_variant(mode, variant, model)
    v = _ZIMAGE_VARIANTS.get(variant)
    if v is None:
        raise ValueError(f"unknown Z-Image variant {variant!r}; expected one of {list(_ZIMAGE_VARIANTS)}")
    # The variant fully determines the Z-Image model file + steps + cfg (the two distilled-vs-base
    # checkpoints pair with specific sampler settings; mixing them — e.g. the turbo model at 25
    # base steps — degrades output). The manifest/--model only selects the family (z_image*).
    _n(wf, "brand:unet")["inputs"]["unet_name"] = v["model"]
    _n(wf, "brand:positive")["inputs"]["text"] = positive
    s = _n(wf, "brand:sampler")["inputs"]
    s["seed"] = seed
    s["steps"] = v["steps"]
    s["cfg"] = v["cfg"]
    try:  # product (img2img) has no empty-latent node
        lat = _n(wf, "brand:latent")["inputs"]
        lat["width"], lat["height"] = m.defaults.width, m.defaults.height
    except NodeNotFound:
        pass


def _apply_qwen(wf, m, positive, negative, seed, model):
    # TextEncodeQwenImage21 encodes BOTH prompts (outputs 0 = positive, 1 = negative), so the brand
    # negative goes on brand:positive's negative_prompt; there is no separate brand:negative node.
    _n(wf, "brand:unet")["inputs"]["unet_name"] = model
    enc = _n(wf, "brand:positive")["inputs"]
    enc["prompt"], enc["negative_prompt"] = positive, negative
    s = _n(wf, "brand:sampler")["inputs"]
    s["seed"], s["steps"], s["cfg"] = seed, _QWEN["steps"], _QWEN["cfg"]
    lat = _n(wf, "brand:latent")["inputs"]
    lat["width"], lat["height"] = m.defaults.width, m.defaults.height


def _inject_lora(wf: dict, m: BrandManifest):
    if not m.lora.file:
        return
    lora_name = m.lora.file.split("/")[-1]
    assert_free_ids(wf, "99")
    unet_id, _ = find_node_by_title(wf, "brand:unet")
    # Splice the LoRA onto the unet's MODEL edge generically: rewire whatever currently reads
    # [unet_id, 0] (the sampler for FLUX; ModelSamplingAuraFlow for Z-Image) to read the LoRA,
    # so an intervening model-patch node is never dropped.
    wf["99"] = {
        "class_type": "LoraLoaderModelOnly", "_meta": {"title": "brand:lora"},
        "inputs": {"model": [unet_id, 0], "lora_name": lora_name, "strength_model": m.lora.strength},
    }
    for nid, node in wf.items():
        if nid == "99" or not isinstance(node, dict):
            continue
        mi = node.get("inputs", {}).get("model")
        if isinstance(mi, list) and len(mi) == 2 and mi[0] == unet_id:
            node["inputs"]["model"] = ["99", 0]


def _inject_upscale(wf, model_name, seed=0):
    """Splice a 4x upscale just before brand:save: take over whatever currently feeds brand:save (the
    decoded image, or the watermark composite if watermark ran first) and rewire save to read the
    upscaled image. Order-independent w.r.t. watermark. SeedVR2 (ids 80-88) unless `model_name` is an
    ESRGAN-style model (ids 80-81)."""
    _, save = find_node_by_title(wf, "brand:save")
    src = save["inputs"]["images"]            # current source: [decode,0] or [composite,0]
    if not _is_seedvr2(model_name):
        assert_free_ids(wf, "80", "81")
        wf["80"] = {"class_type": "UpscaleModelLoader", "_meta": {"title": "brand:upscale_model"},
                    "inputs": {"model_name": model_name}}
        wf["81"] = {"class_type": "ImageUpscaleWithModel", "_meta": {"title": "brand:upscale"},
                    "inputs": {"upscale_model": ["80", 0], "image": src}}
        save["inputs"]["images"] = ["81", 0]
        return wf
    # SeedVR2 (the official Comfy graph): lanczos-resize to the target size, encode with the tiled
    # SeedVR2 VAE, one euler step conditioned on that latent, decode, then post-process against the
    # resized input. The official graph's JoinImageWithAlpha only carries a loaded PNG's alpha; a
    # decoded render has none, so the image feeds the resize directly.
    assert_free_ids(wf, *(str(i) for i in range(80, 89)))
    tiled = {"tile_size": 512, "overlap": 128, "temporal_size": 4096, "temporal_overlap": 8}
    wf["80"] = {"class_type": "UNETLoader", "_meta": {"title": "brand:upscale_model"},
                "inputs": {"unet_name": model_name, "weight_dtype": "default"}}
    wf["81"] = {"class_type": "VAELoader", "_meta": {"title": "brand:upscale_vae"},
                "inputs": {"vae_name": SEEDVR2_VAE}}
    wf["82"] = {"class_type": "ResizeImageMaskNode", "_meta": {"title": "brand:upscale_resize"},
                "inputs": {"input": src, "resize_type": "scale by multiplier",
                           "resize_type.multiplier": UPSCALE_FACTOR, "scale_method": "lanczos"}}
    wf["83"] = {"class_type": "SeedVR2Preprocess", "inputs": {"resized_images": ["82", 0]}}
    wf["84"] = {"class_type": "VAEEncodeTiled", "inputs": {"pixels": ["83", 0], "vae": ["81", 0], **tiled}}
    wf["85"] = {"class_type": "SeedVR2Conditioning", "inputs": {"model": ["80", 0], "vae_conditioning": ["84", 0]}}
    wf["86"] = {"class_type": "KSampler", "_meta": {"title": "brand:upscale_sampler"},
                "inputs": {"model": ["80", 0], "positive": ["85", 0], "negative": ["85", 1],
                           "latent_image": ["84", 0], "seed": seed, "steps": 1, "cfg": 1.0,
                           "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
    wf["87"] = {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["86", 0], "vae": ["81", 0], **tiled}}
    wf["88"] = {"class_type": "SeedVR2PostProcessing", "_meta": {"title": "brand:upscale"},
                "inputs": {"images": ["87", 0], "original_resized_images": ["82", 0],
                           "color_correction_method": "none"}}
    save["inputs"]["images"] = ["88", 0]
    return wf


def _place_logo(wf: dict, m: BrandManifest, logo_px=None):
    # logo image AND its mask are scaled by logo.scale (both must match, or the composite
    # misaligns); x/y geometry is shared with the watermark injector (logo_geometry), so the
    # two placements can never drift apart.
    s = m.logo.scale
    _n(wf, "brand:logo_scale")["inputs"]["scale_by"] = s
    _n(wf, "brand:logo_mask_scale")["inputs"]["scale_by"] = s
    x, y, _scale = logo_geometry((m.defaults.width, m.defaults.height), logo_px=logo_px,
                                 scale=s, margin=m.logo.margin, position=m.logo.position)
    comp = _n(wf, "brand:logo_composite")
    comp["inputs"]["x"] = x
    comp["inputs"]["y"] = y


def build_workflow(repo_root, m: BrandManifest, mode: str, positive: str, negative: str,
                   seed: int, logo_image=None, product_image=None, source_image=None, logo_px=None,
                   variant=None, model=None) -> dict:
    model = model or m.defaults.model
    # Resolve the model FIRST and derive the family from the resolved name, so a relight on a Z-Image
    # brand default correctly resolves to FLUX.2 and loads the FLUX.2 relight template (not a missing
    # zimage/relight one). resolve_image_model is a passthrough for normal FLUX.2/Z-Image runs.
    resolved = resolve_image_model(mode, variant, model)
    fam = family(resolved)
    wf = _load_template(Path(repo_root), fam, mode)   # fresh parse per call — mutation-safe
    if fam == "zimage":
        _apply_zimage(wf, m, positive, seed, mode, variant, model)
    elif fam == "qwen":
        _apply_qwen(wf, m, positive, negative, seed, resolved)
    else:
        # FLUX/other: write the resolved model — the same value _resolve_model_used records — so a
        # --model override (or the relight FLUX.2 fallback) reaches the graph AND the sidecar identically.
        _apply_common(wf, m, positive, negative, seed, resolved)
    _inject_lora(wf, m)
    if mode == "logo":
        name = logo_image or (m.logo.default or "").split("/")[-1]
        if not name:
            raise ValueError("logo mode requires a logo image (logo_image arg or logo.default)")
        _n(wf, "brand:logo_load")["inputs"]["image"] = name
        _place_logo(wf, m, logo_px)
    if mode == "product":
        if not product_image:
            raise ValueError("product mode requires product_image")
        _n(wf, "brand:product_load")["inputs"]["image"] = product_image
    if mode == "relight":
        if not source_image:
            raise ValueError("relight mode requires source_image")
        _n(wf, "brand:relight_load")["inputs"]["image"] = source_image
    return wf


def build(repo_root, manifest, *, positive, negative, seed, watermark=False,
          mode="txt2img", asset=None, logo_px=None, watermark_logo=None, canvas=None,
          variant=None, model=None, upscale=False, upscale_model=None):
    """Uniform filler contract (image). `asset` = uploaded logo/product name; `watermark_logo`
    = uploaded brand-logo name for the opt-in watermark; `canvas` = (w,h) for watermark geometry.
    `upscale` splices a 4x upscale before brand:save (after the watermark, so the logo upscales with
    the image): SeedVR2 by default; `upscale_model` overrides DEFAULT_UPSCALE_MODEL (an ESRGAN name such
    as 4x-UltraSharp.pth selects the ESRGAN pass)."""
    kw = {"variant": variant, "model": model}
    if mode == "logo":
        kw["logo_image"] = asset
        kw["logo_px"] = logo_px
    if mode == "product":
        kw["product_image"] = asset
    if mode == "relight":
        kw["source_image"] = asset
    wf = build_workflow(repo_root, manifest, mode=mode, positive=positive,
                        negative=negative, seed=seed, **kw)
    if mode == "product" and family(resolve_image_model(mode, variant, model or manifest.defaults.model)) == "qwen":
        canvas = None   # a Qwen edit renders at the brand size, not at the product photo's size
    if watermark and mode != "logo":  # logo mode already composites a logo
        from .watermark import inject_image_watermark
        inject_image_watermark(wf, manifest=manifest, logo_name=watermark_logo,
                               canvas=canvas or (manifest.defaults.width, manifest.defaults.height),
                               logo_px=logo_px)
    if upscale:  # after watermark: upscale takes over the composite's edge into save
        _inject_upscale(wf, resolved_upscale_model(manifest, upscale_model), seed=seed)
    return wf

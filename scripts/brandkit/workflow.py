"""Load a brand workflow template and fill it from a manifest + render args.
Nodes are addressed by stable _meta.title (see nodes.find_node_by_title), not numeric id."""
from __future__ import annotations
import json
from pathlib import Path
from copy import deepcopy
from .manifest import BrandManifest
from .nodes import find_node_by_title, NodeNotFound

_TEMPLATES = {
    "flux2": {"txt2img": "brand-txt2img.json", "logo": "brand-logo-overlay.json",
              "product": "brand-product-mockup.json"},
    "zimage": {"txt2img": "brand-zimage-txt2img.json", "logo": "brand-zimage-logo-overlay.json",
               "product": "brand-zimage-product.json"},
}
# Z-Image fidelity variants: model + KSampler steps/cfg (validated values).
_ZIMAGE_VARIANTS = {
    "turbo": {"model": "z_image_turbo_nvfp4.safetensors", "steps": 8, "cfg": 1.0},
    "base":  {"model": "z_image_bf16.safetensors", "steps": 25, "cfg": 4.0},
}
# Default ESRGAN upscaler for the opt-in image --upscale pass (in models/upscale_models/).
DEFAULT_UPSCALE_MODEL = "4x-UltraSharp.pth"


def _family(model):
    return "zimage" if (model or "").lower().startswith("z_image") else "flux2"


def _load_template(repo_root: Path, family: str, mode: str) -> dict:
    fam = _TEMPLATES[family]
    if mode not in fam:
        raise ValueError(f"unknown mode {mode!r}; expected one of {list(fam)}")
    p = Path(repo_root) / "workflows" / "templates" / fam[mode]
    return json.loads(p.read_text(encoding="utf-8"))


def _n(wf, title):
    return find_node_by_title(wf, title)[1]


def _apply_common(wf: dict, m: BrandManifest, positive: str, negative: str, seed: int):
    d = m.defaults
    _n(wf, "brand:unet")["inputs"]["unet_name"] = d.model
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
    default); FLUX.2 (and anything non-z_image) loads the given model name as-is."""
    if _family(model) == "zimage":
        return _ZIMAGE_VARIANTS[_zimage_variant(mode, variant, model)]["model"]
    return model


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


def _inject_lora(wf: dict, m: BrandManifest):
    if not m.lora.file:
        return
    lora_name = m.lora.file.split("/")[-1]
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


def _inject_upscale(wf, model_name):
    """Splice an ESRGAN upscale just before brand:save: take over whatever currently feeds
    brand:save (the decoded image, or the watermark composite if watermark ran first) and
    rewire save to read the upscaled image. Order-independent w.r.t. watermark. Ids 80-81."""
    _, save = find_node_by_title(wf, "brand:save")
    src = save["inputs"]["images"]            # current source: [decode,0] or [composite,0]
    wf["80"] = {"class_type": "UpscaleModelLoader", "_meta": {"title": "brand:upscale_model"},
                "inputs": {"model_name": model_name}}
    wf["81"] = {"class_type": "ImageUpscaleWithModel", "_meta": {"title": "brand:upscale"},
                "inputs": {"upscale_model": ["80", 0], "image": src}}
    save["inputs"]["images"] = ["81", 0]
    return wf


def _place_logo(wf: dict, m: BrandManifest, logo_px=None):
    # logo image AND its mask are scaled by logo.scale (both must match, or the
    # composite misaligns); x/y from position + margin against the canvas.
    cw, ch = m.defaults.width, m.defaults.height
    s, marg = m.logo.scale, m.logo.margin
    _n(wf, "brand:logo_scale")["inputs"]["scale_by"] = s
    _n(wf, "brand:logo_mask_scale")["inputs"]["scale_by"] = s
    if logo_px:
        lw, lh = logo_px
    else:
        lw, lh = int(cw * s), int(ch * s)
    mx, my = int(cw * marg), int(ch * marg)
    pos = m.logo.position
    x = mx if "left" in pos else (cw - lw - mx)
    y = my if "top" in pos else (ch - lh - my)
    if pos == "center":
        x, y = (cw - lw) // 2, (ch - lh) // 2
    comp = _n(wf, "brand:logo_composite")
    comp["inputs"]["x"] = max(0, x)
    comp["inputs"]["y"] = max(0, y)


def build_workflow(repo_root, m: BrandManifest, mode: str, positive: str, negative: str,
                   seed: int, logo_image=None, product_image=None, logo_px=None,
                   variant=None, model=None) -> dict:
    model = model or m.defaults.model
    family = _family(model)
    wf = deepcopy(_load_template(Path(repo_root), family, mode))
    if family == "zimage":
        _apply_zimage(wf, m, positive, seed, mode, variant, model)
    else:
        _apply_common(wf, m, positive, negative, seed)
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
    return wf


def build(repo_root, manifest, *, positive, negative, seed, watermark=False,
          mode="txt2img", asset=None, logo_px=None, watermark_logo=None, canvas=None,
          variant=None, model=None, upscale=False, upscale_model=None):
    """Uniform filler contract (image). `asset` = uploaded logo/product name; `watermark_logo`
    = uploaded brand-logo name for the opt-in watermark; `canvas` = (w,h) for watermark geometry.
    `upscale` splices a 4x ESRGAN pass before brand:save (after the watermark, so the logo
    upscales with the image); `upscale_model` overrides DEFAULT_UPSCALE_MODEL."""
    kw = {"variant": variant, "model": model}
    if mode == "logo":
        kw["logo_image"] = asset
        kw["logo_px"] = logo_px
    if mode == "product":
        kw["product_image"] = asset
    wf = build_workflow(repo_root, manifest, mode=mode, positive=positive,
                        negative=negative, seed=seed, **kw)
    if watermark and mode != "logo":  # logo mode already composites a logo
        from .watermark import inject_image_watermark
        inject_image_watermark(wf, manifest=manifest, logo_name=watermark_logo,
                               canvas=canvas or (manifest.defaults.width, manifest.defaults.height),
                               logo_px=logo_px)
    if upscale:  # after watermark: upscale takes over the composite's edge into save
        _inject_upscale(wf, upscale_model or DEFAULT_UPSCALE_MODEL)
    return wf

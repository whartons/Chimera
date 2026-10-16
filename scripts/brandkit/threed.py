"""Fill a 3D template (image -> 3D -> GLB) by title. Image-conditioned (no text prompt, no watermark);
native ComfyUI nodes only. Three models:

- TRELLIS.2 (default) and Pixal3D share one ComfyUI 0.40 graph (brand-3d-trellis2.json): background
  cut-out, structure -> shape -> texture stages, remesh + UV unwrap + PBR bake -> a TEXTURED GLB.
  Pixal3D adds a MoGe camera-FOV estimate so the mesh lines up with the photo's viewpoint.
- Hunyuan3D 2.1 (brand-3d-image.json): shape only, about 4x faster; color it with the mesh3d loop's
  --texture or `generate.py finalize-texture`."""
from __future__ import annotations
from .nodes import load_template, node as _n

TRELLIS2_MODEL = "trellis_2_int8_convrot.safetensors"
PIXAL3D_MODEL = "pixal3d_int8_convrot.safetensors"
HUNYUAN3D_MODEL = "hunyuan_3d_v2.1.safetensors"
DEFAULT_3D_MODEL = TRELLIS2_MODEL
# Short names accepted wherever a 3D model is chosen (--model, --mesh-model, brand threed.model). They
# resolve to the file name, which is what the graph loads and the sidecar records.
ALIASES = {"trellis2": TRELLIS2_MODEL, "trellis.2": TRELLIS2_MODEL, "pixal3d": PIXAL3D_MODEL,
           "hunyuan21": HUNYUAN3D_MODEL, "hunyuan3d": HUNYUAN3D_MODEL}
_SAMPLERS = ("brand:sampler_structure", "brand:sampler_shape", "brand:sampler_upsample", "brand:sampler_texture")


def canonical(name):
    """A 3D model short name -> its file name; file names (and unknown names) pass through."""
    return ALIASES.get((name or "").lower(), name)


def resolved_model(manifest, model=None):
    """The 3D model file build() will load: explicit override, else the brand's threed.model, else
    DEFAULT_3D_MODEL (short names resolved). Single source of truth shared by build() and the sidecar."""
    return canonical(model or manifest.threed.model or DEFAULT_3D_MODEL)


def family(model_file):
    name = (model_file or "").lower()
    if name.startswith("trellis"):
        return "trellis2"
    if name.startswith("pixal3d"):
        return "pixal3d"
    return "hunyuan3d"


def is_textured(model_file):
    """True when the model's graph bakes textures itself (so the mesh3d loop judges color, and the
    shape-only coloring paths --texture / --finalize don't apply)."""
    return family(model_file) in ("trellis2", "pixal3d")


def build(repo_root, manifest, *, positive="", negative="", seed, watermark=False,
          from_image=None, octree=None, model=None, **opts) -> dict:
    t = manifest.threed
    if not from_image:
        raise ValueError("3d requires from_image")
    model = resolved_model(manifest, model)
    fam = family(model)
    if fam == "hunyuan3d":
        octree = octree if octree is not None else t.octree
        wf = load_template(repo_root, "brand-3d-image.json")
        _n(wf, "brand:ckpt")["inputs"]["ckpt_name"] = model
        _n(wf, "brand:load_image")["inputs"]["image"] = from_image
        s = _n(wf, "brand:sampler")["inputs"]
        s["seed"] = seed
        s["steps"] = t.steps
        s["cfg"] = t.cfg
        _n(wf, "brand:decode")["inputs"]["octree_resolution"] = octree
        return wf
    # TRELLIS.2 / Pixal3D: the official graph's own sampler settings (steps/CFG per stage) are kept;
    # the brand's threed.steps/cfg/octree are Hunyuan3D settings. One seed drives all four stages.
    wf = load_template(repo_root, "brand-3d-trellis2.json")
    _n(wf, "brand:load_image")["inputs"]["image"] = from_image
    _n(wf, "brand:use_trellis2")["inputs"]["value"] = fam == "trellis2"
    _n(wf, "brand:trellis2_model" if fam == "trellis2" else "brand:pixal3d_model")["inputs"]["unet_name"] = model
    for i, title in enumerate(_SAMPLERS):
        _n(wf, title)["inputs"]["seed"] = seed + i
    return wf

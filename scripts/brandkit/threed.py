"""Fill the Hunyuan3D 2.1 brand-3d-image template (image->3D->GLB) by title. Image-conditioned
(CLIP-Vision of the input image); no text prompt, no watermark. Native ComfyUI nodes only."""
from __future__ import annotations
import json
from pathlib import Path
from copy import deepcopy
from .nodes import find_node_by_title

DEFAULT_3D_MODEL = "hunyuan_3d_v2.1.safetensors"


def _n(wf, title):
    return find_node_by_title(wf, title)[1]


def resolved_model(manifest, model=None):
    """The 3D checkpoint build() will load: explicit override, else the brand's threed.model,
    else DEFAULT_3D_MODEL. Single source of truth shared by build() and the sidecar."""
    return model or manifest.threed.model or DEFAULT_3D_MODEL


def build(repo_root, manifest, *, positive="", negative="", seed, watermark=False,
          from_image=None, octree=None, model=None, **opts) -> dict:
    t = manifest.threed
    if not from_image:
        raise ValueError("3d requires from_image")
    model = resolved_model(manifest, model)
    octree = octree if octree is not None else t.octree
    p = Path(repo_root) / "workflows" / "templates" / "brand-3d-image.json"
    wf = deepcopy(json.loads(p.read_text(encoding="utf-8")))
    _n(wf, "brand:ckpt")["inputs"]["ckpt_name"] = model
    _n(wf, "brand:load_image")["inputs"]["image"] = from_image
    s = _n(wf, "brand:sampler")["inputs"]
    s["seed"] = seed
    s["steps"] = t.steps
    s["cfg"] = t.cfg
    _n(wf, "brand:decode")["inputs"]["octree_resolution"] = octree
    return wf

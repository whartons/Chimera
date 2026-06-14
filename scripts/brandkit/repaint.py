"""Build an SDXL depth-ControlNet + IPAdapter "repaint" graph (ComfyUI API format) for Phase-4b
auto-repaint: lock a view's geometry to its rendered depth map (depth ControlNet) while carrying the
concept's identity/material (IPAdapter) -> a corrected view image of the subject from that viewpoint.
The N corrected views then feed _common.bake_multiview into an all-around albedo atlas.

Native ComfyUI nodes + the audited cubiq IPAdapter pack (ComfyUI_IPAdapter_plus @ a0f451a). Model
filenames are parameters (the pieces live in the ComfyUI models/ tree; see docs/CATALOG.md). Nodes are
addressed by stable _meta.title so re-saving can't break the filler (same convention as the other
fillers). Exact cubiq node input names are verified live against get_node_info before first use."""
from __future__ import annotations
from pathlib import Path
from scripts.brandkit.outputs import select_output

DEFAULT_SDXL = "sd_xl_base_1.0.safetensors"
DEFAULT_IPADAPTER = "ip-adapter-plus_sdxl_vit-h.safetensors"
DEFAULT_CLIPVISION = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
DEFAULT_DEPTH_CN = "controlnet-depth-sdxl-1.0.safetensors"
DEFAULT_NEG = "blurry, low quality, deformed, extra limbs, duplicated parts, watermark, text, background clutter"


def build(*, depth_image, concept_image, positive, negative=DEFAULT_NEG, seed,
          width=1024, height=1024, steps=28, cfg=6.5,
          cn_strength=0.7, ip_weight=0.8,
          checkpoint=DEFAULT_SDXL, ipadapter=DEFAULT_IPADAPTER,
          clip_vision=DEFAULT_CLIPVISION, controlnet=DEFAULT_DEPTH_CN) -> dict:
    """API-format graph. `depth_image`/`concept_image` are uploaded ComfyUI input names. `positive`
    describes the subject (IPAdapter carries the concept's specifics, ControlNet the geometry)."""
    return {
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint},
                 "_meta": {"title": "brand:ckpt"}},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["ckpt", 1]},
                     "_meta": {"title": "brand:positive"}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["ckpt", 1]},
                     "_meta": {"title": "brand:negative"}},
        "ipmodel": {"class_type": "IPAdapterModelLoader", "inputs": {"ipadapter_file": ipadapter},
                    "_meta": {"title": "brand:ipmodel"}},
        "clipvis": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": clip_vision},
                    "_meta": {"title": "brand:clipvis"}},
        "concept": {"class_type": "LoadImage", "inputs": {"image": concept_image},
                    "_meta": {"title": "brand:concept"}},
        "ipadapter": {"class_type": "IPAdapterAdvanced",
                      "inputs": {"model": ["ckpt", 0], "ipadapter": ["ipmodel", 0],
                                 "image": ["concept", 0], "clip_vision": ["clipvis", 0],
                                 "weight": ip_weight, "weight_type": "linear",
                                 "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                                 "embeds_scaling": "V only"},
                      "_meta": {"title": "brand:ipadapter"}},
        "cnet": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": controlnet},
                 "_meta": {"title": "brand:cnet"}},
        "depth": {"class_type": "LoadImage", "inputs": {"image": depth_image},
                  "_meta": {"title": "brand:depth"}},
        "cnapply": {"class_type": "ControlNetApplyAdvanced",
                    "inputs": {"positive": ["positive", 0], "negative": ["negative", 0],
                               "control_net": ["cnet", 0], "image": ["depth", 0],
                               "strength": cn_strength, "start_percent": 0.0, "end_percent": 1.0},
                    "_meta": {"title": "brand:cnapply"}},
        "latent": {"class_type": "EmptyLatentImage",
                   "inputs": {"width": width, "height": height, "batch_size": 1},
                   "_meta": {"title": "brand:latent"}},
        "ksampler": {"class_type": "KSampler",
                     "inputs": {"model": ["ipadapter", 0], "positive": ["cnapply", 0],
                                "negative": ["cnapply", 1], "latent_image": ["latent", 0],
                                "seed": seed, "steps": steps, "cfg": cfg,
                                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0},
                     "_meta": {"title": "brand:ksampler"}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["ksampler", 0], "vae": ["ckpt", 2]},
                   "_meta": {"title": "brand:decode"}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": "repaint"},
                 "_meta": {"title": "brand:save"}},
    }


def generate_views(client, *, mesh, concept_path, subject, azimuths, comfy_output_dir, out_dir,
                   render_views_template, blender_runner, seed, res=1024, elevation=15.0,
                   cn_strength=0.7, ip_weight=0.8, blender_bin=None, blender_timeout=600,
                   comfy_timeout=1200, negative=DEFAULT_NEG):
    """Generate N corrected views for `mesh` to feed bake_multiview: render per-view depth maps
    (render_views, headless Blender), then SDXL depth-ControlNet + IPAdapter repaint each from the
    concept. Returns (view_image_paths, depth_paths). All I/O is injected (client, blender_runner) so
    it's unit-testable without ComfyUI/Blender. The concept carries identity; each depth locks geometry."""
    concept_up = client.upload_image(Path(concept_path))
    rv = blender_runner(render_views_template,
                        {"mesh": str(Path(mesh).resolve()), "out_dir": str(out_dir), "stem": "rv",
                         "azimuths": list(azimuths), "elevation": elevation, "res": [res, res], "samples": 1},
                        blender_bin=blender_bin, timeout=blender_timeout)
    depths = rv.get("outputs", [])
    out = Path(comfy_output_dir)
    views = []
    for i, dp in enumerate(depths):
        dup = client.upload_image(Path(dp))
        wf = build(depth_image=dup, concept_image=concept_up,
                   positive=f"{subject}, full object, clean studio render, plain solid background",
                   negative=negative, seed=seed + 1 + i, width=res, height=res,
                   cn_strength=cn_strength, ip_weight=ip_weight)
        pid = client.queue_prompt(wf)
        client.wait(pid, max_wait=comfy_timeout)
        fname, subfolder, _ = select_output(client, pid, wf)
        views.append(str(out / subfolder / fname))
    return views, depths

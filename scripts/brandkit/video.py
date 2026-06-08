"""Fill the LTX-2.3 brand-video-i2v template from a manifest + render args, by title.
LOCAL ONLY — uses the in-graph LTXAVTextEncoderLoader (gemma), never the cloud encoder."""
from __future__ import annotations
import json
from pathlib import Path
from copy import deepcopy
from .nodes import find_node_by_title

DEFAULT_MODEL = "ltx-2.3-22b-dev-nvfp4.safetensors"
# LTX 2x spatial latent upscaler for the opt-in video --upscale pass (built-in option of
# LatentUpscaleModelLoader; in models/latent_upscale_models/).
DEFAULT_VIDEO_UPSCALE_MODEL = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
# Appended to the brand negative for video: suppress frozen/static frames, force audio, and
# suppress the i2v artifacts that read as "unrealistic" (warping/morphing/jitter). The brand
# negative is image-oriented and lacks these; the validated render relied on the first two.
VIDEO_NEG_EXTRA = ("still frame, frozen video, music, silence, morphing, warping, melting, "
                   "distortion, deformation, wobbling, jitter, flicker, rubbery motion, "
                   "object disintegrating, inconsistent geometry")


def _n(wf, title):
    return find_node_by_title(wf, title)[1]


def _inject_video_upscale(wf, model_name):
    """Splice the LTX 2x spatial latent upscaler just before brand:decode: take over whatever
    feeds brand:decode's `samples` (the separated video latent) and the decode's VAE, run them
    through LTXVLatentUpsampler, and rewire decode to the upscaled latent. Latent-space (temporally
    coherent), so it precedes the pixel-space watermark. Ids 70/71."""
    _, decode = find_node_by_title(wf, "brand:decode")
    src = decode["inputs"]["samples"]      # current video-latent source, e.g. ["22",0]
    vae = decode["inputs"]["vae"]          # the video VAE, e.g. ["1",2]
    wf["70"] = {"class_type": "LatentUpscaleModelLoader", "_meta": {"title": "brand:video_upscale_model"},
                "inputs": {"model_name": model_name}}
    wf["71"] = {"class_type": "LTXVLatentUpsampler", "_meta": {"title": "brand:video_upscale"},
                "inputs": {"samples": src, "upscale_model": ["70", 0], "vae": vae}}
    decode["inputs"]["samples"] = ["71", 0]
    return wf


def build(repo_root, manifest, *, positive, negative, seed, watermark=False,
          from_image=None, length=None, fps=None, audio=True, width=None, height=None,
          model=None, watermark_logo=None, logo_px=None, upscale=False, upscale_model=None,
          **opts) -> dict:
    v = manifest.video
    model = model or v.model or DEFAULT_MODEL
    width = width or v.width
    height = height or v.height
    length = length or v.length
    fps = fps or v.fps
    if not from_image:
        raise ValueError("video i2v requires from_image")

    p = Path(repo_root) / "workflows" / "templates" / "brand-video-i2v.json"
    wf = deepcopy(json.loads(p.read_text(encoding="utf-8")))

    for t in ("brand:ckpt", "brand:encoder", "brand:audio_vae"):
        _n(wf, t)["inputs"]["ckpt_name"] = model
    _n(wf, "brand:positive")["inputs"]["text"] = positive
    _n(wf, "brand:negative")["inputs"]["text"] = ", ".join(s for s in (negative, VIDEO_NEG_EXTRA) if s)
    _n(wf, "brand:cond")["inputs"]["frame_rate"] = fps
    _n(wf, "brand:create_video")["inputs"]["fps"] = fps
    _n(wf, "brand:noise")["inputs"]["noise_seed"] = seed
    _n(wf, "brand:load_image")["inputs"]["image"] = from_image
    for t in ("brand:resize", "brand:video_latent"):
        _n(wf, t)["inputs"]["width"] = width
        _n(wf, t)["inputs"]["height"] = height
    _n(wf, "brand:video_latent")["inputs"]["length"] = length
    al = _n(wf, "brand:audio_latent")["inputs"]
    al["frames_number"] = length
    al["frame_rate"] = fps

    if not audio:
        _n(wf, "brand:create_video")["inputs"].pop("audio", None)

    if upscale:
        _inject_video_upscale(wf, upscale_model or DEFAULT_VIDEO_UPSCALE_MODEL)
    if watermark:
        from .watermark import inject_video_watermark
        # The LTX spatial upscaler is fixed 2x, so the decoded frames are 2x the base canvas;
        # the watermark places its logo by canvas geometry, so it must use the doubled canvas.
        wm_canvas = (width * 2, height * 2) if upscale else (width, height)
        inject_video_watermark(wf, manifest=manifest, logo_name=watermark_logo,
                               canvas=wm_canvas, logo_px=logo_px)
    return wf

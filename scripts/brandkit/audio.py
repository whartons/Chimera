"""Fill the audio templates (ACE-Step music / HunyuanVideo-Foley) from a manifest + args, by
title. Dispatches on `mode`. LOCAL ONLY for foley — uses ONLY the registered HunyuanFoley nodes
+ safetensors weights, never the pack's bundled CLI scripts (torch.load pickle-RCE)."""
from __future__ import annotations
import json
from pathlib import Path
from copy import deepcopy
from .nodes import find_node_by_title

DEFAULT_MUSIC_MODEL = "acestep_v1.5_xl_turbo_bf16.safetensors"
DEFAULT_FOLEY_MODEL = "hunyuanvideo_foley_fp8_e4m3fn.safetensors"


def _n(wf, title):
    return find_node_by_title(wf, title)[1]


def resolved_model(manifest, mode="music", model=None):
    """The audio model build() will load for this mode: explicit override, else the brand's
    foley_model/music_model, else the mode's DEFAULT_*. Single source of truth shared by build()
    and the reproducibility sidecar (generate.py reads this rather than re-deriving the chain)."""
    a = manifest.audio
    if mode == "foley":
        return model or a.foley_model or DEFAULT_FOLEY_MODEL
    return model or a.music_model or DEFAULT_MUSIC_MODEL


def _load(repo_root, name):
    p = Path(repo_root) / "workflows" / "templates" / name
    return deepcopy(json.loads(p.read_text(encoding="utf-8")))


def _build_music(repo_root, manifest, *, positive, seed, duration=None, bpm=None,
                 keyscale=None, model=None, **opts) -> dict:
    a = manifest.audio
    model = resolved_model(manifest, "music", model)
    duration = duration if duration is not None else a.music_duration
    bpm = bpm if bpm is not None else a.music_bpm
    keyscale = keyscale or a.music_keyscale
    wf = _load(repo_root, "brand-audio-music.json")
    _n(wf, "brand:unet")["inputs"]["unet_name"] = model
    enc = _n(wf, "brand:tags")["inputs"]
    enc["tags"] = positive
    enc["seed"] = seed
    enc["duration"] = duration
    enc["bpm"] = bpm
    enc["keyscale"] = keyscale
    _n(wf, "brand:sampler")["inputs"]["seed"] = seed
    _n(wf, "brand:latent")["inputs"]["seconds"] = duration
    return wf


def _build_foley(repo_root, manifest, *, positive, negative, seed, watermark=False,
                 from_video=None, frame_rate=None, duration=None, fps=None, model=None,
                 watermark_logo=None, logo_px=None, width=None, height=None, **opts) -> dict:
    a = manifest.audio
    if not from_video:
        raise ValueError("foley requires from_video")
    model = resolved_model(manifest, "foley", model)
    frame_rate = frame_rate if frame_rate is not None else 25.0
    duration = duration if duration is not None else 5.0
    fps = fps if fps is not None else frame_rate
    wf = _load(repo_root, "brand-audio-foley.json")
    _n(wf, "brand:load_video")["inputs"]["file"] = from_video
    _n(wf, "brand:foley_model")["inputs"]["model_name"] = model
    f = _n(wf, "brand:foley")["inputs"]
    f["prompt"] = positive
    f["negative_prompt"] = negative or a.foley_negative
    f["frame_rate"] = frame_rate
    f["duration"] = duration
    f["cfg_scale"] = a.foley_cfg
    f["steps"] = a.foley_steps
    f["seed"] = seed
    _n(wf, "brand:create_video")["inputs"]["fps"] = fps
    if watermark:
        from .watermark import inject_foley_watermark
        inject_foley_watermark(wf, manifest=manifest, logo_name=watermark_logo,
                               canvas=(width or 768, height or 512), logo_px=logo_px)
    return wf


def build(repo_root, manifest, *, positive, negative="", seed, watermark=False,
          mode="music", **opts) -> dict:
    if mode == "foley":
        return _build_foley(repo_root, manifest, positive=positive, negative=negative,
                            seed=seed, watermark=watermark, **opts)
    # music: ACE-Step has no text negative and no visual canvas, so `negative` and
    # `watermark` are intentionally not applied (generate.py also gates watermark off here).
    return _build_music(repo_root, manifest, positive=positive, seed=seed, **opts)

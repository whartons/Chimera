"""Fill the audio templates from a manifest + args, by title. Dispatches on `mode`:

- music: **Stable Audio 3 Medium** (default; won the 2026-10 listening comparison) with the official
  graph's Qwen3.5-2B prompt enhancer, or **ACE-Step 1.5** (`model="acestep"`, e.g. for songs with vocals).
- sfx: Stable Audio 3 with the enhancer's sound-effects mode (stingers, whooshes, UI and alert sounds).
- foley: HunyuanVideo-Foley (video -> synced SFX). LOCAL ONLY — uses ONLY the registered HunyuanFoley
  nodes + safetensors weights, never the pack's bundled CLI scripts (torch.load pickle-RCE)."""
from __future__ import annotations
from .nodes import load_template as _load, node as _n

SA3_MODEL = "stable_audio_3_medium.safetensors"
ACESTEP_MODEL = "acestep_v1.5_xl_turbo_bf16.safetensors"
DEFAULT_MUSIC_MODEL = SA3_MODEL
DEFAULT_FOLEY_MODEL = "hunyuanvideo_foley_fp8_e4m3fn.safetensors"
ALIASES = {"sa3": SA3_MODEL, "stable-audio-3": SA3_MODEL, "acestep": ACESTEP_MODEL, "ace-step": ACESTEP_MODEL}
SFX_DURATION = 4.0      # seconds, when --duration isn't given (a sound effect, not a track)
_SA3_MODE = {"music": "Music", "sfx": "SFX"}   # the enhancer's system prompt per Chimera mode


def canonical(name):
    """An audio model short name -> its file name; file names (and unknown names) pass through."""
    return ALIASES.get((name or "").lower(), name)


def is_sa3(model_file):
    return "stable_audio" in (model_file or "").lower()


def resolved_model(manifest, mode="music", model=None):
    """The audio model build() will load for this mode: explicit override, else the brand's
    foley_model/music_model, else the mode's default (short names resolved). sfx is Stable Audio 3's
    sound-effects mode, so it ignores the brand's music model. Single source of truth shared by build()
    and the reproducibility sidecar (generate.py reads this rather than re-deriving the chain)."""
    a = manifest.audio
    if mode == "foley":
        return model or a.foley_model or DEFAULT_FOLEY_MODEL
    if mode == "sfx":
        return canonical(model or SA3_MODEL)
    return canonical(model or a.music_model or DEFAULT_MUSIC_MODEL)


def _build_sa3(repo_root, manifest, *, positive, seed, mode="music", duration=None, bpm=None,
               keyscale=None, model=None, **opts) -> dict:
    a = manifest.audio
    if duration is None:
        duration = a.music_duration if mode == "music" else SFX_DURATION
    brief = positive
    if mode == "music":   # SA3 has no BPM/key inputs: explicit values (not the ACE-tuned brand defaults) join the brief
        brief = ", ".join(p for p in (positive, f"{bpm} BPM" if bpm else "",
                                      f"in {keyscale}" if keyscale else "") if p)
    wf = _load(repo_root, "brand-audio-sa3.json")
    _n(wf, "brand:ckpt")["inputs"]["ckpt_name"] = model
    _n(wf, "brand:prompt")["inputs"]["value"] = brief
    _n(wf, "brand:mode")["inputs"]["choice"] = _SA3_MODE[mode]
    _n(wf, "brand:length_text")["inputs"]["replace"] = f"{duration:g}"   # the enhancer sizes the prompt to it
    _n(wf, "brand:latent")["inputs"]["seconds"] = duration
    _n(wf, "brand:sampler")["inputs"]["seed"] = seed
    _n(wf, "brand:enhancer")["inputs"]["sampling_mode.seed"] = seed      # deterministic rewrite for replay
    _n(wf, "brand:save")["inputs"]["filename_prefix"] = f"audio/brand_{mode}"
    return wf


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
    if mode not in _SA3_MODE:
        raise ValueError(f"unknown audio mode {mode!r}; expected music, sfx or foley")
    # music / sfx have no visual canvas, so `watermark` is not applied (generate.py also gates it off);
    # neither model takes a brand negative (ACE-Step zeroes it; SA3's negative stays empty).
    model = resolved_model(manifest, mode, opts.pop("model", None))
    if is_sa3(model):
        return _build_sa3(repo_root, manifest, positive=positive, seed=seed, mode=mode, model=model, **opts)
    if mode == "sfx":
        raise ValueError("audio --mode sfx is Stable Audio 3's sound-effects mode: drop --model "
                         f"({model} makes music)")
    return _build_music(repo_root, manifest, positive=positive, seed=seed, model=model, **opts)

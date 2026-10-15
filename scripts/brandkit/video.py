"""Fill a brand video (image-to-video) template from a manifest + render args, by title. Two families:

- **Wan 2.2 14B** (default): fast 4-step image-to-video (lightx2v LoRAs), `quality="full"` for the 20-step
  path, and `camera=<pose>` for Fun Camera moves (a locked "static" camera, pans, zooms, rotations).
  Silent: add sound with `audio --mode foley --from-video`. Native 16 fps / 81 frames.
- **LTX-2.3** (`model="ltx23"`): built-in synced audio. LOCAL ONLY — uses the in-graph
  LTXAVTextEncoderLoader (gemma), never the cloud encoder. In the 2026-10 review it always added a camera
  push-in or pan and drifted a face's identity, which is why Wan became the default."""
from __future__ import annotations
from .nodes import assert_free_ids, find_node_by_title, load_template, node as _n

LTX23_MODEL = "ltx-2.3-22b-dev-nvfp4.safetensors"
# Wan 2.2 runs two experts (high-noise, then low-noise). The HIGH file names the model (what --model,
# brand video.model and the sidecar use); the low file is its pair.
WAN22_I2V = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
WAN22_CAMERA = "wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors"
_WAN_LOW = {WAN22_I2V: "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
            WAN22_CAMERA: "wan2.2_fun_camera_low_noise_14B_fp8_scaled.safetensors"}
DEFAULT_MODEL = WAN22_I2V
ALIASES = {"wan22": WAN22_I2V, "wan2.2": WAN22_I2V, "wan22-camera": WAN22_CAMERA,
           "ltx23": LTX23_MODEL, "ltx-2.3": LTX23_MODEL}
# --camera names -> WanCameraEmbedding camera_pose values
CAMERA_POSES = {"static": "Static", "pan-up": "Pan Up", "pan-down": "Pan Down", "pan-left": "Pan Left",
                "pan-right": "Pan Right", "zoom-in": "Zoom In", "zoom-out": "Zoom Out",
                "rotate-ccw": "Anti Clockwise (ACW)", "rotate-cw": "ClockWise (CW)"}
# Wan's native clip: 81 frames at 16 fps (5 s). The brand video: length/fps defaults are LTX's.
WAN_LENGTH, WAN_FPS = 81, 16
# quality -> (steps, cfg, high->low switch step). fast = the lightx2v 4-step LoRAs; full = 20 steps.
_WAN_QUALITY = {"fast": (4, 1.0, 2), "full": (20, 3.5, 10)}
# LTX 2x spatial latent upscaler for the opt-in video --upscale pass (built-in option of
# LatentUpscaleModelLoader; in models/latent_upscale_models/).
DEFAULT_VIDEO_UPSCALE_MODEL = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
# Appended to the brand negative for video: suppress frozen/static frames, force audio, and
# suppress the i2v artifacts that read as "unrealistic" (warping/morphing/jitter). The brand
# negative is image-oriented and lacks these; the validated render relied on the first two.
VIDEO_NEG_EXTRA = ("still frame, frozen video, music, silence, morphing, warping, melting, "
                   "distortion, deformation, wobbling, jitter, flicker, rubbery motion, "
                   "object disintegrating, inconsistent geometry")


def canonical(name):
    """A video model short name -> its file name; file names (and unknown names) pass through."""
    return ALIASES.get((name or "").lower(), name)


def is_wan(model_file):
    return (model_file or "").lower().startswith("wan")


def resolved_model(manifest, model=None, camera=None):
    """The video model file build() will actually load: explicit override, else the brand's
    video.model, else DEFAULT_MODEL (short names resolved); a camera move selects Wan's Fun Camera
    model unless another model was asked for. The single source of truth shared by build() and the
    reproducibility sidecar (generate.py reads this rather than re-deriving the chain)."""
    if camera and not (model or manifest.video.model):
        return WAN22_CAMERA
    chosen = canonical(model or manifest.video.model or DEFAULT_MODEL)
    return WAN22_CAMERA if camera and chosen == WAN22_I2V else chosen


def _snap16(n):
    return max(16, int(n) // 16 * 16)


def resolved_settings(manifest, *, model=None, camera=None, quality=None, length=None, fps=None,
                      width=None, height=None, audio=None):
    """Every resolved knob of a render: explicit value, else the family default. Shared by build() and
    the sidecar so a replay reproduces the clip. LTX falls back to the brand video: block (its
    length/fps/audio were tuned for LTX); Wan to its native 81 frames at 16 fps, sizes snapped to
    multiples of 16, silent, `fast` quality for plain image-to-video and `full` for camera moves (the
    4-step Fun Camera kept the camera locked but cut the scene's motion to about a third)."""
    v = manifest.video
    mfile = resolved_model(manifest, model, camera)
    if not is_wan(mfile):
        return {"model": mfile, "width": width or v.width, "height": height or v.height,
                "length": length or v.length, "fps": fps or v.fps,
                "audio": v.audio if audio is None else audio, "quality": None, "camera": None}
    return {"model": mfile, "width": _snap16(width or v.width), "height": _snap16(height or v.height),
            "length": length or WAN_LENGTH, "fps": fps or WAN_FPS, "audio": False,
            "quality": quality or ("full" if camera else "fast"), "camera": camera}


def resolved_upscale_model(manifest, upscale_model=None):
    """The spatial latent upscaler the --upscale pass will load: override, else the brand's
    video.upscale_model, else DEFAULT_VIDEO_UPSCALE_MODEL. Shared by build() and the sidecar."""
    return upscale_model or manifest.video.upscale_model or DEFAULT_VIDEO_UPSCALE_MODEL


def _inject_video_upscale(wf, model_name):
    """Splice the LTX 2x spatial latent upscaler just before brand:decode: take over whatever
    feeds brand:decode's `samples` (the separated video latent) and the decode's VAE, run them
    through LTXVLatentUpsampler, and rewire decode to the upscaled latent. Latent-space (temporally
    coherent), so it precedes the pixel-space watermark. Ids 70/71."""
    assert_free_ids(wf, "70", "71")
    _, decode = find_node_by_title(wf, "brand:decode")
    src = decode["inputs"]["samples"]      # current video-latent source, e.g. ["22",0]
    vae = decode["inputs"]["vae"]          # the video VAE, e.g. ["1",2]
    wf["70"] = {"class_type": "LatentUpscaleModelLoader", "_meta": {"title": "brand:video_upscale_model"},
                "inputs": {"model_name": model_name}}
    wf["71"] = {"class_type": "LTXVLatentUpsampler", "_meta": {"title": "brand:video_upscale"},
                "inputs": {"samples": src, "upscale_model": ["70", 0], "vae": vae}}
    decode["inputs"]["samples"] = ["71", 0]
    return wf


def _build_ltx(repo_root, manifest, positive, negative, seed, from_image, r, upscale, upscale_model):
    width, height, length, fps = r["width"], r["height"], r["length"], r["fps"]
    wf = load_template(repo_root, "brand-video-i2v.json")
    for t in ("brand:ckpt", "brand:encoder", "brand:audio_vae"):
        _n(wf, t)["inputs"]["ckpt_name"] = r["model"]
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
    if not r["audio"]:
        _n(wf, "brand:create_video")["inputs"].pop("audio", None)
    if upscale:
        _inject_video_upscale(wf, resolved_upscale_model(manifest, upscale_model))
    return wf


def _build_wan(repo_root, positive, negative, seed, from_image, r):
    camera = r["camera"]
    wf = load_template(repo_root, "brand-video-wan22-camera.json" if camera else "brand-video-wan22-i2v.json")
    _n(wf, "brand:unet_high")["inputs"]["unet_name"] = r["model"]
    _n(wf, "brand:unet_low")["inputs"]["unet_name"] = _WAN_LOW.get(r["model"],
                                                                     r["model"].replace("high_noise", "low_noise"))
    _n(wf, "brand:load_image")["inputs"]["image"] = from_image
    _n(wf, "brand:positive")["inputs"]["text"] = positive
    neg = _n(wf, "brand:negative")["inputs"]
    neg["text"] = ", ".join(s for s in (negative, neg["text"]) if s)   # brand negative + Wan's own list
    size = _n(wf, "brand:camera" if camera else "brand:i2v")["inputs"]
    size["width"], size["height"], size["length"] = r["width"], r["height"], r["length"]
    if camera:
        size["camera_pose"] = CAMERA_POSES[camera]
    _n(wf, "brand:create_video")["inputs"]["fps"] = r["fps"]
    steps, cfg, split = _WAN_QUALITY[r["quality"]]
    if r["quality"] == "full":   # the 20-step path samples the bare experts, without the 4-step LoRAs
        for side in ("high", "low"):
            lora_id, lora = find_node_by_title(wf, f"brand:lora_{side}")
            _n(wf, f"brand:model_sampling_{side}")["inputs"]["model"] = lora["inputs"]["model"]
            del wf[lora_id]
    hi, lo = _n(wf, "brand:sampler_high")["inputs"], _n(wf, "brand:sampler_low")["inputs"]
    hi.update(noise_seed=seed, steps=steps, cfg=cfg, end_at_step=split)
    lo.update(steps=steps, cfg=cfg, start_at_step=split)
    return wf


def build(repo_root, manifest, *, positive, negative, seed, watermark=False,
          from_image=None, length=None, fps=None, audio=None, width=None, height=None,
          model=None, camera=None, quality=None, watermark_logo=None, logo_px=None,
          upscale=False, upscale_model=None, **opts) -> dict:
    if not from_image:
        raise ValueError("video i2v requires from_image")
    if camera is not None and camera not in CAMERA_POSES:
        raise ValueError(f"unknown camera move {camera!r}; expected one of: {', '.join(CAMERA_POSES)}")
    if quality is not None and quality not in _WAN_QUALITY:
        raise ValueError(f"unknown quality {quality!r}; expected one of: {', '.join(_WAN_QUALITY)}")
    r = resolved_settings(manifest, model=model, camera=camera, quality=quality, length=length, fps=fps,
                          width=width, height=height, audio=audio)   # audio None = brand video.audio (LTX)
    if is_wan(r["model"]):
        if upscale:
            raise ValueError("video --upscale is LTX's latent upscaler: render with --model ltx23, or ask Wan for "
                             "the size you want with --width/--height")
        wf = _build_wan(repo_root, positive, negative, seed, from_image, r)
    else:
        if camera:
            raise ValueError("camera moves need Wan 2.2's Fun Camera model: drop --model ltx23 (or pass "
                             "--model wan22)")
        wf = _build_ltx(repo_root, manifest, positive, negative, seed, from_image, r, upscale, upscale_model)
    if watermark:
        from .watermark import inject_video_watermark
        # The LTX spatial upscaler is fixed 2x, so the decoded frames are 2x the base canvas;
        # the watermark places its logo by canvas geometry, so it must use the doubled canvas.
        wm_canvas = (r["width"] * 2, r["height"] * 2) if upscale else (r["width"], r["height"])
        inject_video_watermark(wf, manifest=manifest, logo_name=watermark_logo,
                               canvas=wm_canvas, logo_px=logo_px)
    return wf

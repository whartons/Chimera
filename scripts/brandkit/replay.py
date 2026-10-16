"""Reproducibility-sidecar input resolution + replay reconstruction (pure, no I/O).

Owns the CLI-inputs ↔ sidecar contract for the generate CLI: which args are harvested into a
sidecar's `inputs` block, how the graph's ACTUAL model/upscaler/dims are resolved through the
fillers' own resolvers (single source of truth — the sidecar can never drift from the built
graph), and how a schema-2 sidecar reconstructs the argparse.Namespace `run()` expects.
Lives beside sidecar.py, which owns the sidecar's on-disk shape (build_meta et al.)."""
from __future__ import annotations
import argparse

from . import audio as audio_filler
from . import threed as threed_filler
from . import video as video_filler
from . import workflow as image_filler
from .comfy import DEFAULT_URL as DEFAULT_COMFY_URL
from .outputs import _MEDIA_DIRS, brand_name_ok, unsafe_path as _unsafe_path
from .sidecar import graph_prompts, graph_signature, graph_values

# CLI args harvested into the sidecar `inputs` dict (sidecar.relevant_inputs then keeps the
# modality-relevant subset). Must remain a superset of every sidecar._INPUT_KEYS value, minus
# "format" which is injected separately as the resolved fmt; tests/test_sidecar.py guards this.
SIDECAR_INPUT_KEYS = ("subject", "asset", "variant", "model", "from_image", "from_video",
                      "length", "fps", "width", "height", "audio", "duration", "bpm",
                      "keyscale", "lyrics", "octree", "upscale", "upscale_model", "camera", "quality")
_FILE_INPUTS = ("asset", "from_image", "from_video")
# What a replayable sidecar may name (generate.py's subcommands and --mode choices; a test keeps them in
# step). The mode becomes part of the output file name, and the inputs are uploaded to ComfyUI.
REPLAY_MODES = {"image": ("txt2img", "logo", "product", "relight"), "video": ("i2v",),
                "audio": ("music", "sfx", "foley"), "3d": ("image",)}
_INPUT_KIND = {"asset": "images", "from_image": "images", "from_video": "video"}


def _file_name(value) -> str:
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def resolve_model_used(args, m):
    """The model filename the graph ACTUALLY loaded — asked of the filler that decided it, so the
    sidecar can never drift from the built graph (single source of truth, B6). Pure."""
    if args.modality == "video":
        return video_filler.resolved_model(m, getattr(args, "model", None), getattr(args, "camera", None))
    if args.modality == "audio":
        return audio_filler.resolved_model(m, args.mode, getattr(args, "model", None))
    if args.modality == "3d":
        return threed_filler.resolved_model(m, args.model)
    # Z-Image's variant determines the actual model file (product -> base, etc.).
    return image_filler.resolve_image_model(args.mode, args.variant, args.model or m.defaults.model)


def resolve_sidecar_inputs(args, m, fmt=None):
    """The modality-relevant `inputs` block for the reproducibility sidecar (pure). Harvests the
    CLI inputs, then — only when --upscale is on — records the RESOLVED upscaler via the filler's
    own resolver (single source of truth with the graph; off renders stay clean), and the resolved
    3d export format."""
    inputs = {k: getattr(args, k, None) for k in SIDECAR_INPUT_KEYS}
    for k in _FILE_INPUTS:   # sidecars get shared and committed: no local folder layout or user name
        if inputs.get(k) and _unsafe_path(inputs[k]):
            inputs[k] = _file_name(inputs[k])
    if args.modality == "image" and image_filler.family(resolve_model_used(args, m)) != "zimage":
        inputs["variant"] = None   # only Z-Image reads it
    if args.modality == "3d" and threed_filler.family(threed_filler.resolved_model(m, args.model)) != "hunyuan3d":
        inputs["octree"] = None    # only Hunyuan3D reads it
    if args.modality in ("image", "video"):
        resolver = (image_filler.resolved_upscale_model if args.modality == "image"
                    else video_filler.resolved_upscale_model)
        inputs["upscale"] = True if args.upscale else None
        inputs["upscale_model"] = resolver(m, args.upscale_model) if args.upscale else None
    if args.modality == "video":
        # record the RESOLVED settings (the filler's own resolver: CLI flag, else the family default —
        # the brand video: block for LTX, Wan's native clip for Wan) so replay reproduces the render
        # even if the brand.yaml or a default changes later
        r = video_filler.resolved_settings(
            m, model=getattr(args, "model", None), camera=getattr(args, "camera", None),
            quality=getattr(args, "quality", None), length=args.length, fps=args.fps,
            width=args.width, height=args.height, audio=args.audio)
        for k in ("length", "fps", "width", "height", "audio", "quality", "camera"):
            inputs[k] = r[k]
    if args.modality == "3d":
        inputs["format"] = fmt
    return inputs


def args_from_sidecar(data, *, seed=None, comfy_output_dir=None, comfy_url=None, model=None):
    """Reconstruct the full argparse.Namespace that run() expects from a schema-2 sidecar dict,
    plus optional overrides. Pure (no I/O), stdlib-only.

    Schema-1 sidecars predate the enriched `inputs` block and cannot be reconstructed, so we
    refuse them rather than guess. An explicit seed override wins over the recorded seed; with
    neither override the recorded seed is reused. The model is PINNED: an explicit `model` override
    (replay --model: re-run old work on a newer model) wins, else the render's own --model override,
    else the model the render actually loaded — so a later brand pin or Chimera default change can't
    silently swap it. run() then checks the rest for drift (replay_drift).

    Sidecars get shared (the example brand's are in the repo), so replay trusts none of their routing: it
    renders on the local default ComfyUI unless `comfy_url` is passed, and refuses a brand that isn't a
    folder name or a file input that is absolute or climbs with '..' (a crafted sidecar used those to upload
    any local file to a URL of its choosing, 2026-10 audit)."""
    if data.get("schema", 1) < 2:
        raise ValueError("sidecar is schema-1 (pre-enriched); replay needs schema>=2 — "
                         "re-render once to upgrade it.")
    if data.get("kind") == "agent-run":
        raise ValueError("this is an agent-run sidecar (auto_generate.py), not a "
                         "replayable render sidecar")
    if data.get("kind") == "render":
        raise ValueError("render sidecars aren't replayable yet (Phase 2 produces them, "
                         "replay support is a later phase)")
    if data.get("kind") == "cad":
        raise ValueError("cad sidecars aren't replayable (headless FreeCAD geometry, not a "
                         "ComfyUI render)")
    modality = data["modality"]
    inp = data.get("inputs") or {}
    brand = data["brand"]
    if modality not in REPLAY_MODES:
        raise ValueError(f"modality {modality!r} isn't one replay renders ({', '.join(REPLAY_MODES)})")
    if data.get("mode") not in REPLAY_MODES[modality]:
        # the mode names the output file: a crafted '../..' mode wrote outside outputs/ (2026-10 review)
        raise ValueError(f"mode {data.get('mode')!r} isn't a {modality} mode ({', '.join(REPLAY_MODES[modality])})")
    if seed is None and (not isinstance(data.get("seed"), int) or isinstance(data.get("seed"), bool)):
        raise ValueError(f"seed {data.get('seed')!r} isn't a whole number (pass --seed to choose one)")
    if brand is not None and not brand_name_ok(brand):
        raise ValueError(f"brand {brand!r} is not a brand folder name")
    if not isinstance(inp, dict):
        raise ValueError("the sidecar's inputs block isn't a mapping")
    for k in _FILE_INPUTS:
        if inp.get(k) is None:
            continue
        if _unsafe_path(inp[k]):
            raise ValueError(f"inputs.{k} {inp[k]!r} is not a plain relative file name; put the file in the "
                             "brand folder (or the current folder, brandless) and name it in the sidecar")
        if "." + str(inp[k]).rsplit(".", 1)[-1].lower() not in _MEDIA_DIRS[_INPUT_KIND[k]]:
            # replay uploads it to ComfyUI: a sidecar naming '.env' would have sent that file
            kind = "an image" if _INPUT_KIND[k] == "images" else "a video"
            raise ValueError(f"inputs.{k} {inp[k]!r} isn't {kind} file")
    ns = argparse.Namespace(
        modality=modality,
        mode=data.get("mode"),
        brand=brand,
        seed=seed if seed is not None else data.get("seed"),
        comfy_url=comfy_url or DEFAULT_COMFY_URL,   # never the sidecar's (see above)
        comfy_output_dir=comfy_output_dir,  # host path, not stored; only relocates if passed
        watermark=bool(data.get("watermark", False)),
        out_name=None, timeout=None, free_before=None,
        subject=inp.get("subject"),
        asset=inp.get("asset"),
        variant=inp.get("variant"),
        # the render's own --model override is a family selector (Z-Image's variant then picks the
        # file), so it outranks the top-level resolved file; that file pins renders made on a default
        # (the Z-Image file names map back to their variant, so either way the same file re-resolves).
        model=model or inp.get("model") or data.get("model"),
        upscale=bool(inp.get("upscale")),       # image: re-apply the upscale pass on replay
        upscale_model=inp.get("upscale_model"),
        from_image=inp.get("from_image"),
        from_video=inp.get("from_video"),
        length=inp.get("length"),
        fps=inp.get("fps"),
        width=inp.get("width"),
        height=inp.get("height"),
        audio=inp.get("audio", True),  # only video records `audio`; True matches the vid --audio default
        duration=inp.get("duration"),
        bpm=inp.get("bpm"),
        keyscale=inp.get("keyscale"),
        lyrics=inp.get("lyrics"),
        camera=inp.get("camera"),          # video (Wan Fun Camera) move, if any
        quality=inp.get("quality"),        # video (Wan) fast / full
        octree=inp.get("octree"),
        format=inp.get("format") or data.get("format"),
    )
    return _clear_family_settings(ns, data.get("model"), model) if model else ns


def _clear_family_settings(ns, recorded, override):
    """A cross-family `replay --model` must not carry the old family's settings into the new one. The
    record holds RESOLVED values: Wan's clip (81 frames at 16 fps, silent) or LTX's (97 at 25 fps with
    audio, perhaps the 2x upscaler), a Z-Image variant, a Hunyuan3D octree. Clear them so the new family's
    defaults apply: an LTX clip replayed on Wan played about 1.56x fast (2026-10 review)."""
    if ns.modality == "video":
        if video_filler.is_wan(video_filler.canonical(override)) != video_filler.is_wan(recorded):
            ns.length = ns.fps = ns.audio = ns.quality = ns.camera = ns.upscale_model = None
            ns.upscale = False
    elif ns.modality == "image":
        if image_filler.family(override) != image_filler.family(recorded):
            ns.variant = None
    elif ns.modality == "3d":
        if threed_filler.family(threed_filler.canonical(override)) != threed_filler.family(recorded):
            ns.octree = None
    return ns


def _clip(text, n=160):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 3] + "..."


def replay_drift(expect, *, model, wf, modality, mode, model_override=None):
    """What a replay would render differently from the recorded one (pure). `expect` is the sidecar,
    `model`/`wf` the replay's resolved model and built graph. Returns human-readable lines; [] means
    the replay reproduces the record. With a model override (replay --model, a deliberate re-run on
    a newer model) the model, graph structure, settings and negative change by design (each family
    builds its own negative: Z-Image none, LTX and Wan their own lists), so only the prompt text is
    compared; an override naming the recorded model is no override. Older sidecars without a
    provenance block get the model + prompt checks only."""
    out = []
    recorded = expect.get("model")
    overridden = model_override is not None and model != recorded
    if not overridden and recorded and model != recorded:
        out.append(f"model: recorded {recorded}, would now load {model}")
    pos, neg = graph_prompts(wf, modality, mode)
    texts = [("prompt", pos, expect.get("prompt"))]
    if not overridden:
        texts.append(("negative", neg, expect.get("negative")))
    for label, now, then in texts:
        if then is not None and now != then:
            out.append(f"{label} changed\n      recorded: {_clip(then)}\n      now:      {_clip(now)}")
    if not overridden:
        prov = expect.get("provenance") or {}
        if prov.get("graph_signature") and graph_signature(wf) != prov["graph_signature"]:
            out.append("graph structure changed (a Chimera template update, or a brand change that adds or "
                       "removes nodes, such as a LoRA)")
        if prov.get("graph_values") and graph_values(wf, modality, mode) != prov["graph_values"]:
            out.append("render settings changed (e.g. the brand's size, steps, guidance, LoRA or watermark)")
    return out

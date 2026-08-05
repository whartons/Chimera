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

# CLI args harvested into the sidecar `inputs` dict (sidecar.relevant_inputs then keeps the
# modality-relevant subset). Must remain a superset of every sidecar._INPUT_KEYS value, minus
# "format" which is injected separately as the resolved fmt; tests/test_sidecar.py guards this.
SIDECAR_INPUT_KEYS = ("subject", "asset", "variant", "model", "from_image", "from_video",
                      "length", "fps", "width", "height", "audio", "duration", "bpm",
                      "keyscale", "octree", "upscale", "upscale_model")


def resolve_model_used(args, m):
    """The model filename the graph ACTUALLY loaded — asked of the filler that decided it, so the
    sidecar can never drift from the built graph (single source of truth, B6). Pure."""
    if args.modality == "video":
        return video_filler.resolved_model(m)
    if args.modality == "audio":
        return audio_filler.resolved_model(m, args.mode)
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
    if args.modality in ("image", "video"):
        resolver = (image_filler.resolved_upscale_model if args.modality == "image"
                    else video_filler.resolved_upscale_model)
        inputs["upscale"] = True if args.upscale else None
        inputs["upscale_model"] = resolver(m, args.upscale_model) if args.upscale else None
    if args.modality == "video":
        # record RESOLVED dims/audio (CLI flag, else brand video: block, else filler default) so
        # replay reproduces the render even if the brand.yaml changes later
        v = m.video
        inputs["length"] = args.length or v.length
        inputs["fps"] = args.fps or v.fps
        inputs["width"] = args.width or v.width
        inputs["height"] = args.height or v.height
        inputs["audio"] = v.audio if args.audio is None else args.audio
    if args.modality == "3d":
        inputs["format"] = fmt
    return inputs


def args_from_sidecar(data, *, seed=None, comfy_output_dir=None, comfy_url=None):
    """Reconstruct the full argparse.Namespace that run() expects from a schema-2 sidecar dict,
    plus optional overrides. Pure (no I/O), stdlib-only.

    Schema-1 sidecars predate the enriched `inputs` block and cannot be reconstructed, so we
    refuse them rather than guess. An explicit seed override wins over the recorded seed; with
    neither override the recorded seed is reused, giving an identical render."""
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
    inp = data.get("inputs", {})
    return argparse.Namespace(
        modality=modality,
        mode=data.get("mode"),
        brand=data["brand"],
        seed=seed if seed is not None else data.get("seed"),
        comfy_url=comfy_url or data.get("comfy_url") or DEFAULT_COMFY_URL,
        comfy_output_dir=comfy_output_dir,  # host path, not stored; only relocates if passed
        watermark=bool(data.get("watermark", False)),
        out_name=None, timeout=None, free_before=None,
        subject=inp.get("subject"),
        asset=inp.get("asset"),
        variant=inp.get("variant"),
        # the user's --model OVERRIDE (absent when they used the brand default); run()
        # re-resolves the actual model file, so we must NOT use the top-level resolved model.
        model=inp.get("model"),
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
        octree=inp.get("octree"),
        format=inp.get("format") or data.get("format"),
    )

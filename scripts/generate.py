#!/usr/bin/env python3
"""Unified brand-aware generator. One entrypoint, per-modality subcommands sharing the
brandkit core: manifest -> prompt -> filler (builds the graph, injects opt-in watermark)
-> queue to ComfyUI -> route output into brands/<brand>/outputs/ (+ reproducibility sidecar).

  python scripts/generate.py image --brand example-brand --subject "an armored rover" \
      --mode txt2img [--watermark] [--seed 7] [--comfy-output-dir <dir>] [--asset primary.png]

The `replay` subcommand re-runs a render from its schema-2 sidecar JSON, closing the
reproducibility loop:

  python scripts/generate.py replay brands/example-brand/outputs/video/<name>.json \
      [--seed 999] [--comfy-url <url>] [--comfy-output-dir <dir>]

Replay reconstructs the CLI inputs from the sidecar's `inputs` block and feeds them back
through the SAME prepare -> filler -> queue -> route -> sidecar flow as a normal render. It
re-derives the prompt from the recorded `subject` via build_prompt/build_audio_prompt (it does
NOT replay the stored prompt string verbatim), so with an unchanged brand.yaml it reproduces the
identical prompt/seed/model. The stored prompt/negative stay as the human-readable as-rendered
record. Schema-1 (pre-enriched) sidecars lack `inputs` and cannot be replayed -- re-render once
to upgrade them.
"""
import argparse, json, random, struct, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.brandkit.manifest import load_manifest, default_manifest
from scripts.brandkit.prompt import build_prompt, build_audio_prompt
from scripts.brandkit import workflow as image_filler
from scripts.brandkit import video as video_filler
from scripts.brandkit import audio as audio_filler
from scripts.brandkit import threed as threed_filler
from scripts.brandkit.comfy import ComfyClient
from scripts.brandkit.outputs import route_output, select_output, NoOutputError, write_sidecar
from scripts.brandkit.sidecar import build_meta
import tempfile, shutil
from scripts.brandkit import blender as blender_runner
from scripts.brandkit import freecad as freecad_runner
from scripts.brandkit.sidecar import build_render_meta, build_cad_meta
from scripts.brandkit import finalize as finalize_core

FILLERS = {"image": image_filler.build, "video": video_filler.build, "audio": audio_filler.build,
           "3d": threed_filler.build}
TIMEOUTS = {"image": 900, "video": 3600, "audio": 1800, "3d": 3600}
FREE_BEFORE_DEFAULT = {"image": False, "video": True, "audio": True, "3d": True}

RENDER_TIMEOUT = 1800
_TEMPLATE_FOR_MODE = {"mesh": "mesh_render.py", "comfy-scene": "comfy_to_scene.py",
                      "finish": "mesh_finish.py"}

FINALIZE_TIMEOUT = finalize_core.FINALIZE_TIMEOUT
_FINALIZE_TEMPLATE = finalize_core.FINALIZE_TEMPLATE

CAD_TIMEOUT = 600
_TEMPLATE_FOR_CAD = {"primitive": "primitive.py", "convert": "convert.py", "script": "script_exec.py"}
_CAD_FORMATS = ("step", "stl", "obj")
_SHAPE_DIMS = {
    "box": ("length", "width", "height"),
    "cylinder": ("radius", "height"),
    "cone": ("radius", "radius2", "height"),
    "sphere": ("radius",),
    "tube": ("radius", "inner_radius", "height"),
}
_MESH_EXTS = {".stl", ".obj"}
# source extensions the convert template can actually import (BREP family + mesh family)
_CONVERT_SRC_EXTS = {".step", ".stp", ".iges", ".igs", ".brep", ".stl", ".obj"}

# CLI args harvested into the sidecar `inputs` dict (sidecar.relevant_inputs then keeps the
# modality-relevant subset). Must remain a superset of every sidecar._INPUT_KEYS value, minus
# "format" which is injected separately as the resolved fmt; tests/test_sidecar.py guards this.
SIDECAR_INPUT_KEYS = ("subject", "asset", "variant", "model", "from_image", "from_video",
                      "length", "fps", "width", "height", "audio", "duration", "bpm",
                      "keyscale", "octree", "upscale", "upscale_model")


def _image_size(path):
    """(width, height) of a logo image, or None if it can't be determined. Uses Pillow when
    available (png/jpg/webp/bmp/tiff/gif); otherwise falls back to a PNG-header read so PNG logos
    still work with no third-party deps. None -> callers use a canvas-proportional geometry
    estimate (correct SIZE on-graph, only the corner offset is approximate)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except ImportError:
        pass                       # no Pillow -> PNG-header fallback below
    except Exception:
        return None                # Pillow present but the file isn't a readable image
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None                # not a PNG, or a truncated one -> approximate geometry
    return struct.unpack(">II", head[16:24])


def _add_common(sp):
    sp.add_argument("--brand", default=None,
                    help="optional brand (brands/<brand>/); omit to generate brandlessly -> outputs/")
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--comfy-url", default="http://127.0.0.1:8000")
    sp.add_argument("--comfy-output-dir", default=None)
    sp.add_argument("--watermark", action="store_true", help="stamp the brand logo (opt-in)")
    sp.add_argument("--out-name", default=None, help="(reserved; output is named <brand>_<mode>_<seed>)")
    sp.add_argument("--timeout", type=int, default=None)
    sp.add_argument("--free-before", dest="free_before", action="store_true", default=None)
    sp.add_argument("--no-free-before", dest="free_before", action="store_false")


def _resolve_asset(brand_dir, name, subdirs, ap, what):
    """Locate an input asset. With a brand, search its <subdirs>/ (current behavior). Brandless
    (brand_dir is None), treat `name` as a direct file path (absolute or relative to cwd). ap.error()s
    if `name` is empty or the file can't be found — returns a Path otherwise."""
    if not name:
        ap.error(f"{what} is required")
    if brand_dir is not None:
        p = next((brand_dir / d / name for d in subdirs if (brand_dir / d / name).exists()), None)
        if p is None:
            ap.error(f"{what} {name!r} not found under the brand in {'/, '.join(subdirs)}/")
        return p
    p = Path(name)
    if not p.exists():
        ap.error(f"{what} not found: {name} (give a file path; no --brand set)")
    return p


def _prepare_image(args, m, brand_dir, client, ap):
    fkw = {"mode": args.mode, "variant": args.variant, "model": args.model,
           "upscale": args.upscale,
           "upscale_model": args.upscale_model}  # raw; the filler resolves brand/default
    if args.mode == "relight":
        # relight (FLUX.2 ReferenceLatent edit): --asset is the source still to relight. Search the
        # usual input locations incl. prior renders; brandless -> treat --asset as a direct path.
        asset_path = _resolve_asset(brand_dir, args.asset,
                                    ("products", "references", "outputs/images"), ap, "relight --asset")
        fkw["asset"] = client.upload_image(asset_path)
    if args.mode in ("logo", "product"):
        subdir = "logos" if args.mode == "logo" else "products"
        asset_name = args.asset or (m.logo.default or "").split("/")[-1] or None
        asset_path = _resolve_asset(brand_dir, asset_name, (subdir,), ap, f"{args.mode} --asset")
        fkw["asset"] = client.upload_image(asset_path)
        if args.mode == "logo":
            sz = _image_size(asset_path)
            if sz:
                fkw["logo_px"] = (int(sz[0] * m.logo.scale), int(sz[1] * m.logo.scale))
            else:
                print(f"warning: could not read logo dimensions from {asset_path.name}; corner "
                      "placement will be approximate (install Pillow or use a PNG logo)",
                      file=sys.stderr)
    return fkw


def _prepare_video(args, m, brand_dir, client, ap):
    path = _resolve_asset(brand_dir, args.from_image, ("products", "references"), ap, "video --from-image")
    return {"from_image": client.upload_image(path),
            "length": args.length, "fps": args.fps, "audio": args.audio,
            "width": args.width, "height": args.height,
            "upscale": args.upscale,
            "upscale_model": args.upscale_model}  # raw; the filler resolves brand/default


def _probe_video(path):
    """Best-effort (fps, duration_s, width, height) via PyAV; (None,)*4 if PyAV is absent
    or the file has no readable video stream."""
    try:
        import av
    except ImportError:
        return None, None, None, None
    c = av.open(str(path))
    try:
        if not c.streams.video:                       # audio-only / no video track
            return None, None, None, None
        vs = c.streams.video[0]
        fr = float(vs.average_rate) if vs.average_rate else None  # None or 0 -> unknown
        frames = vs.frames or 0
        w, h = vs.codec_context.width, vs.codec_context.height
        dur = (frames / fr) if (frames and fr) else None
        return fr, dur, w, h
    finally:
        c.close()


def _prepare_audio(args, m, brand_dir, client, ap):
    if args.mode == "music":
        return {"mode": "music", "duration": args.duration, "bpm": args.bpm,
                "keyscale": args.keyscale}
    # foley: locate + upload the source video, probe its fps/duration/size
    # outputs/video/ first (media-type-routed location), then legacy flat outputs/, then sources
    path = _resolve_asset(brand_dir, args.from_video,
                          ("outputs/video", "outputs", "references", "products"), ap, "foley --from-video")
    fr, dur, w, h = _probe_video(path)
    frame_rate = args.fps or fr or 25.0
    duration = args.duration or dur or 5.0
    if (fr is None or dur is None) and (args.fps is None or args.duration is None):
        print(f"warning: could not probe {path.name}; using frame_rate={frame_rate} duration={duration}"
              " (pass --fps/--duration to override)", file=sys.stderr)
    return {"mode": "foley", "from_video": client.upload_video(path),
            "frame_rate": frame_rate, "duration": duration, "fps": frame_rate,
            "width": w or 768, "height": h or 512}


def _prepare_3d(args, m, brand_dir, client, ap):
    path = _resolve_asset(brand_dir, args.from_image,
                          ("products", "references", "outputs/images"), ap, "3d --from-image")
    return {"mode": args.mode, "from_image": client.upload_image(path),
            "octree": args.octree, "model": args.model}


def _supports_watermark(modality, mode):
    if modality == "image":
        return mode != "logo"
    if modality == "video":
        return True
    if modality == "audio":
        return mode == "foley"   # music has no visual canvas
    return False


def git_provenance(repo_root):
    """Best-effort short provenance of the pipeline repo at render time: the HEAD commit (short),
    suffixed `-dirty` if the working tree has uncommitted changes. None when it isn't a git repo or
    git is absent — so a tarball/non-git install still renders. Recorded in the sidecar so a render
    traces back to the exact pipeline code that produced it. Best-effort: never raises."""
    import subprocess
    try:
        rev = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if rev.returncode != 0:
            return None
        sha = rev.stdout.strip()
        st = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=5)
        return sha + ("-dirty" if st.stdout.strip() else "")
    except Exception:
        return None


def _resolve_model_used(args, m):
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


def _resolve_sidecar_inputs(args, m, fmt=None):
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
    if args.modality == "3d":
        inputs["format"] = fmt
    return inputs


PREPARE = {"image": _prepare_image, "video": _prepare_video, "audio": _prepare_audio,
           "3d": _prepare_3d}


def _args_from_sidecar(data, *, seed=None, comfy_output_dir=None, comfy_url=None):
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
        comfy_url=comfy_url or data.get("comfy_url") or "http://127.0.0.1:8000",
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


def run(args, repo_root, ap):
    if args.brand:
        brand_dir = repo_root / "brands" / args.brand
        m = load_manifest(brand_dir / "brand.yaml")
    else:
        brand_dir, m = None, default_manifest()   # brandless: neutral manifest, output -> outputs/
    seed = args.seed if args.seed is not None else random.randint(1, 2_000_000_000)
    if args.modality == "3d":
        pos, neg = "", ""
    elif args.modality == "audio":
        pos, neg = build_audio_prompt(m, args.subject, args.mode)
    else:
        pos, neg = build_prompt(m, args.subject)
    do_watermark = (args.watermark or m.watermark.enabled_default) and \
        _supports_watermark(args.modality, args.mode)
    if do_watermark and not args.brand:
        ap.error("--watermark needs a --brand (the logo comes from brands/<brand>/logos/)")
    client = ComfyClient(args.comfy_url)

    free_before = args.free_before if args.free_before is not None else FREE_BEFORE_DEFAULT[args.modality]
    if free_before:
        client.free()

    fkw = PREPARE[args.modality](args, m, brand_dir, client, ap)
    if do_watermark:
        logo_rel = (m.logo.default or "").split("/")[-1]
        logo_path = brand_dir / "logos" / logo_rel
        if not logo_path.exists():
            ap.error(f"--watermark needs a brand logo at brands/{args.brand}/logos/{logo_rel}")
        fkw["watermark_logo"] = client.upload_image(logo_path)
        sz = _image_size(logo_path)
        if sz:
            fkw["logo_px"] = (int(sz[0] * m.watermark.scale), int(sz[1] * m.watermark.scale))
        else:
            print(f"warning: could not read watermark logo dimensions from {logo_rel}; corner "
                  "placement will be approximate (install Pillow or use a PNG logo)",
                  file=sys.stderr)

    wf = FILLERS[args.modality](repo_root, m, positive=pos, negative=neg, seed=seed,
                               watermark=do_watermark, **fkw)
    pid = client.queue_prompt(wf)
    print(f"queued {pid} (modality={args.modality} brand={args.brand or '-'} mode={args.mode} seed={seed})")
    timeout = args.timeout or TIMEOUTS[args.modality]
    try:
        client.wait(pid, max_wait=timeout)
    except (RuntimeError, TimeoutError) as e:
        print(f"render failed: {e}", file=sys.stderr); sys.exit(1)
    try:
        # anchor on the graph's titled brand:save node, not output-dict order
        fname, subfolder, _ = select_output(client, pid, wf)
    except NoOutputError as e:
        print(str(e), file=sys.stderr); sys.exit(1)

    if args.comfy_output_dir:
        src = Path(args.comfy_output_dir) / subfolder / fname
        dest = route_output(repo_root, args.brand, src, args.mode, seed)
        fmt = None  # only set for 3d; passed to build_meta (None -> omitted from sidecar)
        if args.modality == "3d":
            # ComfyUI only saves GLB; convert to the requested export format host-side
            # (geometry-only — fine for STL/OBJ printing/CAD). Drop the intermediate GLB.
            fmt = (args.format or m.threed.format or "glb").lower()
            if fmt != "glb":
                from scripts.brandkit.mesh import convert
                converted = convert(dest, fmt)
                dest.unlink()
                dest = converted
        model_used = _resolve_model_used(args, m)
        inputs = _resolve_sidecar_inputs(args, m, fmt)
        meta = build_meta(modality=args.modality, mode=args.mode, brand=args.brand, seed=seed,
                          model=model_used, watermark=do_watermark, comfy_url=args.comfy_url,
                          wf=wf, inputs=inputs,
                          timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
                          fmt=fmt, comfyui_version=client.comfyui_version(),
                          pipeline_git_sha=git_provenance(repo_root))
        write_sidecar(dest, meta)
        print(f"output -> {dest}")
    else:
        print(f"output filename: {fname} (pass --comfy-output-dir to relocate into the brand folder)")


def _render_params(args, asset, tmp, seed):
    p = {"out_dir": str(tmp), "stem": f"{args.brand or 'render'}_{args.mode}_{seed}",
         "samples": args.samples, "res": list(args.res), "engine": "CYCLES", "seed": seed}
    if args.mode == "mesh":
        p.update(mesh=str(asset), turntable=bool(args.turntable), frames=args.frames)
    elif args.mode == "comfy-scene":
        p.update(asset=str(asset), placement=args.as_, frames=args.frames)
    else:  # finish
        p.update(mesh=str(asset), target_tris=args.target_tris, watertight=bool(args.watertight),
                 scale_mm=args.scale_mm, color=args.color,
                 formats=[f.strip() for f in args.formats.split(",") if f.strip()],
                 render_still=bool(args.render_still))
        if args.color == "project":
            p["asset"] = str(args.project_image)
    return p


def _sidecar_params(args):
    keys = {"mesh": ("samples", "res", "turntable", "frames"),
            "comfy-scene": ("samples", "res", "as_", "frames"),
            "finish": ("samples", "res", "target_tris", "watertight", "scale_mm", "color",
                       "formats", "render_still")}[args.mode]
    return {k: getattr(args, k) for k in keys}


def _primary_output(paths):
    """Pick the file the sidecar sits next to: a PNG if present, else a GLB, else the first."""
    for ext in (".png", ".glb"):
        m = next((p for p in paths if p.suffix.lower() == ext), None)
        if m:
            return m
    return paths[0]


def run_render(args, repo_root, ap):
    brand_dir = (repo_root / "brands" / args.brand) if args.brand else None
    if args.mode == "finish" and args.color == "project" and not args.project_image:
        ap.error("--color project needs --project-image <file>")
    seed = args.seed if args.seed is not None else random.randint(1, 2_000_000_000)
    if args.mode in ("mesh", "finish"):
        subdirs = ("outputs/3d", "outputs", "products", "references")
    else:
        subdirs = ("outputs/images", "outputs/video", "outputs", "references", "products")
    # absolute path: the headless Blender process runs with a different cwd, so a relative
    # --from would not resolve inside the template.
    asset = _resolve_asset(brand_dir, args.from_, subdirs, ap, f"render --from ({args.mode})").resolve()
    tmp = Path(tempfile.mkdtemp(prefix="chimera_render_"))
    template = repo_root / "workflows" / "templates" / "blender" / _TEMPLATE_FOR_MODE[args.mode]
    try:
        manifest = blender_runner.run_template(
            template, _render_params(args, asset, tmp, seed),
            blender_bin=args.blender_bin, timeout=args.timeout or RENDER_TIMEOUT)
        outs = manifest.get("outputs", [])
        if not outs:
            print("render produced no outputs", file=sys.stderr); sys.exit(1)
        routed = [route_output(repo_root, args.brand, Path(o), args.mode, seed) for o in outs]
    except blender_runner.BlenderJobError as e:
        print(f"render failed: {e}", file=sys.stderr); sys.exit(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    primary = _primary_output(routed)
    meta = build_render_meta(mode=args.mode, brand=args.brand, seed=seed, template=template.name,
                             params=_sidecar_params(args), outputs=[p.name for p in routed],
                             source=Path(asset).name, blender_version=manifest.get("blender_version"),
                             timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
                             pipeline_git_sha=git_provenance(repo_root))
    write_sidecar(primary, meta)
    for p in routed:
        print(f"output -> {p}")


def _cad_formats(args):
    # de-dup while preserving order: `--formats step,step` would otherwise produce the same output
    # path twice, and route_output would move it on the first pass then FileNotFoundError on the second.
    return list(dict.fromkeys(f.strip().lower() for f in args.formats.split(",") if f.strip()))


def _cad_params(args, source, tmp, seed):
    """The params blob handed to the FreeCAD template (pure). Primitive carries shape + its dims;
    convert carries the absolute source path. `formats` is the normalized export list."""
    p = {"out_dir": str(tmp), "stem": f"{args.brand or 'cad'}_{args.mode}_{seed}",
         "formats": _cad_formats(args)}
    if args.mode == "primitive":
        p["shape"] = args.shape
        for d in _SHAPE_DIMS[args.shape]:
            p[d] = float(getattr(args, d))
    elif args.mode == "script":
        p["script"] = str(source)   # `source` carries the resolved script path in script mode
    else:  # convert
        p["source"] = str(source)
    return p


def _cad_sidecar_params(args):
    """The CAD params recorded in the sidecar: primitive dims, or (script) the script name + a content
    hash so the params_signature actually varies across in-place script revisions (the whole point of the
    self-correction loop), or just formats (convert)."""
    if args.mode == "primitive":
        d = {k: float(getattr(args, k)) for k in _SHAPE_DIMS[args.shape]}
        d["formats"] = _cad_formats(args)
        return d
    if args.mode == "script":
        d = {"script": Path(args.script).name, "formats": _cad_formats(args)}
        try:
            import hashlib
            d["script_sha"] = hashlib.sha256(Path(args.script).read_bytes()).hexdigest()[:16]
        except OSError:
            pass
        return d
    return {"formats": _cad_formats(args)}


def _primary_cad_output(paths):
    """Pick the file the sidecar sits next to: a STEP (BREP) if present, else STL, else OBJ, else first."""
    for ext in (".step", ".stl", ".obj"):
        m = next((p for p in paths if p.suffix.lower() == ext), None)
        if m:
            return m
    return paths[0]


def _validate_cad(args, ap):
    """Friendly host-side validation before shelling out: formats subset, positive dims, tube bore
    < radius, cone top radius >= 0, and the one impossible convert (mesh source -> BREP STEP)."""
    fmts = _cad_formats(args)
    bad = [f for f in fmts if f not in _CAD_FORMATS]
    if bad:
        ap.error(f"--formats: unsupported {bad} (choose from {', '.join(_CAD_FORMATS)})")
    if not fmts:
        ap.error("--formats must list at least one of step/stl/obj")
    if args.mode == "primitive":
        for d in _SHAPE_DIMS[args.shape]:
            if d == "radius2":          # a cone may taper to a sharp tip (radius2 == 0)
                if float(args.radius2) < 0:
                    ap.error("cone --radius2 must be >= 0")
                continue
            if float(getattr(args, d)) <= 0:
                ap.error(f"--{d.replace('_', '-')} must be > 0 for shape {args.shape}")
        if args.shape == "tube" and float(args.inner_radius) >= float(args.radius):
            ap.error("tube --inner-radius must be < --radius")
    elif args.mode == "script":
        if not args.script:
            ap.error("cad --mode script needs --script <file.py>")
        if not Path(args.script).is_file():
            ap.error(f"cad --mode script: script not found (or not a file): {args.script}")
    else:  # convert
        ext = Path(args.from_).suffix.lower() if args.from_ else ""
        if ext not in _CONVERT_SRC_EXTS:
            ap.error(f"convert --from: unsupported source {ext or '(none)'} "
                     "(use step/stp/iges/igs/brep or stl/obj)")
        # a mesh source can't become a BREP STEP solid headlessly
        if ext in _MESH_EXTS and "step" in fmts:
            ap.error("convert: a mesh source (.stl/.obj) cannot be exported to STEP "
                     "(mesh -> BREP solid is not a headless operation); export stl/obj only")


def run_cad(args, repo_root, ap):
    _validate_cad(args, ap)
    brand_dir = (repo_root / "brands" / args.brand) if args.brand else None
    seed = args.seed if args.seed is not None else random.randint(1, 2_000_000_000)
    source = None
    if args.mode == "convert":
        # absolute path: the headless FreeCAD process runs with a different cwd.
        source = _resolve_asset(brand_dir, args.from_,
                                ("outputs/3d", "outputs", "products", "references"),
                                ap, "cad convert --from").resolve()
    elif args.mode == "script":
        source = Path(args.script).resolve()   # the agent-authored FreeCAD script (abs for headless cwd)
    tmp = Path(tempfile.mkdtemp(prefix="chimera_cad_"))
    template = repo_root / "workflows" / "templates" / "freecad" / _TEMPLATE_FOR_CAD[args.mode]
    try:
        manifest = freecad_runner.run_template(
            template, _cad_params(args, source, tmp, seed),
            freecad_bin=args.freecad_bin, timeout=args.timeout or CAD_TIMEOUT)
        outs = manifest.get("outputs", [])
        if not outs:
            print("cad produced no outputs", file=sys.stderr); sys.exit(1)
        routed = [route_output(repo_root, args.brand, Path(o), args.mode, seed) for o in outs]
    except freecad_runner.FreeCADJobError as e:
        print(f"cad failed: {e}", file=sys.stderr); sys.exit(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    primary = _primary_cad_output(routed)
    meta = build_cad_meta(mode=args.mode, shape=(args.shape if args.mode == "primitive" else None),
                          brand=args.brand, seed=seed, template=template.name,
                          params=_cad_sidecar_params(args), outputs=[p.name for p in routed],
                          source=(Path(source).name if source else None),
                          freecad_version=manifest.get("freecad_version"),
                          timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
                          pipeline_git_sha=git_provenance(repo_root))
    write_sidecar(primary, meta)
    for p in routed:
        print(f"output -> {p}")


def _finalize_views(args):
    return [v.strip() for v in args.views.split(",") if v.strip()]


def _finalize_azimuths(args, n):
    """Camera azimuths (deg) for the N views: explicit --azimuths CSV, else evenly spaced from front=0."""
    if args.azimuths:
        return [float(a) for a in args.azimuths.split(",") if a.strip()]
    return [360.0 * i / n for i in range(n)]


def _finalize_params(args, mesh, view_paths, azimuths, tmp, seed, palette):
    return finalize_core.finalize_params(
        mesh=mesh, view_paths=view_paths, azimuths=azimuths, brand=args.brand, seed=seed,
        elevation=args.elevation, back_fill=args.back_fill, palette=palette,
        texture_res=args.texture_res, samples=args.samples, res=list(args.res), out_dir=str(tmp))


def _validate_finalize(args, ap):
    if getattr(args, "auto_repaint", False):
        # auto-repaint generates the views (ComfyUI SDXL depth-CN + IPAdapter), so --views isn't needed
        if not args.concept:
            ap.error("finalize-texture --auto-repaint needs --concept <image> (the identity source)")
        if not args.subject:
            ap.error("finalize-texture --auto-repaint needs --subject (the repaint prompt)")
        if not args.comfy_output_dir:
            ap.error("finalize-texture --auto-repaint needs --comfy-output-dir (where ComfyUI writes)")
        if not 1 <= args.views_count <= 7:
            ap.error("finalize-texture --views-count must be 1..7 (Blender's 8-UV-layer cap minus atlas)")
        if args.azimuths:
            az = [a for a in args.azimuths.split(",") if a.strip()]
            if len(az) != args.views_count:
                ap.error(f"--azimuths count ({len(az)}) must match --views-count ({args.views_count})")
            try:
                [float(a) for a in az]
            except ValueError:
                ap.error("--azimuths must be comma-separated numbers (degrees)")
        return
    views = _finalize_views(args)
    if not views:
        ap.error("--views needs at least one image (azimuth order, front first), or use --auto-repaint")
    if len(views) > 7:
        ap.error("--views: at most 7 (Blender caps a mesh at 8 UV layers; one is the bake atlas)")
    if args.azimuths:
        az = [a for a in args.azimuths.split(",") if a.strip()]
        if len(az) != len(views):
            ap.error(f"--azimuths count ({len(az)}) must match --views count ({len(views)})")
        try:
            [float(a) for a in az]
        except ValueError:
            ap.error("--azimuths must be comma-separated numbers (degrees)")


def _auto_repaint_views(args, mesh, seed, brand_dir, repo_root, ap):
    """Resolve the concept + azimuths, then delegate to brandkit.finalize.repaint_views (shared with
    the in-loop finalize). Returns (view_paths, azimuths)."""
    concept = _resolve_asset(brand_dir, args.concept,
                             ("outputs/images", "outputs", "references", "products"),
                             ap, "finalize-texture --concept").resolve()
    azimuths = _finalize_azimuths(args, args.views_count)   # honors --azimuths, else even spacing
    client = ComfyClient(args.comfy_url)
    client.free()
    try:
        return finalize_core.repaint_views(
            client, mesh=mesh, concept=concept, subject=args.subject, azimuths=azimuths,
            comfy_output_dir=args.comfy_output_dir, repo_root=repo_root,
            blender_runner=blender_runner.run_template, seed=seed, res=args.texture_res,
            elevation=args.elevation, cn_strength=args.cn_strength, ip_weight=args.ip_weight,
            blender_bin=args.blender_bin)
    except finalize_core.FinalizeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def run_finalize_texture(args, repo_root, ap):
    _validate_finalize(args, ap)
    if args.brand:
        brand_dir = repo_root / "brands" / args.brand
        m = load_manifest(brand_dir / "brand.yaml")
    else:
        brand_dir, m = None, default_manifest()
    seed = args.seed if args.seed is not None else random.randint(1, 2_000_000_000)
    # absolute paths: the headless Blender process runs with a different cwd.
    mesh = _resolve_asset(brand_dir, args.from_, ("outputs/3d", "outputs", "products", "references"),
                          ap, "finalize-texture --from").resolve()
    if getattr(args, "auto_repaint", False):
        view_paths, azimuths = _auto_repaint_views(args, mesh, seed, brand_dir, repo_root, ap)
    else:
        view_paths = [_resolve_asset(brand_dir, v, ("outputs/images", "outputs", "references", "products"),
                                     ap, "finalize-texture --views").resolve() for v in _finalize_views(args)]
        azimuths = _finalize_azimuths(args, len(view_paths))
    palette = list(getattr(m, "palette", []) or [])
    tmp = Path(tempfile.mkdtemp(prefix="chimera_finalize_"))
    template = repo_root / "workflows" / "templates" / "blender" / _FINALIZE_TEMPLATE
    sheet = None
    try:
        manifest = blender_runner.run_template(
            template, _finalize_params(args, mesh, view_paths, azimuths, tmp, seed, palette),
            blender_bin=args.blender_bin, timeout=args.timeout or FINALIZE_TIMEOUT)
        glb = manifest.get("textured_glb")
        if not glb:
            print("finalize-texture produced no textured GLB", file=sys.stderr); sys.exit(1)
        routed_glb = route_output(repo_root, args.brand, Path(glb), "finalize", seed)
        stills = manifest.get("outputs", [])
        if stills:
            # the verification sheet is a nicety — its failure (e.g. Pillow absent) must NOT sink the
            # finalize after the GLB is already routed, or we'd leave a GLB with no sidecar.
            try:
                from scripts.brandkit import montage
                sheet_tmp = tmp / "sheet.png"
                montage.contact_sheet([Path(s) for s in stills], sheet_tmp, cols=2)
                sheet = route_output(repo_root, args.brand, sheet_tmp, "finalize", seed)
            except Exception as e:   # noqa: BLE001 - best-effort verification render
                print(f"warning: verification contact sheet skipped ({e})", file=sys.stderr)
    except blender_runner.BlenderJobError as e:
        print(f"finalize-texture failed: {e}", file=sys.stderr); sys.exit(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    outs = [routed_glb] + ([sheet] if sheet else [])
    params = {"views": [Path(v).name for v in view_paths], "azimuths": azimuths,
              "elevation": args.elevation, "back_fill": args.back_fill, "texture_res": args.texture_res}
    if getattr(args, "auto_repaint", False):   # record the auto-repaint provenance
        params.update(auto_repaint=True, concept=Path(args.concept).name, subject=args.subject,
                      cn_strength=args.cn_strength, ip_weight=args.ip_weight)
    meta = build_render_meta(mode="finalize-texture", brand=args.brand, seed=seed, template=template.name,
                             params=params,
                             outputs=[p.name for p in outs], source=Path(mesh).name,
                             blender_version=manifest.get("blender_version"),
                             timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
                             pipeline_git_sha=git_provenance(repo_root))
    write_sidecar(routed_glb, meta)
    for p in outs:
        print(f"output -> {p}")


def main():
    ap = argparse.ArgumentParser(prog="generate.py")
    sub = ap.add_subparsers(dest="modality", required=True)
    img = sub.add_parser("image"); _add_common(img)
    img.add_argument("--subject", required=True)
    img.add_argument("--mode", choices=["txt2img", "logo", "product", "relight"], default="txt2img")
    img.add_argument("--asset", default=None)
    img.add_argument("--variant", choices=["base", "turbo"], default=None,
                     help="Z-Image fidelity: turbo (8-step, default for txt2img/logo) or base "
                          "(25-step, default for product img2img)")
    img.add_argument("--model", default=None,
                     help="override the image model/family (e.g. flux2_dev_fp8mixed.safetensors "
                          "to use the FLUX.2 backend instead of Z-Image)")
    img.add_argument("--upscale", action="store_true",
                     help="4x ESRGAN upscale of the output (decode -> [watermark] -> upscale -> save)")
    img.add_argument("--upscale-model", dest="upscale_model", default=None,
                     help=f"override the upscale model (default {image_filler.DEFAULT_UPSCALE_MODEL}; "
                          "must be in ComfyUI models/upscale_models/)")
    vid = sub.add_parser("video"); _add_common(vid)
    vid.add_argument("--subject", required=True)
    vid.add_argument("--from-image", dest="from_image", required=True,
                     help="start frame: a file in brands/<brand>/products/ or references/")
    vid.add_argument("--mode", choices=["i2v"], default="i2v")
    vid.add_argument("--length", type=int, default=97)
    vid.add_argument("--fps", type=int, default=25)
    vid.add_argument("--width", type=int, default=768)
    vid.add_argument("--height", type=int, default=512)
    vid.add_argument("--audio", dest="audio", action="store_true", default=True)
    vid.add_argument("--no-audio", dest="audio", action="store_false")
    vid.add_argument("--upscale", action="store_true",
                     help="2x LTX spatial latent upscale (temporally coherent; precedes watermark)")
    vid.add_argument("--upscale-model", dest="upscale_model", default=None,
                     help=f"override the latent upscaler (default {video_filler.DEFAULT_VIDEO_UPSCALE_MODEL}; "
                          "must be in ComfyUI models/latent_upscale_models/)")
    aud = sub.add_parser("audio"); _add_common(aud)
    aud.add_argument("--mode", choices=["music", "foley"], default="music")
    aud.add_argument("--subject", required=True,
                     help="music: the sonic brief (e.g. 'logo sting'); foley: the SFX to generate")
    aud.add_argument("--from-video", dest="from_video", default=None,
                     help="foley source: a file in brands/<brand>/outputs|references|products/")
    aud.add_argument("--duration", type=float, default=None)
    aud.add_argument("--bpm", type=int, default=None, help="(music)")
    aud.add_argument("--keyscale", default=None, help="(music)")
    aud.add_argument("--fps", type=float, default=None, help="(foley; default = source fps)")
    td = sub.add_parser("3d"); _add_common(td)
    td.add_argument("--mode", choices=["image"], default="image")
    td.add_argument("--from-image", dest="from_image", required=True,
                    help="source image: a file in brands/<brand>/products|references/ or outputs/images/")
    td.add_argument("--octree", type=int, default=None, help="VAEDecodeHunyuan3D octree_resolution (detail vs size)")
    td.add_argument("--model", default=None, help="3D checkpoint override")
    td.add_argument("--format", choices=["glb", "stl", "obj"], default=None,
                    help="3D export format (default glb; stl/obj converted host-side, geometry only)")
    rn = sub.add_parser("render", help="headless Blender: render a mesh / ComfyUI asset, or finish a mesh")
    rn.add_argument("--brand", default=None)
    rn.add_argument("--seed", type=int, default=None)
    rn.add_argument("--from", dest="from_", required=True,
                    help="mesh (mesh/finish) or image|video (comfy-scene); a brand asset or a file path")
    rn.add_argument("--mode", choices=["mesh", "comfy-scene", "finish"], default="mesh")
    rn.add_argument("--samples", type=int, default=96)
    rn.add_argument("--res", type=int, nargs=2, default=[1080, 1080], metavar=("W", "H"))
    rn.add_argument("--turntable", action="store_true", help="(mesh) also render a 360 MP4")
    rn.add_argument("--frames", type=int, default=72)
    rn.add_argument("--as", dest="as_", choices=["backdrop"], default="backdrop",
                    help="(comfy-scene) image placement (only 'backdrop' in V1; plane/texture are roadmap)")
    rn.add_argument("--target-tris", dest="target_tris", type=int, default=200000, help="(finish) decimate target")
    rn.add_argument("--watertight", action="store_true", help="(finish) voxel-remesh to a manifold solid")
    rn.add_argument("--scale-mm", dest="scale_mm", type=float, default=None, help="(finish) longest-dim mm")
    rn.add_argument("--color", choices=["material", "project"], default="material", help="(finish) color method")
    rn.add_argument("--formats", default="stl,glb", help="(finish) comma-separated export formats")
    rn.add_argument("--project-image", dest="project_image", default=None,
                    help="(finish, --color project) image to project as color")
    rn.add_argument("--no-render", dest="render_still", action="store_false", default=True,
                    help="(finish) skip the hero render")
    rn.add_argument("--blender-bin", dest="blender_bin", default=None, help="blender path (else $BLENDER_BIN/PATH)")
    rn.add_argument("--timeout", type=int, default=None)
    ft = sub.add_parser("finalize-texture",
                        help="headless Blender: all-around albedo bake of N corrected views onto a mesh (Phase 4b)")
    ft.add_argument("--brand", default=None)
    ft.add_argument("--seed", type=int, default=None)
    ft.add_argument("--from", dest="from_", required=True,
                    help="mesh to texture (GLB/STL/OBJ; brand asset or path — e.g. a winning mesh3d GLB)")
    ft.add_argument("--views", default=None,
                    help="manual mode: comma-separated corrected view images in azimuth order, front first "
                         "(4 views = front,right,back,left). Omit when using --auto-repaint.")
    ft.add_argument("--azimuths", default=None,
                    help="comma-separated camera azimuths in degrees (default: evenly spaced, front=0)")
    ft.add_argument("--elevation", type=float, default=15.0, help="camera elevation in degrees")
    ft.add_argument("--back-fill", dest="back_fill", choices=["palette", "grey"], default="palette",
                    help="fill for faces no view sees (palette[0] or neutral grey)")
    ft.add_argument("--texture-res", dest="texture_res", type=int, default=1024)
    ft.add_argument("--samples", type=int, default=48, help="Cycles samples for the verification stills")
    ft.add_argument("--res", type=int, nargs=2, default=[768, 768], metavar=("W", "H"))
    ft.add_argument("--blender-bin", dest="blender_bin", default=None)
    ft.add_argument("--timeout", type=int, default=None)
    # --auto-repaint: generate the N views via ComfyUI SDXL depth-ControlNet + IPAdapter (Phase 4b auto)
    ft.add_argument("--auto-repaint", dest="auto_repaint", action="store_true",
                    help="generate the views automatically: render per-view depth -> SDXL depth-ControlNet "
                         "+ IPAdapter repaint from --concept (instead of supplying --views)")
    ft.add_argument("--concept", default=None,
                    help="(--auto-repaint) identity source image for IPAdapter (brand asset or path)")
    ft.add_argument("--subject", default=None, help="(--auto-repaint) the repaint prompt, e.g. 'an armored rover'")
    ft.add_argument("--views-count", dest="views_count", type=int, default=4,
                    help="(--auto-repaint) number of ring views to generate + bake (1..7; default 4)")
    ft.add_argument("--cn-strength", dest="cn_strength", type=float, default=0.7,
                    help="(--auto-repaint) depth-ControlNet strength")
    ft.add_argument("--ip-weight", dest="ip_weight", type=float, default=0.8,
                    help="(--auto-repaint) IPAdapter weight (identity strength)")
    ft.add_argument("--comfy-url", default="http://127.0.0.1:8000")
    ft.add_argument("--comfy-output-dir", default=None,
                    help="(--auto-repaint) where ComfyUI writes outputs (to collect repainted views)")
    cd = sub.add_parser("cad",
                        help="headless FreeCAD: parametric primitive, CAD/mesh convert, or run an "
                             "agent-authored script (generative CAD)")
    cd.add_argument("--brand", default=None)
    cd.add_argument("--seed", type=int, default=None)
    cd.add_argument("--mode", choices=["primitive", "convert", "script"], default="primitive")
    cd.add_argument("--shape", choices=["box", "cylinder", "cone", "sphere", "tube"], default="box",
                    help="(primitive) solid to build")
    cd.add_argument("--script", default=None,
                    help="(script) an agent/user-authored FreeCAD .py that builds geometry in `doc` "
                         "(or sets RESULT=[objs]); run headless -> STEP/STL/OBJ. For generative CAD.")
    cd.add_argument("--length", type=float, default=40.0, help="(box) mm")
    cd.add_argument("--width", type=float, default=30.0, help="(box) mm")
    cd.add_argument("--height", type=float, default=20.0, help="(box/cylinder/cone/tube) mm")
    cd.add_argument("--radius", type=float, default=15.0, help="(cylinder/cone/sphere/tube) mm")
    cd.add_argument("--radius2", type=float, default=0.0, help="(cone) top radius mm (0 = sharp tip)")
    cd.add_argument("--inner-radius", dest="inner_radius", type=float, default=8.0, help="(tube) bore mm")
    cd.add_argument("--from", dest="from_", default=None,
                    help="(convert) source CAD/mesh file: step/iges/brep or stl/obj (brand asset or path)")
    cd.add_argument("--formats", default="step,stl", help="comma-separated subset of step,stl,obj")
    cd.add_argument("--freecad-bin", dest="freecad_bin", default=None,
                    help="FreeCADCmd path (else $FREECAD_BIN / PATH / default install)")
    cd.add_argument("--timeout", type=int, default=None)
    rp = sub.add_parser("replay", help="re-run a render from its sidecar JSON")
    rp.add_argument("sidecar", help="path to a schema-2 sidecar .json")
    rp.add_argument("--seed", type=int, default=None, help="override the recorded seed")
    rp.add_argument("--comfy-output-dir", default=None,
                    help="route the result into the brand folder + write a fresh sidecar "
                         "(omit to just re-render and print the raw ComfyUI filename)")
    rp.add_argument("--comfy-url", default=None, help="override (default: the sidecar's recorded comfy_url)")
    nb = sub.add_parser("new-brand", help="scaffold a new brand folder from brands/_template/")
    nb.add_argument("name", help="brand folder name (used as --brand later)")
    lt = sub.add_parser("lint", help="validate a brand.yaml + check referenced assets")
    lt.add_argument("--brand", required=True)
    dr = sub.add_parser("doctor", help="preflight: check ComfyUI, node packs, models, and a brand")
    dr.add_argument("--brand", default=None, help="also check this brand's manifest/assets/model")
    dr.add_argument("--comfy-url", default="http://127.0.0.1:8000")
    uc = sub.add_parser("update-check",
                        help="report available updates (chimera repo, ComfyUI, pip deps, node packs)")
    uc.add_argument("--comfy-url", default="http://127.0.0.1:8000")
    uc.add_argument("--no-network", action="store_true", help="skip the GitHub release lookup")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if args.modality == "new-brand":
        from scripts.brandkit.scaffold import new_brand
        try:
            dest = new_brand(repo_root, args.name)
        except (ValueError, FileExistsError, FileNotFoundError) as e:
            ap.error(str(e))
        print(f"created {dest}")
        print(f"  next: edit {dest / 'brand.yaml'}, add a logo to logos/, then "
              f"`python scripts/generate.py lint --brand {args.name}`")
        return
    if args.modality == "lint":
        from scripts.brandkit.scaffold import lint_brand, print_lint
        fails = print_lint(args.brand, lint_brand(repo_root, args.brand))
        sys.exit(1 if fails else 0)
    if args.modality == "doctor":
        from scripts.brandkit.doctor import run_checks, print_doctor
        client = ComfyClient(args.comfy_url)
        fails = print_doctor(args.brand, run_checks(client, repo_root, args.brand))
        sys.exit(1 if fails else 0)
    if args.modality == "update-check":
        from scripts.brandkit.updates import check_updates, latest_comfyui_release, print_updates
        client = ComfyClient(args.comfy_url)
        latest = None if args.no_network else latest_comfyui_release()
        print_updates(check_updates(client, repo_root, latest_comfyui=latest))
        return
    if args.modality == "replay":
        data = json.loads(Path(args.sidecar).read_text(encoding="utf-8"))
        try:
            rargs = _args_from_sidecar(data, seed=args.seed,
                                       comfy_output_dir=args.comfy_output_dir,
                                       comfy_url=args.comfy_url)
        except (ValueError, KeyError) as e:
            ap.error(f"cannot replay {args.sidecar}: {e}")
        print(f"replaying {args.sidecar} (modality={rargs.modality} mode={rargs.mode} "
              f"brand={rargs.brand} seed={rargs.seed})")
        run(rargs, repo_root, ap)
        return
    if args.modality == "render":
        run_render(args, repo_root, ap)
        return
    if args.modality == "cad":
        if args.mode == "convert" and not args.from_:
            ap.error("cad --mode convert needs --from <file>")
        run_cad(args, repo_root, ap)
        return
    if args.modality == "finalize-texture":
        run_finalize_texture(args, repo_root, ap)
        return
    run(args, repo_root, ap)


if __name__ == "__main__":
    main()

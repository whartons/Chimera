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
through the SAME prepare -> filler -> queue -> route -> sidecar flow as a normal render, with the
recorded model PINNED (a later brand pin or Chimera default change can't swap it). It re-derives the
prompt from the recorded `subject` and today's brand.yaml, then compares the built graph with the
record (prompt/negative text, model, structure, settings) and stops, listing the differences, unless
`--accept-drift`. `replay --model <file>` deliberately re-runs old work on a different model (only the
prompt is then checked, and a different video family gets its own clip defaults). The result takes the
render's standard name, or `<name>_replay` (…2, …) when that is taken, never replacing a file. Replay treats the sidecar as untrusted: it
renders on the local default ComfyUI unless `--comfy-url` is given, and only takes plain relative file
names. Schema-1 (pre-enriched) sidecars lack `inputs` and cannot be replayed -- re-render once to
upgrade them.
"""
import argparse, json, random, struct, sys, datetime, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.brandkit.manifest import ManifestError, load_manifest, default_manifest
from scripts.brandkit.prompt import build_prompt, build_audio_prompt
from scripts.brandkit import workflow as image_filler
from scripts.brandkit import video as video_filler
from scripts.brandkit import audio as audio_filler
from scripts.brandkit import threed as threed_filler
from scripts.brandkit.comfy import ComfyClient, DEFAULT_URL as DEFAULT_COMFY_URL
from scripts.brandkit.outputs import (NoOutputError, brand_name_ok, comfy_output_path, fresh_output_name,
                                      route_output, select_output, write_sidecar)
from scripts.brandkit.provenance import git_provenance  # re-exported; historical home was here
from scripts.brandkit.sidecar import build_meta

FILLERS = {"image": image_filler.build, "video": video_filler.build, "audio": audio_filler.build,
           "3d": threed_filler.build}
TIMEOUTS = {"image": 900, "video": 3600, "audio": 1800, "3d": 3600}
FREE_BEFORE_DEFAULT = {"image": False, "video": True, "audio": True, "3d": True}

# The sidecar-inputs/replay contract lives in brandkit beside sidecar.py; the old private
# names stay importable from here (tests + any external callers).
from scripts.brandkit.replay import SIDECAR_INPUT_KEYS  # noqa: E402,F401 (re-export)
from scripts.brandkit.replay import (  # noqa: E402
    args_from_sidecar as _args_from_sidecar,
    replay_drift,
    replay_notes,
    resolve_model_used as _resolve_model_used,
    resolve_sidecar_inputs as _resolve_sidecar_inputs,
)

# The headless render/cad/finalize-texture orchestration lives in brandkit beside its runners;
# _resolve_asset is the shared CLI asset-locator (also used by the _prepare_* functions here).
from scripts.brandkit.dcc_cli import (  # noqa: E402
    _resolve_asset,
    run_cad,
    run_finalize_texture,
    run_render,
)


_ROTATED = (5, 6, 7, 8)   # EXIF orientations that turn the stored image a quarter turn (width <-> height)


def _exif_orientation(app1):
    """The EXIF Orientation (tag 0x0112) in a JPEG APP1 segment's payload; 1 (as stored) when it has none or
    the block can't be read."""
    if app1[:6] != b"Exif\x00\x00":
        return 1
    tiff = app1[6:]
    e = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if e is None:
        return 1
    try:
        ifd = struct.unpack(e + "I", tiff[4:8])[0]
        for i in range(struct.unpack(e + "H", tiff[ifd:ifd + 2])[0]):
            at = ifd + 2 + 12 * i
            tag, kind = struct.unpack(e + "HH", tiff[at:at + 4])
            if tag == 0x0112:
                fmt = {3: "H", 4: "I"}.get(kind)   # a SHORT, as the standard says; a LONG Pillow reads too
                return struct.unpack(e + fmt, tiff[at + 8:at + 8 + struct.calcsize(fmt)])[0] if fmt else 1
    except struct.error:   # a truncated EXIF block: the frame size still stands
        pass
    return 1


def _jpeg_size(f):
    """(width, height) from a JPEG's frame header, swapped when its EXIF orientation turns it a quarter turn:
    the size ComfyUI's LoadImage loads (it applies the rotation), or None."""
    f.seek(2)
    orientation = None
    while True:
        b = f.read(1)
        while b and b != b"\xff":
            b = f.read(1)
        while b == b"\xff":
            b = f.read(1)
        if not b:
            return None
        marker = b[0]
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:   # markers without a length
            continue
        seg = f.read(2)
        if len(seg) < 2:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):   # a start-of-frame
            data = f.read(5)
            if len(data) < 5:
                return None
            w, h = struct.unpack(">H", data[3:5])[0], struct.unpack(">H", data[1:3])[0]
            return (h, w) if orientation in _ROTATED else (w, h)
        length = struct.unpack(">H", seg)[0]
        if marker == 0xE1 and orientation is None:   # APP1: the first Exif block counts, as in Pillow
            app1 = f.read(length - 2)
            if app1[:6] == b"Exif\x00\x00":
                orientation = _exif_orientation(app1)
            continue
        f.seek(length - 2, 1)


def _header_size(path):
    """(width, height) read from a PNG, GIF, WebP or JPEG header without Pillow; None for anything else."""
    with open(path, "rb") as f:
        head = f.read(30)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a") and len(head) >= 10:
            return struct.unpack("<HH", head[6:10])
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP" and len(head) == 30:
            kind = head[12:16]
            if kind == b"VP8 ":    # lossy: 14-bit sizes after the frame tag and start code
                w, h = struct.unpack("<HH", head[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if kind == b"VP8L":    # lossless: 14-bit width-1 and height-1 after the signature byte
                bits = int.from_bytes(head[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if kind == b"VP8X":    # extended: 24-bit canvas width-1 and height-1
                return int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1
        if head[:2] == b"\xff\xd8":
            return _jpeg_size(f)
    return None


def _image_size(path):
    """(width, height) of a logo or source image, or None if it can't be determined. Uses Pillow when
    available (png/jpg/webp/bmp/tiff/gif), else reads the PNG/GIF/WebP/JPEG header itself, so the graph
    (the watermark canvas, the logo size) is the same with or without Pillow and a replay on the other
    kind of install reports no drift. The size is the upright one ComfyUI's LoadImage loads: it applies the
    EXIF rotation, so a phone photo stored 4032x3024 with orientation 6 is 3024x4032 there, and a corner
    watermark placed for 4032 wide fell off the frame (2026-10-25 review). None -> callers use a
    canvas-proportional geometry estimate (correct SIZE on-graph, only the corner offset is approximate)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            return (h, w) if im.getexif().get(0x0112) in _ROTATED else (w, h)
    except ImportError:
        pass                       # no Pillow -> header read below
    except Exception:
        return None                # Pillow present but the file isn't a readable image
    try:
        return _header_size(path)
    except (OSError, struct.error):
        return None                # unreadable or truncated -> approximate geometry


def _add_common(sp):
    sp.add_argument("--brand", default=None,
                    help="optional brand (brands/<brand>/); omit to generate brandlessly -> outputs/")
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    sp.add_argument("--comfy-output-dir", default=None)
    sp.add_argument("--watermark", action="store_true", help="stamp the brand logo (opt-in)")
    sp.add_argument("--out-name", default=None, help="(reserved; output is named <brand>_<mode>_<seed>)")
    sp.add_argument("--timeout", type=int, default=None)
    sp.add_argument("--free-before", dest="free_before", action="store_true", default=None)
    sp.add_argument("--no-free-before", dest="free_before", action="store_false")


def _prepare_image(args, m, brand_dir, client, ap):
    resolved = _resolve_model_used(args, m)
    if args.variant and image_filler.family(resolved) != "zimage":
        print(f"note: --variant picks Z-Image's fidelity; {resolved} ignores it", file=sys.stderr)
    fkw = {"mode": args.mode, "variant": args.variant, "model": args.model,
           "upscale": args.upscale,
           "upscale_model": args.upscale_model}  # raw; the filler resolves brand/default
    if args.mode == "relight":
        if args.model and image_filler.family(args.model) != "flux2":
            print(f"note: relight is a FLUX.2 edit, so it renders on {image_filler.DEFAULT_RELIGHT_MODEL}, not "
                  f"{args.model}", file=sys.stderr)
        # relight (FLUX.2 ReferenceLatent edit): --asset is the source still to relight. Search the
        # usual input locations incl. prior renders; brandless -> treat --asset as a direct path.
        asset_path = _resolve_asset(brand_dir, args.asset,
                                    ("products", "references", "outputs/images"), ap, "relight --asset")
        fkw["asset"] = client.upload_image(asset_path)
        sz = _image_size(asset_path)
        if sz:   # relight renders at the source's native size -> true watermark canvas
            fkw["canvas"] = sz
    if args.mode in ("logo", "product"):
        # a product shot may start from one of the brand's own renders (the image -> video -> 3D chain)
        subdirs = ("logos",) if args.mode == "logo" else ("products", "outputs/images")
        # only LOGO mode may fall back to logo.default; product must not silently pick up a
        # products/ file that happens to share the logo's filename
        logo_fallback = (m.logo.default or "").split("/")[-1] if args.mode == "logo" else None
        asset_name = args.asset or logo_fallback or None
        asset_path = _resolve_asset(brand_dir, asset_name, subdirs, ap, f"{args.mode} --asset")
        fkw["asset"] = client.upload_image(asset_path)
        if args.mode == "product":
            sz = _image_size(asset_path)
            if sz:   # product img2img renders at the source's native size -> true watermark canvas
                fkw["canvas"] = sz
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
    model, camera = getattr(args, "model", None), getattr(args, "camera", None)
    try:   # before the upload: a combination the family can't render is a CLI error, not a wasted upload
        video_filler.check_options(m, model=model, camera=camera, quality=getattr(args, "quality", None),
                                   upscale=args.upscale)
    except ValueError as e:
        replaying = getattr(args, "expect", None) is not None and "--camera" in str(e)
        ap.error(f"{e} (replay can't add a camera move: replay a Fun Camera render's sidecar, or pick another "
                 "--model)" if replaying else str(e))
    path = _resolve_asset(brand_dir, args.from_image, ("products", "references", "outputs/images"), ap,
                          "video --from-image")
    r = video_filler.resolved_settings(m, model=model, camera=camera, length=args.length)
    wan = video_filler.is_wan(r["model"])
    if wan and args.audio:
        print("note: Wan 2.2 clips are silent; for built-in synced audio use --model ltx23, or add sound "
              "afterwards with `audio --mode foley --from-video <clip>`", file=sys.stderr)
    if wan and args.fps and args.fps != video_filler.WAN_FPS:
        print(f"note: Wan 2.2 times its motion for {video_filler.WAN_FPS} fps; --fps {args.fps} only changes "
              "the playback speed", file=sys.stderr)
    if args.length and r["length"] != args.length:
        print(f"note: {'Wan 2.2' if wan else 'LTX-2.3'} renders {4 if wan else 8}k+1 frames, so --length "
              f"{args.length} renders {r['length']}", file=sys.stderr)
    return {"from_image": client.upload_image(path),
            "length": args.length, "fps": args.fps, "audio": args.audio,
            "width": args.width, "height": args.height,
            "model": model, "camera": camera, "quality": getattr(args, "quality", None),
            "upscale": args.upscale,
            "upscale_model": args.upscale_model}  # raw; the filler resolves brand/default


def _probe_video(path):
    """Best-effort (fps, duration_s, width, height) via PyAV; (None,)*4 if PyAV is absent
    or the file has no readable video stream."""
    try:
        import av
    except ImportError:
        return None, None, None, None
    try:
        c = av.open(str(path))
    except Exception:                                 # corrupt / non-media file — best-effort
        return None, None, None, None
    try:
        if not c.streams.video:                       # audio-only / no video track
            return None, None, None, None
        vs = c.streams.video[0]
        fr = float(vs.average_rate) if vs.average_rate else None  # None or 0 -> unknown
        frames = vs.frames or 0
        w, h = vs.codec_context.width, vs.codec_context.height
        dur = (frames / fr) if (frames and fr) else None
        if dur is None:   # WebM and MKV store no frame count (frames == 0): foley used 5 s for any length
            if vs.duration and vs.time_base:
                dur = float(vs.duration * vs.time_base)
            elif c.duration:
                dur = c.duration / av.time_base   # the container's, in microseconds
        return fr, dur, w, h
    except Exception:                                 # unreadable stream metadata
        return None, None, None, None
    finally:
        c.close()


def _clip_timing(path):
    """(fps, duration_s, width, height) of a foley source clip. A Chimera render records the exact values
    in its own sidecar (no dependencies; and right for Wan's 16 fps clips, which the 25 fps fallback below
    used to speed up); otherwise probe with PyAV (the [video] extra); (None,)*4 if neither works."""
    try:
        inp = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8-sig")).get("inputs") or {}
    except (OSError, ValueError, AttributeError):
        inp = {}
    fps, length = inp.get("fps"), inp.get("length")
    if fps and length:
        w, h = inp.get("width"), inp.get("height")
        if inp.get("upscale") and w and h:   # LTX's latent upscaler doubles the decoded frame
            w, h = w * 2, h * 2
        return float(fps), length / float(fps), w, h
    return _probe_video(path)


def _prepare_audio(args, m, brand_dir, client, ap):
    model = getattr(args, "model", None)   # --model, or pinned by replay; else brand/default
    try:   # before the foley upload: a request the mode can't render is a CLI error
        audio_filler.check_options(m, args.mode, model=model, duration=args.duration,
                                   lyrics=getattr(args, "lyrics", None))
    except ValueError as e:
        ap.error(str(e))
    if args.mode == "music":
        lyrics = getattr(args, "lyrics", None)
        if lyrics and args.duration is None and getattr(args, "expect", None) is None:
            print(f"note: --lyrics renders {audio_filler.music_seconds(m, lyrics):g} s (ACE-Step didn't sing in a "
                  "20 s clip); pass --duration to change it", file=sys.stderr)
        elif lyrics and args.duration is not None and args.duration < audio_filler.LYRICS_SECONDS:
            print(f"warning: a {args.duration:g} s clip may come out instrumental: ACE-Step didn't sing in 20 s "
                  f"and did in {audio_filler.LYRICS_SECONDS:g} s", file=sys.stderr)
        if lyrics and getattr(args, "expect", None) is None:
            print("note: ACE-Step sings on most seeds but not every one: if this render comes out instrumental, "
                  "try another --seed", file=sys.stderr)
        return {"mode": "music", "duration": args.duration, "bpm": args.bpm,
                "keyscale": args.keyscale, "model": model, "lyrics": lyrics}
    if args.mode == "sfx":
        return {"mode": "sfx", "duration": args.duration, "model": model}
    # foley: locate + upload the source video, probe its fps/duration/size
    # outputs/video/ first (media-type-routed location), then legacy flat outputs/, then sources
    path = _resolve_asset(brand_dir, args.from_video,
                          ("outputs/video", "outputs", "references", "products"), ap, "foley --from-video")
    fr, dur, w, h = _clip_timing(path)
    frame_rate = args.fps or fr or 25.0
    duration = args.duration or dur or 5.0
    if (fr is None or dur is None) and (args.fps is None or args.duration is None):
        print(f"warning: could not probe {path.name}; using frame_rate={frame_rate} duration={duration}"
              " (pass --fps/--duration to override)", file=sys.stderr)
    # a replay passes the recorded size too (the watermark canvas), so it needn't probe the clip again
    return {"mode": "foley", "from_video": client.upload_video(path),
            "frame_rate": frame_rate, "duration": duration, "fps": frame_rate,
            "width": getattr(args, "width", None) or w or 768, "height": getattr(args, "height", None) or h or 512,
            "model": model}


def _prepare_3d(args, m, brand_dir, client, ap):
    if args.octree is not None and threed_filler.family(threed_filler.resolved_model(m, args.model)) != "hunyuan3d":
        print("note: --octree is a Hunyuan3D setting; TRELLIS.2 and Pixal3D ignore it", file=sys.stderr)
    path = _resolve_asset(brand_dir, args.from_image,
                          ("products", "references", "outputs/images"), ap, "3d --from-image")
    return {"mode": args.mode, "from_image": client.upload_image(path),
            "octree": args.octree, "model": args.model}


def _check_repo_layout(repo_root, ap):
    """Fail fast when running outside a repo checkout. The CLI resolves workflow templates and
    brands/_template relative to its own file, which only works from a git clone / editable
    install — a plain `pip install .` copies just the scripts package into site-packages."""
    if not (Path(repo_root) / "workflows" / "templates").is_dir():
        ap.error(f"no workflows/templates found at {repo_root} — chimera must run from a repo "
                 "checkout: git clone + `pip install -e .` (a non-editable install doesn't "
                 "package the templates)")


def _supports_watermark(modality, mode):
    if modality == "image":
        return mode != "logo"
    if modality == "video":
        return True
    if modality == "audio":
        return mode == "foley"   # music has no visual canvas
    return False


PREPARE = {"image": _prepare_image, "video": _prepare_video, "audio": _prepare_audio,
           "3d": _prepare_3d}


def _default_free_before(args, m):
    """--free-before when neither flag is given: per modality, except that image jobs loading FLUX.2
    also free first (see workflow.needs_free_before). Mirrors the filler's `model or brand default`."""
    if args.modality == "image":
        return image_filler.needs_free_before(args.mode, args.variant, args.model or m.defaults.model)
    return FREE_BEFORE_DEFAULT[args.modality]


def run(args, repo_root, ap):
    if args.brand:
        brand_dir = repo_root / "brands" / args.brand
        try:
            m = load_manifest(brand_dir / "brand.yaml")
        except ManifestError as e:   # a brand you don't have, or a brand.yaml mistake
            ap.error(f"brand {args.brand!r}: {e}")
    else:
        brand_dir, m = None, default_manifest()   # brandless: neutral manifest, output -> outputs/
    seed = args.seed if args.seed is not None else random.randint(1, 2_000_000_000)
    if args.modality == "3d":
        pos, neg = "", ""
    elif args.modality == "audio":
        pos, neg = build_audio_prompt(m, args.subject, args.mode)
    else:
        pos, neg = build_prompt(m, args.subject)
    expect = getattr(args, "expect", None)   # replay: the sidecar being reproduced
    # a replay keeps the recorded watermark decision: a brand that later turned enabled_default on used to
    # stamp old renders without a word
    want = bool(expect.get("watermark")) if expect is not None else (args.watermark or m.watermark.enabled_default)
    do_watermark = want and _supports_watermark(args.modality, args.mode)
    if do_watermark and not args.brand:
        ap.error("--watermark needs a --brand (the logo comes from brands/<brand>/logos/)")
    client = ComfyClient(args.comfy_url)
    if do_watermark:   # checked before anything is uploaded
        logo_rel = (m.logo.default or "").split("/")[-1]
        logo_path = brand_dir / "logos" / logo_rel
        # is_file(), not exists(): with logo.default unset logo_rel is "" and pathlib's empty
        # join makes logo_path the logos/ DIRECTORY itself, which exists on every scaffolded brand
        if not logo_rel or not logo_path.is_file():
            ap.error(f"--watermark needs logo.default set in brand.yaml and the file present at "
                     f"brands/{args.brand}/logos/ (logo.default is {m.logo.default!r})")

    fkw = PREPARE[args.modality](args, m, brand_dir, client, ap)
    if do_watermark:
        fkw["watermark_logo"] = client.upload_image(logo_path)
        sz = _image_size(logo_path)
        if sz:
            fkw["logo_px"] = (int(sz[0] * m.watermark.scale), int(sz[1] * m.watermark.scale))
        else:
            print(f"warning: could not read watermark logo dimensions from {logo_rel}; corner "
                  "placement will be approximate (install Pillow or use a PNG logo)",
                  file=sys.stderr)

    try:
        wf = FILLERS[args.modality](repo_root, m, positive=pos, negative=neg, seed=seed,
                                   watermark=do_watermark, **fkw)
    except ValueError as e:   # a combination the filler can't render (e.g. --camera with --model ltx23)
        ap.error(str(e))
    if expect is not None:
        drift = replay_drift(expect, model=_resolve_model_used(args, m), wf=wf, modality=args.modality,
                             mode=args.mode, model_override=getattr(args, "model_override", None))
        if drift:
            print("this replay would not reproduce the recorded render:", file=sys.stderr)
            for d in drift:
                print(f"  - {d}", file=sys.stderr)
            if not getattr(args, "accept_drift", False):
                print("nothing rendered; re-run with --accept-drift to render with today's settings "
                      "(the new sidecar records what was actually used)", file=sys.stderr)
                sys.exit(1)
            print("--accept-drift: rendering anyway", file=sys.stderr)
    # free only now: a replay stopped by drift, or a bad flag, must not unload every ComfyUI model first
    free_before = args.free_before if args.free_before is not None else _default_free_before(args, m)
    if free_before:
        client.free()
    try:
        pid = client.queue_prompt(fresh_output_name(wf))   # a repeated identical job still writes a new file
    except RuntimeError as e:   # ComfyUI's validation (HTTP 400): a model file it doesn't have, a value out of range
        print(f"{e}\n(`chimera doctor` checks models and node packs)", file=sys.stderr)
        sys.exit(1)
    print(f"queued {pid} (modality={args.modality} brand={args.brand or '-'} mode={args.mode} seed={seed})")
    timeout = args.timeout or TIMEOUTS[args.modality]
    try:
        hist = client.wait(pid, max_wait=timeout)
    except (RuntimeError, TimeoutError) as e:
        print(f"render failed: {e}", file=sys.stderr); sys.exit(1)
    try:
        # anchor on the graph's titled brand:save node, not output-dict order; reuse wait()'s
        # history record instead of re-fetching it
        fname, subfolder, _ = select_output(client, pid, wf, history=hist)
        src = comfy_output_path(args.comfy_output_dir, subfolder, fname) if args.comfy_output_dir else None
    except NoOutputError as e:
        print(str(e), file=sys.stderr); sys.exit(1)

    if src is not None:
        # a replay keeps the recorded seed, so it must not land on (and replace) the render it reproduces
        try:
            dest = route_output(repo_root, args.brand, src, args.mode, seed, keep_existing=expect is not None)
        except NoOutputError as e:
            print(str(e), file=sys.stderr); sys.exit(1)
        fmt = None  # only set for 3d; passed to build_meta (None -> omitted from sidecar)
        if args.modality == "3d":
            # ComfyUI only saves GLB; convert to the requested export format host-side (geometry only, for
            # printing or CAD). The GLB stays beside it: TRELLIS.2 and Pixal3D bake their textures into it.
            fmt = (args.format or m.threed.format or "glb").lower()
            if fmt != "glb":
                from scripts.brandkit.mesh import convert
                try:
                    dest = convert(dest, fmt)
                except ValueError as e:
                    print(f"{e} (the GLB is at {dest})", file=sys.stderr); sys.exit(1)
        model_used = _resolve_model_used(args, m)
        inputs = _resolve_sidecar_inputs(args, m, fmt)
        if args.modality == "audio" and args.mode == "foley":
            # the timing and size actually used (probed, or read from the clip's sidecar): a replay without
            # PyAV, or of a clip whose sidecar has gone, used to fall back to 25 fps / 5 s and fail as drift
            inputs.update(fps=fkw["fps"], duration=fkw["duration"], width=fkw["width"], height=fkw["height"])
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
        if args.modality == "3d" and (args.format or m.threed.format or "glb").lower() != "glb":
            print("note: the STL/OBJ conversion runs on the routed file, so without --comfy-output-dir you get "
                  "ComfyUI's GLB only", file=sys.stderr)


def _run_comfy(args, repo_root, ap):
    """run(), with ComfyUI being down or dropping mid-render reported as one line instead of a traceback."""
    try:
        run(args, repo_root, ap)
    except urllib.error.HTTPError as e:   # reached ComfyUI, which refused a request (an upload, /free)
        print(f"ComfyUI at {args.comfy_url} answered HTTP {e.code} ({e.reason})", file=sys.stderr)
        sys.exit(1)
    except (urllib.error.URLError, ConnectionError) as e:
        print(f"can't reach ComfyUI at {args.comfy_url} ({getattr(e, 'reason', e)}). Is it running? "
              "`chimera doctor` checks.", file=sys.stderr)
        sys.exit(1)
    except TimeoutError:   # a request ComfyUI accepted but didn't answer in time (busy, or wedged)
        print(f"ComfyUI at {args.comfy_url} stopped answering (timed out). Is it busy or stuck? "
              "`chimera doctor` checks.", file=sys.stderr)
        sys.exit(1)


def main():
    for stream in (sys.stdout, sys.stderr):   # a name outside the console's code page crashed a piped run
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(prog="generate.py")
    from scripts.brandkit import __version__
    ap.add_argument("--version", action="version", version=f"chimera {__version__}")
    sub = ap.add_subparsers(dest="modality", required=True)
    img = sub.add_parser("image", help="text-to-image, product mockups, logo overlays and relighting "
                                      "(Qwen-Image-2.1 by default)"); _add_common(img)
    img.add_argument("--subject", required=True)
    img.add_argument("--mode", choices=["txt2img", "logo", "product", "relight"], default="txt2img")
    img.add_argument("--asset", default=None)
    img.add_argument("--variant", choices=["base", "turbo"], default=None,
                     help="Z-Image fidelity: turbo (8-step, default for txt2img/logo) or base "
                          "(25-step, default for product img2img)")
    img.add_argument("--model", default=None,
                     help="override the image model/family by file name (default Qwen-Image-2.1; e.g. "
                          "z_image_turbo_nvfp4.safetensors for Z-Image, flux2_dev_fp8mixed.safetensors for FLUX.2)")
    img.add_argument("--upscale", action="store_true",
                     help="4x upscale of the output with SeedVR2 (decode -> [watermark] -> upscale -> save)")
    img.add_argument("--upscale-model", dest="upscale_model", default=None,
                     help=f"override the upscaler (default {image_filler.DEFAULT_UPSCALE_MODEL}, in "
                          "models/diffusion_models/; an ESRGAN model such as 4x-UltraSharp.pth, in "
                          "models/upscale_models/, selects the ESRGAN pass)")
    vid = sub.add_parser("video", help="image-to-video (Wan 2.2 by default; --model ltx23 for synced audio)")
    _add_common(vid)
    vid.add_argument("--subject", required=True)
    vid.add_argument("--from-image", dest="from_image", required=True,
                     help="start frame: a file in brands/<brand>/products|references/ or outputs/images/")
    vid.add_argument("--mode", choices=["i2v"], default="i2v")
    vid.add_argument("--model", default=None,
                     help="video model: wan22 (default; steady camera, silent) | ltx23 (built-in synced audio), "
                          "or a model file name")
    vid.add_argument("--camera", choices=list(video_filler.CAMERA_POSES), default=None,
                     help="(Wan) a controlled camera via Wan 2.2 Fun Camera: static keeps it locked while the "
                          "scene moves; pans/zooms/rotations move it")
    vid.add_argument("--quality", choices=["fast", "full"], default=None,
                     help="(Wan) fast = 4-step LoRAs, ~35 s on an RTX 5090 (default without --camera); full = 20 "
                          "steps, ~3 min, more scene motion (default with --camera)")
    # defaults stay None so the brand.yaml video: block (LTX) / Wan's native clip wins in the filler
    vid.add_argument("--length", type=int, default=None,
                     help="frames (default: Wan 81 at 16 fps; LTX brand video.length, else 97); snapped down to "
                          "what the model renders, 4k+1 for Wan and 8k+1 for LTX")
    vid.add_argument("--fps", type=int, default=None,
                     help="default: Wan 16; LTX brand video.fps, else 25 (Wan's motion is timed for 16 fps, so "
                          "another value only changes its playback speed)")
    vid.add_argument("--width", type=int, default=None, help="default: brand video.width, else 768")
    vid.add_argument("--height", type=int, default=None, help="default: brand video.height, else 512")
    vid.add_argument("--audio", dest="audio", action="store_true", default=None,
                     help="(LTX) force synced audio on (default: brand video.audio, else on); Wan clips are silent")
    vid.add_argument("--no-audio", dest="audio", action="store_false")
    vid.add_argument("--upscale", action="store_true",
                     help="(LTX) 2x spatial latent upscale (temporally coherent; precedes watermark)")
    vid.add_argument("--upscale-model", dest="upscale_model", default=None,
                     help=f"override the latent upscaler (default {video_filler.DEFAULT_VIDEO_UPSCALE_MODEL}; "
                          "must be in ComfyUI models/latent_upscale_models/)")
    aud = sub.add_parser("audio", help="music, sound effects and video foley (Stable Audio 3 by default; "
                                      "--model acestep sings --lyrics)"); _add_common(aud)
    aud.add_argument("--mode", choices=["music", "sfx", "foley"], default="music",
                     help="music: a track (Stable Audio 3); sfx: a sound effect (Stable Audio 3); foley: "
                          "synced sound for an existing video")
    aud.add_argument("--subject", required=True,
                     help="music: the sonic brief (e.g. 'logo sting'); sfx / foley: the sound to generate")
    aud.add_argument("--model", default=None,
                     help="(music) sa3 (default) | acestep (ACE-Step 1.5, sings --lyrics), or a model file name")
    aud.add_argument("--from-video", dest="from_video", default=None,
                     help="foley source: a file in brands/<brand>/outputs|references|products/")
    aud.add_argument("--duration", type=float, default=None,
                     help="seconds (default: music = brand audio.music_duration, at least 40 with --lyrics; sfx = "
                          "4, at least 1; foley = the clip)")
    aud.add_argument("--bpm", type=int, default=None, help="(music)")
    aud.add_argument("--keyscale", default=None, help="(music)")
    aud.add_argument("--lyrics", default=None,
                     help="(music, --model acestep) words for ACE-Step to sing; section tags like [Verse 1] and "
                          "[Chorus] on their own lines. Renders at least 40 s unless --duration says otherwise (a 20 s "
                          "clip came out instrumental). From a file: --lyrics \"$(cat song.txt)\"")
    aud.add_argument("--fps", type=float, default=None, help="(foley; default = source fps)")
    td = sub.add_parser("3d", help="image-to-3D mesh (TRELLIS.2, a textured GLB, by default)"); _add_common(td)
    td.add_argument("--mode", choices=["image"], default="image")
    td.add_argument("--from-image", dest="from_image", required=True,
                    help="source image: a file in brands/<brand>/products|references/ or outputs/images/")
    td.add_argument("--octree", type=int, default=None,
                    help="(Hunyuan3D only) VAEDecodeHunyuan3D octree_resolution (detail vs size)")
    td.add_argument("--model", default=None,
                    help="3D model: trellis2 (default; textured PBR GLB) | pixal3d (textured, matches the "
                         "photo's viewpoint) | hunyuan21 (shape only, ~4x faster), or a model file name")
    td.add_argument("--format", choices=["glb", "stl", "obj"], default=None,
                    help="3D export format (default glb; stl/obj are converted host-side, geometry only, and the GLB "
                         "stays beside them)")
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
    rn.add_argument("--watertight", action="store_true",
                    help="(finish) voxel-remesh to a closed surface; for already-solid meshes such as Hunyuan3D 2.1. "
                         "A TRELLIS.2 or Pixal3D mesh comes out hollow this way: use --solid")
    rn.add_argument("--solid", action="store_true",
                    help="(finish) rebuild a thin, double-sided AI mesh (TRELLIS.2, Pixal3D) as one solid for "
                         "printing: closes leaks, keeps only the outer skin, Poisson-reconstructs it. Needs "
                         "--scale-mm and the [print] extra; about 3 minutes on the CPU for a 230 mm print")
    rn.add_argument("--scale-mm", dest="scale_mm", type=float, default=None,
                    help="(finish) longest side in mm; STL is always written in millimetres")
    rn.add_argument("--color", choices=["auto", "material", "project", "keep"], default="auto",
                    help="(finish) auto (default): keep a textured mesh's own materials (e.g. a TRELLIS.2 PBR GLB, "
                         "exported with JPEG textures), else clay; material = clay; project = --project-image; "
                         "keep = always keep")
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
    ft.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
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
                    help="route the result into the outputs folder for its media type + write a fresh sidecar, "
                         "under the render's standard name, or <name>_replay when that is taken (omit to just re-render and print the raw "
                         "ComfyUI filename)")
    rp.add_argument("--comfy-url", default=None,
                    help=f"ComfyUI to render on (default {DEFAULT_COMFY_URL}; the sidecar's recorded URL is not "
                         "trusted, since sidecars get shared)")
    rp.add_argument("--model", default=None,
                    help="re-run the recorded render on a different model (e.g. old brand work on a newer "
                         "model); without it replay pins the model the render used")
    rp.add_argument("--accept-drift", dest="accept_drift", action="store_true",
                    help="render even if the brand or a template changed since the original render "
                         "(replay stops and lists the differences otherwise)")
    nb = sub.add_parser("new-brand", help="scaffold a new brand folder from brands/_template/")
    nb.add_argument("name", help="brand folder name (used as --brand later)")
    lt = sub.add_parser("lint", help="validate a brand.yaml + check referenced assets")
    lt.add_argument("--brand", required=True)
    dr = sub.add_parser("doctor", help="preflight: check ComfyUI, node packs, models, a brand, and GPU memory")
    dr.add_argument("--brand", default=None, help="also check this brand's manifest/assets/model")
    dr.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    dr.add_argument("--ollama-url", default=None,
                    help="local Ollama to report on (default: $OLLAMA_HOST, else http://127.0.0.1:11434)")
    fr = sub.add_parser("free", help="free GPU memory: unload every Ollama model, then ComfyUI's models")
    fr.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    fr.add_argument("--ollama-url", default=None,
                    help="local Ollama (default: $OLLAMA_HOST, else http://127.0.0.1:11434)")
    uc = sub.add_parser("update-check",
                        help="report available updates (chimera repo, ComfyUI, pip deps, node packs)")
    uc.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    uc.add_argument("--no-network", action="store_true", help="skip the GitHub release lookup")
    args = ap.parse_args()
    if getattr(args, "brand", None) and not brand_name_ok(args.brand):
        # before anything renders: route_output refuses it afterwards, leaving the render in ComfyUI's folder
        ap.error(f"--brand {args.brand!r} isn't a brand folder name (one plain name, not starting with '.')")

    repo_root = Path(__file__).resolve().parents[1]
    _check_repo_layout(repo_root, ap)
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
        from scripts.brandkit.gpu import gpu_checks
        client = ComfyClient(args.comfy_url)
        from scripts.agent.llm import local_model_checks   # the CLI may import the agent layer, not the reverse
        results = (run_checks(client, repo_root, args.brand) + gpu_checks(client, args.ollama_url)
                   + local_model_checks(client, args.ollama_url))
        fails = print_doctor(args.brand, results)
        sys.exit(1 if fails else 0)
    if args.modality == "free":
        from scripts.brandkit.gpu import free_all, print_free
        print_free(free_all(ComfyClient(args.comfy_url), args.ollama_url))
        return
    if args.modality == "update-check":
        from scripts.brandkit.updates import check_updates, latest_comfyui_release, print_updates
        client = ComfyClient(args.comfy_url)
        latest = None if args.no_network else latest_comfyui_release()
        print_updates(check_updates(client, repo_root, latest_comfyui=latest))
        return
    if args.modality == "replay":
        try:
            data = json.loads(Path(args.sidecar).read_text(encoding="utf-8-sig"))   # PowerShell 5.1 adds a BOM
        except (OSError, ValueError) as e:   # missing, unreadable, or not JSON (e.g. the render itself)
            ap.error(f"cannot read {args.sidecar} as a sidecar: {e}")
        if not isinstance(data, dict):
            ap.error(f"cannot replay {args.sidecar}: not a sidecar")
        try:
            rargs = _args_from_sidecar(data, seed=args.seed,
                                       comfy_output_dir=args.comfy_output_dir,
                                       comfy_url=args.comfy_url, model=args.model)
        except (ValueError, KeyError) as e:
            ap.error(f"cannot replay {args.sidecar}: {e}")
        rargs.expect, rargs.accept_drift, rargs.model_override = data, args.accept_drift, args.model
        rec = str(data.get("comfy_url") or "")
        if rec and not args.comfy_url and rec.rstrip("/") != rargs.comfy_url.rstrip("/"):
            print(f"note: the render used ComfyUI at {rec}; replaying on {rargs.comfy_url} "
                  "(pass --comfy-url to change)", file=sys.stderr)
        for note in replay_notes(data):
            print(f"note: {note}", file=sys.stderr)
        print(f"replaying {args.sidecar} (modality={rargs.modality} mode={rargs.mode} "
              f"brand={rargs.brand} seed={rargs.seed} model={rargs.model})", flush=True)
        _run_comfy(rargs, repo_root, ap)
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
    if getattr(args, "upscale_model", None) and not args.upscale:
        ap.error("--upscale-model picks the upscaler for --upscale; add --upscale")
    if args.modality == "audio" and args.mode != "music" and (args.bpm is not None or args.keyscale):
        ap.error(f"--bpm/--keyscale are music settings; audio --mode {args.mode} doesn't use them")
    _run_comfy(args, repo_root, ap)


if __name__ == "__main__":
    main()

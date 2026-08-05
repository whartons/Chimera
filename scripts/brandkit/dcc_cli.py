"""Headless DCC subcommand orchestration for the generate CLI: `render` (Blender),
`cad` (FreeCAD), and `finalize-texture` (multi-view bake, optionally --auto-repaint via
ComfyUI SDXL depth-ControlNet + IPAdapter). Lives beside the runners (blender.py/freecad.py)
and the finalize engine (finalize.py) it drives; generate.py just parses args and dispatches
here. Functions take (args, repo_root, ap) — argparse-shaped on purpose, ap.error() is the
user-facing validation channel."""
from __future__ import annotations
import datetime
import random
import shutil
import sys
import tempfile
from pathlib import Path

from . import blender as blender_runner
from . import finalize as finalize_core
from . import freecad as freecad_runner
from .comfy import ComfyClient
from .manifest import default_manifest, load_manifest
from .outputs import route_output, write_sidecar
from .provenance import git_provenance
from .sidecar import build_cad_meta, build_render_meta

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
    if args.mode == "finish":
        # host-side validation like the cad path: mesh_finish.py only exports these — anything
        # else would silently exit 0 with no export
        bad = [f for f in (x.strip().lower() for x in args.formats.split(",")) if f and f not in ("stl", "glb")]
        if bad:
            ap.error(f"render --mode finish supports --formats stl,glb (got {','.join(bad)}); "
                     "for step/obj use `generate.py cad --mode convert`")
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
                from . import montage
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

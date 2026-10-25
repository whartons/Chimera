"""Preflight 'doctor' checks for a render — surface the things that make a render fail BEFORE
you wait minutes for one: is ComfyUI reachable, are the workflow templates' node types installed,
is a brand's model present, are the brand manifest + assets valid, and are the optional host
helpers available.

Takes an injected `client` (needs `system_stats()` and `object_info()`) so it's unit-testable
without a live server. Returns a checklist of (level, message) tuples — same shape as
scaffold.lint_brand — rendered ASCII-only (Windows cp1252 safe)."""
from __future__ import annotations
import json
from pathlib import Path

from .manifest import load_manifest, ManifestError
from .scaffold import lint_brand, _LEVEL_MARK


def _template_class_types(repo_root):
    """Every ComfyUI node class_type used across the tracked workflow templates — so we can check
    each is actually installed (a missing one means a custom node pack isn't installed)."""
    types = set()
    for p in sorted((Path(repo_root) / "workflows" / "templates").glob("*.json")):
        try:
            g = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for node in g.values():
            if isinstance(node, dict) and isinstance(node.get("class_type"), str):
                types.add(node["class_type"])
    return types


def _repaint_class_types():
    """Node class_types of the Phase-4b auto-repaint graph — built inline by repaint.build (no
    tracked template), so derive them from a dummy build; they can never drift from the builder."""
    from .repaint import build
    wf = build(depth_image="d.png", concept_image="c.png", positive="p", seed=0,
               prev_view_image="v.png")
    return {n["class_type"] for n in wf.values()}


def _required_class_types(repo_root):
    """Everything a full pipeline run can queue: the tracked templates PLUS the inline
    auto-repaint graph (finalize-texture --auto-repaint would otherwise fail mid-run on a box
    doctor had just called healthy)."""
    return _template_class_types(repo_root) | _repaint_class_types()


def _available_models(object_info):
    """Every model filename ComfyUI offers across loader nodes — so a brand's model can be checked
    as actually installed. ComfyUI encodes a dropdown as [[choice, ...], {...}]; the first element
    is the list of choices."""
    models = set()
    for spec in (object_info or {}).values():
        if not isinstance(spec, dict):
            continue
        inputs = spec.get("input", {})
        for section in ("required", "optional"):
            fields = inputs.get(section, {}) if isinstance(inputs, dict) else {}
            for field in (fields.values() if isinstance(fields, dict) else ()):
                if not (isinstance(field, list) and field):
                    continue
                if isinstance(field[0], list):              # classic dropdown: [[choice, ...], {...}]
                    models.update(c for c in field[0] if isinstance(c, str))
                elif field[0] == "COMBO" and len(field) > 1 and isinstance(field[1], dict):
                    # v3 nodes (ComfyUI 0.40): ["COMBO", {"options": [...]}] - missed before, so doctor
                    # flagged an installed birefnet.safetensors as missing
                    models.update(c for c in field[1].get("options", []) if isinstance(c, str))
    return models


_MODEL_EXTS = (".safetensors", ".sft", ".ckpt", ".pth", ".pt", ".gguf", ".bin")


def _model_files(wf):
    """Model files a built graph loads: its string inputs that end in a weights extension."""
    return sorted({v for k, n in wf.items() if not str(k).startswith("_") and isinstance(n, dict)
                   for v in (n.get("inputs") or {}).values()
                   if isinstance(v, str) and v.lower().endswith(_MODEL_EXTS)})


def _default_model_files(repo_root):
    """[(label, model, docs, files)] for every modality's DEFAULT model, read off a dummy build of the real
    default graph, so the list can't drift from the fillers. A build that fails is skipped."""
    from . import audio, threed, video, workflow
    from .manifest import default_manifest
    m, r = default_manifest(), repo_root
    specs = (
        ("image", "Qwen-Image-2.1", "modules/image/models.md",
         lambda: _model_files(workflow.build(r, m, positive="p", negative="", seed=0))),
        ("--upscale", "SeedVR2 7B", "modules/image/models.md",
         lambda: [workflow.DEFAULT_UPSCALE_MODEL, workflow.SEEDVR2_VAE]),
        ("video", "Wan 2.2", "modules/video/models.md",
         lambda: _model_files(video.build(r, m, positive="p", negative="", seed=0, from_image="x.png"))),
        ("video --camera", "Wan 2.2 Fun Camera", "modules/video/models.md",
         lambda: _model_files(video.build(r, m, positive="p", negative="", seed=0, from_image="x.png",
                                          camera="static"))),
        ("music / sfx", "Stable Audio 3", "modules/audio/models.md",
         lambda: _model_files(audio.build(r, m, positive="p", seed=0))),
        ("3d", "TRELLIS.2", "modules/threed/models.md",
         lambda: _model_files(threed.build(r, m, seed=0, from_image="x.png"))),
    )
    out = []
    for label, model, docs, files in specs:
        try:
            out.append((label, model, docs, files()))
        except Exception:   # a missing/edited template: skip the row rather than break doctor
            continue
    return out


def run_checks(client, repo_root, brand=None):
    """Run the preflight checks and return a [(level, message)] checklist (level in
    ok/warn/fail/info). Never raises — an unreachable ComfyUI is reported, not thrown."""
    out = []

    # 1. ComfyUI reachable + version (tolerant of a malformed-but-reachable /system_stats)
    reachable = False
    try:
        stats = client.system_stats()
        sysinfo = (stats.get("system") or {}) if isinstance(stats, dict) else {}
        ver = sysinfo.get("comfyui_version") or "unknown version"
        out.append(("ok", f"ComfyUI reachable ({ver})"))
        reachable = True
    except Exception as e:  # any transport/parse error means "not reachable"
        out.append(("fail", f"ComfyUI not reachable - start it / check --comfy-url "
                            f"({type(e).__name__})"))

    # 2. required node types installed (only if reachable)
    object_info = None
    if reachable:
        try:
            object_info = client.object_info()
        except Exception:
            out.append(("warn", "couldn't read /object_info - skipping node + model checks"))
    if object_info is not None:
        missing = sorted(_required_class_types(repo_root) - set(object_info))
        if missing:
            out.append(("warn", f"{len(missing)} required workflow node type(s) not installed - "
                                "these belong to optional modality packs; install only the ones you "
                                f"need (see docs/CATALOG.md): {', '.join(missing)}"))
        else:
            out.append(("ok", "all required workflow node types are installed"))
        # every modality's default model files (each needed only if you use that modality)
        avail = _available_models(object_info)
        for label, model, docs, files in _default_model_files(repo_root):
            missing = [f for f in files if f not in avail]
            if not missing:
                out.append(("ok", f"{label} default ({model}) installed"))
            else:
                out.append(("warn", f"{label} default ({model}): {len(missing)} of {len(files)} model file(s) "
                                    f"missing - {', '.join(missing)} - needed only for {label} (see {docs})"))

    # 3. brand manifest + assets (reuse the lint checklist verbatim), then 4. its models.
    # Load the manifest ONCE and share it with lint; on a load failure lint reports it.
    if brand:
        try:
            m = load_manifest(Path(repo_root) / "brands" / brand / "brand.yaml")
        except ManifestError:
            m = None
        out.extend(lint_brand(repo_root, brand, manifest=m))
        if object_info is not None and m is not None:
            avail = _available_models(object_info)
            model = m.defaults.model
            if model and model in avail:
                out.append(("ok", f"defaults.model installed in ComfyUI ({model})"))
            elif model:
                out.append(("warn", f"defaults.model not found in ComfyUI ({model}) - download "
                                    "it into the right models/ folder (see modules/image/models.md)"))
            # also verify any explicitly-configured non-image modality models
            from .threed import canonical as _canonical_3d   # a brand may pin a 3D short name (pixal3d)
            from .video import canonical as _canonical_video   # short names (ltx23) resolve to files
            from .audio import canonical as _canonical_audio   # (acestep, sa3)
            for label, mdl in (("video", _canonical_video(m.video.model) if m.video.model else None),
                               ("audio.music", _canonical_audio(m.audio.music_model) if m.audio.music_model else None),
                               ("audio.foley", m.audio.foley_model),
                               ("3d", _canonical_3d(m.threed.model) if m.threed.model else None)):
                if not mdl:
                    continue
                if mdl in avail:
                    out.append(("ok", f"{label} model installed in ComfyUI ({mdl})"))
                else:
                    out.append(("warn", f"{label} model not found in ComfyUI ({mdl}) - "
                                        "needed only if you use this modality"))

    # 5. optional host helpers (used by generate.py; graceful fallbacks exist, so info not fail)
    for mod, pkg, why in (("PIL", "pillow", "non-PNG logo sizing"),
                          ("av", "av", "foley fps/duration auto-probe"),
                          ("skimage", "-e .[print]",   # scikit-image pulls in numpy + scipy, the rest of [print]
                           "3D printing: render --mode finish --solid + the STL print check")):
        try:
            __import__(mod)
            out.append(("ok", f"{mod} available ({why})"))
        except ImportError:
            out.append(("info", f"{mod} not installed - optional ({why}); pip install {pkg}"))
    return out


def print_doctor(brand, results) -> int:
    """Print the checklist (ASCII only, Windows-safe) and return the fail count (for the exit code)."""
    fails = sum(1 for lvl, _ in results if lvl == "fail")
    warns = sum(1 for lvl, _ in results if lvl == "warn")
    print(f"doctor: {'brand ' + brand if brand else 'environment'}")
    for lvl, msg in results:
        print(f"  {_LEVEL_MARK.get(lvl, '[?]   ')} {msg}")
    print(f"  -> {fails} fail, {warns} warn")
    return fails

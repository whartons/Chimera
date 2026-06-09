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


def _available_models(object_info):
    """Every model filename ComfyUI offers across loader nodes — so a brand's model can be checked
    as actually installed. ComfyUI encodes a dropdown as [[choice, ...], {...}]; the first element
    is the list of choices."""
    models = set()
    for spec in (object_info or {}).values():
        if not isinstance(spec, dict):
            continue
        req = spec.get("input", {}).get("required", {})
        if not isinstance(req, dict):
            continue
        for field in req.values():
            if isinstance(field, list) and field and isinstance(field[0], list):
                models.update(c for c in field[0] if isinstance(c, str))
    return models


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
        missing = sorted(_template_class_types(repo_root) - set(object_info))
        if missing:
            out.append(("warn", f"{len(missing)} workflow-template node type(s) not installed - "
                                "these belong to optional modality packs; install only the ones you "
                                f"need (see docs/CATALOG.md): {', '.join(missing)}"))
        else:
            out.append(("ok", "all workflow-template node types are installed"))

    # 3. brand manifest + assets (reuse the lint checklist verbatim), then 4. its models
    if brand:
        out.extend(lint_brand(repo_root, brand))
        if object_info is not None:
            try:
                m = load_manifest(Path(repo_root) / "brands" / brand / "brand.yaml")
                avail = _available_models(object_info)
                model = m.defaults.model
                if model and model in avail:
                    out.append(("ok", f"defaults.model installed in ComfyUI ({model})"))
                elif model:
                    out.append(("warn", f"defaults.model not found in ComfyUI ({model}) - download "
                                        "it into the right models/ folder (see modules/image/models.md)"))
                # also verify any explicitly-configured non-image modality models
                for label, mdl in (("video", m.video.model), ("audio.music", m.audio.music_model),
                                   ("audio.foley", m.audio.foley_model), ("3d", m.threed.model)):
                    if not mdl:
                        continue
                    if mdl in avail:
                        out.append(("ok", f"{label} model installed in ComfyUI ({mdl})"))
                    else:
                        out.append(("warn", f"{label} model not found in ComfyUI ({mdl}) - "
                                            "needed only if you use this modality"))
            except ManifestError:
                pass  # lint_brand already reported the manifest problem

    # 5. optional host helpers (used by generate.py; graceful fallbacks exist, so info not fail)
    for mod, pkg, why in (("PIL", "pillow", "non-PNG logo sizing"),
                          ("av", "av", "foley fps/duration auto-probe")):
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

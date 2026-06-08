"""Scaffold a new brand from brands/_template/ and lint a brand.yaml + its referenced assets.

new_brand / lint_brand are reusable library functions (no printing); print_lint renders the
lint checklist to stdout in ASCII (Windows cp1252) and returns the fail count for the exit code.
"""
from __future__ import annotations
import re, shutil
from pathlib import Path

from .manifest import load_manifest, ManifestError

_LEVEL_MARK = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]", "info": "[info]"}


def new_brand(repo_root, name) -> Path:
    """Copy brands/_template/ to brands/<name>/, refuse if it exists, seed the name: field."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"invalid brand name {name!r}: use a simple folder-safe name")
    src = Path(repo_root) / "brands" / "_template"
    if not src.is_dir():
        raise FileNotFoundError(f"template not found: {src}")
    dest = Path(repo_root) / "brands" / name
    if dest.exists():
        raise FileExistsError(f"brand already exists: {dest}")
    shutil.copytree(src, dest)
    try:
        yaml_path = dest / "brand.yaml"
        text = yaml_path.read_text(encoding="utf-8")
        text = re.sub(r'(?m)^name:.*$', f'name: "{name}"', text, count=1)
        yaml_path.write_text(text, encoding="utf-8")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def lint_brand(repo_root, brand) -> list[tuple[str, str]]:
    """Validate brands/<brand>/brand.yaml and check referenced assets. Returns a checklist of
    (level, message) where level in {ok, warn, fail, info}. Reads files; never prints."""
    brand_dir = Path(repo_root) / "brands" / brand
    yaml_path = brand_dir / "brand.yaml"
    try:
        m = load_manifest(yaml_path)
    except ManifestError as e:
        return [("fail", f"brand.yaml did not load: {e}")]

    out: list[tuple[str, str]] = [("ok", f"brand.yaml loaded (name: {m.name!r})")]

    if m.name.strip().lower() == "your brand":
        out.append(("warn", "name is still the template placeholder 'Your Brand'"))

    model = (m.defaults.model or "").lower()
    if model.startswith("z_image") or model.startswith("flux2"):
        out.append(("ok", f"defaults.model family recognized ({m.defaults.model})"))
    else:
        out.append(("warn", f"defaults.model {m.defaults.model!r} doesn't match a known image "
                            "family (z_image*/flux2*); it will be treated as FLUX.2 - typo?"))

    if m.logo.default:
        logo = brand_dir / "logos" / m.logo.default.split("/")[-1]
        if logo.exists():
            out.append(("ok", f"logo.default present: logos/{logo.name}"))
        else:
            out.append(("fail", f"logo.default set but missing: {logo}"))
    else:
        out.append(("info", "no logo.default - logo-overlay mode & --watermark unavailable"))

    if m.watermark.enabled_default and not m.logo.default:
        out.append(("warn", "watermark.enabled_default is true but no logo.default is set"))

    if m.lora.file:
        out.append(("info", f"brand LoRA configured: {m.lora.file.split('/')[-1]} "
                            "(must be installed in ComfyUI models/loras/)"))

    return out


def print_lint(brand, results) -> int:
    """Print the lint checklist (ASCII only) and return the number of 'fail' entries."""
    fails = sum(1 for lvl, _ in results if lvl == "fail")
    warns = sum(1 for lvl, _ in results if lvl == "warn")
    print(f"lint: brands/{brand}")
    for lvl, msg in results:
        print(f"  {_LEVEL_MARK.get(lvl, '[?]   ')} {msg}")
    print(f"  -> {fails} fail, {warns} warn")
    return fails

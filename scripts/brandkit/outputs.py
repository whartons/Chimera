"""Route a finished render to the per-brand outputs/ folder, organized by media type."""
from __future__ import annotations
import json, shutil, time
from pathlib import Path

# Outputs are grouped by what the file IS (extension-driven), so a foley clip (a video) lands
# with the videos and a music stinger with the audio — see media_subdir().
_MEDIA_DIRS = {
    "images": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"},
    "video":  {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"},
    "audio":  {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus"},
    "3d":     {".glb", ".gltf", ".obj", ".ply", ".fbx", ".stl"},
}


def brand_output_dir(repo_root, brand: str) -> Path:
    return Path(repo_root) / "brands" / brand / "outputs"


def media_subdir(suffix: str) -> str:
    """Media-type subfolder for a file extension ('images'|'video'|'audio'|'3d'),
    or '' for an unrecognized extension (routed flat)."""
    suffix = suffix.lower()
    for sub, exts in _MEDIA_DIRS.items():
        if suffix in exts:
            return sub
    return ""


def route_output(repo_root, brand, src, mode: str, seed: int, _retries=5, _delay=0.4) -> Path:
    src = Path(src)
    if not brand:
        return src
    out_dir = brand_output_dir(repo_root, brand)
    sub = media_subdir(src.suffix)
    if sub:
        out_dir = out_dir / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{brand}_{mode}_{seed}{src.suffix}"
    last = None
    for _ in range(max(1, _retries)):
        try:
            # idempotent: re-rendering the same brand/mode/seed overwrites cleanly
            # (shutil.move raises on Windows if the destination already exists).
            if dest.exists():
                dest.unlink()
            shutil.move(str(src), str(dest))
            return dest
        except PermissionError as e:
            # transient lock: a sync client (OneDrive) or AV is scanning the just-written
            # file. Back off briefly and retry rather than losing the render.
            last = e
            time.sleep(_delay)
    raise last


class NoOutputError(RuntimeError):
    pass


def first_output(files):
    """Return the first (filename, subfolder, type) tuple, or raise NoOutputError.
    ComfyUI returns no new output for an identical (cached) graph, so callers must not
    blindly index files[0]."""
    if not files:
        raise NoOutputError("no outputs produced (an identical render may be cached — "
                            "try a different --seed)")
    return files[0]


def write_sidecar(output_path, meta: dict):
    """Write a <output>.json reproducibility sidecar next to a routed output. Records the
    resolved model filename, seed, mode, prompts, etc. — so months later you know which
    model produced a file. Paths in meta should be basenames/repo-relative, never absolute."""
    side = Path(output_path).with_suffix(".json")
    side.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return side

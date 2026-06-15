"""Route a finished render to the per-brand outputs/ folder, organized by media type."""
from __future__ import annotations
import json, shutil, time
from pathlib import Path
from .nodes import find_node_by_title, NodeNotFound

# Outputs are grouped by what the file IS (extension-driven), so a foley clip (a video) lands
# with the videos and a music stinger with the audio — see media_subdir().
_MEDIA_DIRS = {
    "images": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"},
    "video":  {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"},
    "audio":  {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus"},
    "3d":     {".glb", ".gltf", ".obj", ".ply", ".fbx", ".stl",
               ".step", ".stp", ".iges", ".igs", ".brep"},   # CAD (BREP) outputs group with 3D geometry
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
    """Relocate a finished render into its outputs folder, grouped by media type. With a brand it
    goes to brands/<brand>/outputs/<media>/<brand>_<mode>_<seed>; brandless (brand falsy) it goes to
    the global outputs/<media>/<mode>_<seed> — both gitignored. Idempotent + lock-retry."""
    src = Path(src)
    base = brand_output_dir(repo_root, brand) if brand else Path(repo_root) / "outputs"
    sub = media_subdir(src.suffix)
    out_dir = base / sub if sub else base
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{brand}_{mode}_{seed}" if brand else f"{mode}_{seed}"
    dest = out_dir / f"{stem}{src.suffix}"
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


def first_output(files, prefer_node_id=None):
    """Return the chosen (filename, subfolder, type) tuple, or raise NoOutputError.

    ComfyUI returns no new output for an identical (cached) graph, so callers must not blindly
    index files[0]. With `prefer_node_id` set, `files` are (node_id, filename, subfolder, type)
    4-tuples (from ComfyClient.output_files_by_node) and the file produced by that node — e.g. the
    graph's titled `brand:save` node — is returned (node id stripped), so a graph with more than
    one save node still routes the intended render; it falls back to the first file if the
    preferred node produced none. With no `prefer_node_id`, `files` are plain (filename, subfolder,
    type) tuples and the first is returned (legacy behavior)."""
    if not files:
        raise NoOutputError("no outputs produced (an identical render may be cached — "
                            "try a different --seed)")
    if prefer_node_id is not None:
        match = next((f for f in files if f[0] == prefer_node_id), files[0])
        return tuple(match[1:])
    return files[0]


def select_output(client, prompt_id, wf, save_title="brand:save"):
    """Pick the canonical output file for a finished prompt, anchored on the node titled
    `save_title` so a multi-save graph still routes the intended render rather than whatever
    ComfyUI listed first. Degrades to the legacy first-file behavior when the graph has no such
    titled node. Returns (filename, subfolder, type) or raises NoOutputError."""
    try:
        save_id, _ = find_node_by_title(wf, save_title)
    except NodeNotFound:
        return first_output(client.output_filenames(prompt_id))
    return first_output(client.output_files_by_node(prompt_id), prefer_node_id=save_id)


def write_sidecar(output_path, meta: dict):
    """Write a <output>.json reproducibility sidecar next to a routed output. Records the
    resolved model filename, seed, mode, prompts, etc. — so months later you know which
    model produced a file. Paths in meta should be basenames/repo-relative, never absolute."""
    side = Path(output_path).with_suffix(".json")
    side.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return side

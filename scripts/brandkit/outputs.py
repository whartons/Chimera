"""Route a finished render to the per-brand outputs/ folder, organized by media type."""
from __future__ import annotations
import itertools, json, os, shutil, time, unicodedata, uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from .nodes import find_node_by_title, NodeNotFound
from .sidecar import render_identity

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


def _unused_stem(out_dir, stem: str, tag="replay", reuse=None) -> str:
    """The first of stem, stem_replay, stem_replay2, ... (with tag "": stem, stem_2, stem_3, ...) that no file
    in out_dir uses (render, sidecar or checks file), or that `reuse(name)` accepts although it is taken.
    out_dir may be several folders (one job's files), and the name must be free in each. The sidecar counts:
    a 3D render converted to STL leaves no GLB under its stem. Compared without case, as Windows names are: a
    differently-cased brand replaced the render it reproduced."""
    dirs = [Path(out_dir)] if isinstance(out_dir, (str, os.PathLike)) else [Path(d) for d in out_dir]
    names = [p.name.casefold() for d in dirs if d.is_dir() for p in d.iterdir()]
    cands = itertools.chain((stem,), (f"{stem}_{tag}",) if tag else (),
                            (f"{stem}_{tag}{n}" for n in itertools.count(2)))
    return next(c for c in cands
                if not any(n.startswith(c.casefold() + ".") for n in names) or (reuse is not None and reuse(c)))


def _same_render(sidecar: Path, identity) -> bool:
    """Whether the sidecar on disk records the render `identity` describes (sidecar.render_identity)."""
    if identity is None:
        return False
    try:
        return render_identity(json.loads(sidecar.read_text(encoding="utf-8-sig"))) == identity
    except (OSError, ValueError):   # gone, unreadable or not JSON: not provably the same render
        return False


def _output_stem(brand, mode, seed) -> str:
    stem = f"{brand}_{mode}_{seed}" if brand else f"{mode}_{seed}"
    if not plain_name(stem) or (brand and not brand_name_ok(brand)):
        # mode and brand can come from a shared sidecar: never let them name a folder (2026-10 review)
        raise NoOutputError(f"refusing to name an output {stem!r}: brand and mode must be plain names")
    return stem


def _output_dir(repo_root, brand, suffix) -> Path:
    base = brand_output_dir(repo_root, brand) if brand else Path(repo_root) / "outputs"
    sub = media_subdir(suffix)
    return base / sub if sub else base


def job_stem(repo_root, brand, srcs, mode: str, seed) -> str:
    """One name for a job that routes several files (a FreeCAD STEP + STL, a Blender PNG + GLB): the first of
    <stem>, <stem>_2, ... that is free in every folder they route to. Pass it to route_output(stem=...) for
    each file: routed one by one, the second file found the first one's name taken (2026-10-25 review)."""
    stem = _output_stem(brand, mode, seed)
    return _unused_stem({_output_dir(repo_root, brand, Path(s).suffix) for s in srcs}, stem, tag="")


def plain_name(value) -> bool:
    """True for one plain file or folder name: no separator, drive, root or '..' in either OS's spelling, not
    '.', no control characters, no trailing space or dot (Windows drops those). Names that arrive from
    outside (a sidecar's brand and mode, ComfyUI's file names) must stay a single name."""
    v = str(value)
    return (v not in ("", ".", "..") and v == PureWindowsPath(v).name == PurePosixPath(v).name and ":" not in v
            and v.strip() == v and not v.endswith(".") and not any(ord(ch) < 32 for ch in v))


_NOT_IN_A_FOLDER_NAME = set('<>:"/\\|?*')   # what Windows refuses in a file or folder name


def brand_name_ok(name) -> bool:
    """A brand folder name new-brand creates and replay accepts: one plain name, not hidden, nothing Windows
    refuses in a folder name and no control character. `new-brand 'what?'` passed, then copytree raised
    WinError 123; a '"' broke brand.yaml's name: line on POSIX (2026-10-25 review)."""
    v = str(name)
    return (plain_name(v) and not v.startswith(".") and not _NOT_IN_A_FOLDER_NAME.intersection(v)
            and not any(unicodedata.category(ch) == "Cc" for ch in v))


def route_output(repo_root, brand, src, mode: str, seed: int, _retries=5, _delay=0.4, *,
                 keep_existing=False, identity=None, stem=None, producer="ComfyUI") -> Path:
    """Relocate a finished render into its outputs folder, grouped by media type. With a brand it
    goes to brands/<brand>/outputs/<media>/<brand>_<mode>_<seed>; brandless (brand falsy) it goes to
    the global outputs/<media>/<mode>_<seed> — both gitignored. Lock-retry.
    A name that is taken is replaced only by the same render: `identity` (sidecar.render_identity of the new
    render's sidecar) equal to what the earlier render's sidecar records, a true re-render. Anything else (another
    prompt, setting or input file with the same seed, or a caller that passes no identity) takes the next free
    name, `<stem>_2`, `<stem>_3`, ...: 'a red cat' then 'a blue dog' with --seed 7 left only the dog, and its
    sidecar (2026-10-25 review). A render identical to one of those numbered ones replaces it.
    `keep_existing` (replay) never replaces a file: a replay keeps the recorded seed, so it used to
    overwrite the very render and sidecar it reproduced, which is permanent for gitignored brand
    outputs. It takes the next free name instead (`<stem>_replay`, `<stem>_replay2`, ...).
    `stem` routes to exactly that name, for a job whose files share one (job_stem picked it free).
    `producer` names the app that reported the file, for the error when it isn't there."""
    src = Path(src)
    if not src.is_file():
        if producer != "ComfyUI":
            raise NoOutputError(f"{producer} listed {src.name} as an output, but the file isn't there")
        raise NoOutputError(f"ComfyUI reported {src.name}, but it isn't in its output folder (is --comfy-output-dir "
                            "ComfyUI's output folder?)")
    default = _output_stem(brand, mode, seed)   # refuses a brand or mode that isn't a plain name, either way
    named = stem is not None   # the caller picked the name for the whole job: route to it as it is
    if named and not plain_name(stem):
        raise NoOutputError(f"refusing to name an output {stem!r}: it must be a plain name")
    stem = stem if named else default
    out_dir = _output_dir(repo_root, brand, src.suffix)
    out_dir.mkdir(parents=True, exist_ok=True)
    if keep_existing:
        stem = _unused_stem(out_dir, stem)
    elif not named:
        stem = _unused_stem(out_dir, stem, tag="", reuse=lambda c: _same_render(out_dir / f"{c}.json", identity))
    dest = out_dir / f"{stem}{src.suffix}"
    last = None
    for _ in range(max(1, _retries)):
        try:
            # the same render's file is replaced (shutil.move raises on Windows if the destination exists)
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


def select_output(client, prompt_id, wf, save_title="brand:save", history=None):
    """Pick the canonical output file for a finished prompt, anchored on the node titled
    `save_title` so a multi-save graph still routes the intended render rather than whatever
    ComfyUI listed first. Degrades to the legacy first-file behavior when the graph has no such
    titled node. Returns (filename, subfolder, type) or raises NoOutputError. Pass the dict
    wait() returned as `history` to spare a /history re-fetch (only forwarded when set, so
    duck-typed test clients without the kwarg keep working)."""
    hkw = {"history": history} if history else {}
    try:
        save_id, _ = find_node_by_title(wf, save_title)
    except NodeNotFound:
        return first_output(client.output_filenames(prompt_id, **hkw))
    return first_output(client.output_files_by_node(prompt_id, **hkw), prefer_node_id=save_id)


def unsafe_path(value) -> bool:
    """True for an absolute or '..' path in either OS's spelling (a drive, a root, a climb): names that
    arrive from outside (a sidecar, ComfyUI's /history) must stay inside the folder they are joined to."""
    return any(p.anchor or ".." in p.parts for p in (PureWindowsPath(str(value)), PurePosixPath(str(value))))


def comfy_output_path(out_dir, subfolder, fname) -> Path:
    """The local path of a file ComfyUI reports in /history, under the host's output dir. The names come
    from the server, so an absolute or '..' one (which a hostile server could send to make the CLI move
    any local file into outputs/) is refused."""
    if unsafe_path(subfolder or "") or not plain_name(fname):
        raise NoOutputError(f"ComfyUI reported an output outside its output folder: {subfolder}/{fname}")
    return Path(out_dir) / (subfolder or "") / str(fname)


def fresh_output_name(wf, save_title="brand:save"):
    """Give the graph's save node a unique filename prefix before queueing. ComfyUI serves a job identical to
    an earlier one from its cache and reports the earlier file, which Chimera had already moved out of
    ComfyUI's folder, so repeating a run with the same --seeds failed with "cannot find the file" (2026-10).
    With a new prefix only the save node re-runs and writes a fresh file; the render itself still comes from
    the cache. Replay's checks ignore the prefix. Returns `wf`, changed in place."""
    try:
        _, node = find_node_by_title(wf, save_title)
    except NodeNotFound:
        return wf
    prefix = node.get("inputs", {}).get("filename_prefix")
    if isinstance(prefix, str):
        node["inputs"]["filename_prefix"] = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return wf


def run_graph_to_file(client, wf, out_dir, *, timeout=900):
    """Queue a built graph, wait for it, and return the produced file's LOCAL path under
    `out_dir` (the host's ComfyUI output dir). Anchors on the graph's brand:save node via
    select_output and reuses wait()'s history record (no /history re-fetch) — the
    queue -> wait -> select -> local-path dance every generator was hand-rolling."""
    pid = client.queue_prompt(fresh_output_name(wf))
    hist = client.wait(pid, max_wait=timeout)
    fname, subfolder, _ = select_output(client, pid, wf, history=hist)
    return comfy_output_path(out_dir, subfolder, fname)


def write_sidecar(output_path, meta: dict):
    """Write a <output>.json reproducibility sidecar next to a routed output. Records the
    resolved model filename, seed, mode, prompts, etc. — so months later you know which
    model produced a file. Paths in meta should be basenames/repo-relative, never absolute."""
    side = Path(output_path).with_suffix(".json")
    side.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return side

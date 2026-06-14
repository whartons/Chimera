"""Headless Blender job runner: spawn `blender --background --python <template> -- <json>` per
job (fresh process — bpy imports once), parse the one-line result manifest the template prints.
Pure host-side plumbing; templates carry all bpy knowledge. The `_runner` seam keeps it GPU-free
testable (mock the subprocess)."""
from __future__ import annotations
import json, os, shutil, subprocess

MANIFEST_TAG = "@@CHIMERA_MANIFEST@@"
_DEFAULT_WIN = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"


class BlenderJobError(RuntimeError):
    pass


def find_blender(blender_bin: str | None = None) -> str:
    """Resolve the blender executable: explicit arg, $BLENDER_BIN, PATH, then the default Windows
    install. Raise BlenderJobError with an actionable message if none is found."""
    cand = blender_bin or os.environ.get("BLENDER_BIN") or shutil.which("blender")
    if cand:
        return cand
    if os.path.exists(_DEFAULT_WIN):
        return _DEFAULT_WIN
    raise BlenderJobError(
        "blender executable not found — install Blender >= 5.1, put it on PATH, or set "
        "$BLENDER_BIN (or pass --blender-bin)")


def run_template(template_path, params: dict, *, blender_bin=None, timeout=600,
                 _runner=subprocess.run) -> dict:
    """Run a bpy template headless with `params` (JSON after `--`). Return the parsed manifest
    dict. Raise BlenderJobError on nonzero exit, timeout, or a missing manifest line."""
    exe = find_blender(blender_bin)
    argv = [exe, "--background", "--factory-startup", "--python-exit-code", "1",
            "--python", str(template_path), "--", json.dumps(params)]
    try:
        proc = _runner(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise BlenderJobError(f"blender job timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise BlenderJobError(f"blender exited {proc.returncode}:\n{tail}")
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(MANIFEST_TAG):
            return json.loads(line[len(MANIFEST_TAG):].strip())
    raise BlenderJobError("blender job printed no manifest line (template error?):\n"
                          + (proc.stdout or "")[-2000:])

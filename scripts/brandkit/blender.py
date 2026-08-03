"""Headless Blender job runner: spawn `blender --background --python <template> -- <json>` per
job (fresh process — bpy imports once), parse the one-line result manifest the template prints.
Pure host-side plumbing; templates carry all bpy knowledge. The `_runner` seam keeps it GPU-free
testable (mock the subprocess)."""
from __future__ import annotations
import glob, json, os, shutil, subprocess

MANIFEST_TAG = "@@CHIMERA_MANIFEST@@"
_DEFAULT_GLOB = r"C:\Program Files\Blender Foundation\Blender *\blender.exe"


class BlenderJobError(RuntimeError):
    pass


def find_blender(blender_bin: str | None = None) -> str:
    """Resolve the blender executable: explicit arg, $BLENDER_BIN, PATH, then the default Windows
    install glob (any version, newest wins — parallels the FreeCAD runner). Raise BlenderJobError
    with an actionable message if none is found."""
    cand = blender_bin or os.environ.get("BLENDER_BIN") or shutil.which("blender")
    if cand:
        return cand
    hits = sorted(glob.glob(_DEFAULT_GLOB))
    if hits:
        return hits[-1]                 # newest versioned folder if several
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
            payload = line[len(MANIFEST_TAG):].strip()
            try:
                return json.loads(payload)
            except json.JSONDecodeError as e:
                raise BlenderJobError(
                    f"blender manifest line was not valid JSON ({e}): {payload[:500]}") from e
    # Surface BOTH streams: blender prints template exceptions to stderr and can still exit 0,
    # so callers need stderr to see why the job died (parity with the FreeCAD runner).
    raise BlenderJobError(
        "blender job printed no manifest line (template error?):\n"
        + ("--- stderr ---\n" + (proc.stderr or "")[-1800:] + "\n" if proc.stderr else "")
        + "--- stdout ---\n" + (proc.stdout or "")[-800:])

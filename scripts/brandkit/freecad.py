"""Headless FreeCAD job runner: spawn `FreeCADCmd <template.py> <params.json>` per job, parse the
one-line result manifest the template prints. Pure host-side plumbing; templates carry all FreeCAD
knowledge. Params go through a temp JSON FILE (not inline) because FreeCADCmd exposes script args as
sys.argv=[exe, script, *args] with no `--` separator — a file path avoids all Windows quoting of
JSON's embedded quotes. The `_runner` seam keeps it FreeCAD-free testable (mock the subprocess)."""
from __future__ import annotations
import glob, json, os, shutil, subprocess, tempfile

MANIFEST_TAG = "@@CHIMERA_MANIFEST@@"
_DEFAULT_GLOB = r"C:\Program Files\FreeCAD *\bin\FreeCADCmd.exe"


class FreeCADJobError(RuntimeError):
    pass


def find_freecad(freecad_bin: str | None = None) -> str:
    """Resolve the FreeCADCmd executable: explicit arg, $FREECAD_BIN, PATH (freecadcmd/FreeCADCmd),
    then the default Windows install glob. Raise FreeCADJobError with an actionable message if none."""
    cand = (freecad_bin or os.environ.get("FREECAD_BIN")
            or shutil.which("freecadcmd") or shutil.which("FreeCADCmd"))
    if cand:
        return cand
    hits = sorted(glob.glob(_DEFAULT_GLOB))
    if hits:
        return hits[-1]                 # newest point release if several
    raise FreeCADJobError(
        "FreeCADCmd not found — install FreeCAD >= 1.0, put FreeCADCmd on PATH, or set "
        "$FREECAD_BIN (or pass --freecad-bin)")


def run_template(template_path, params: dict, *, freecad_bin=None, timeout=600,
                 _runner=subprocess.run) -> dict:
    """Run a FreeCAD template headless with `params` (a temp JSON file passed as the script arg).
    Return the parsed manifest dict. Raise FreeCADJobError on nonzero exit, timeout, or missing
    manifest line. The temp params file is removed even on error."""
    exe = find_freecad(freecad_bin)
    fd, pfile = tempfile.mkstemp(prefix="chimera_cad_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(params, fh)
        argv = [exe, str(template_path), pfile]
        try:
            proc = _runner(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise FreeCADJobError(f"FreeCAD job timed out after {timeout}s") from e
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-2000:]
            raise FreeCADJobError(f"FreeCADCmd exited {proc.returncode}:\n{tail}")
        for line in reversed((proc.stdout or "").splitlines()):
            if line.startswith(MANIFEST_TAG):
                payload = line[len(MANIFEST_TAG):].strip()
                try:
                    return json.loads(payload)
                except json.JSONDecodeError as e:
                    raise FreeCADJobError(
                        f"FreeCAD manifest line was not valid JSON ({e}): {payload[:500]}") from e
        # Surface BOTH streams: a script-level exception (e.g. a bad FreeCAD API call) is printed to
        # stderr while FreeCADCmd still exits 0, so the loop's revise feedback needs stderr to be able
        # to self-correct (e.g. "module 'Part' has no attribute 'Vector'").
        raise FreeCADJobError(
            "FreeCAD job printed no manifest line (script error?):\n"
            + ("--- stderr ---\n" + (proc.stderr or "")[-1800:] + "\n" if proc.stderr else "")
            + "--- stdout ---\n" + (proc.stdout or "")[-800:])
    finally:
        try:
            os.unlink(pfile)
        except OSError:
            pass

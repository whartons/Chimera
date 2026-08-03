"""Headless FreeCAD job runner: spawn `FreeCADCmd <template.py>` per job (the params-file path is
handed to the template via the $CHIMERA_CAD_PARAMS env var), parse the one-line result manifest the
template prints. Pure host-side plumbing; templates carry all FreeCAD knowledge. Params go through a
temp JSON FILE referenced by env — NOT a CLI arg — because FreeCAD 1.1.x opens any trailing file
argument as a document (a .json hits the FEM YAML/JSON importer and throws). The `_runner` seam
keeps it testable. Shared plumbing lives in dcc.py (same core as the Blender runner)."""
from __future__ import annotations
import json
import os
import subprocess
import tempfile

from .dcc import MANIFEST_TAG, find_executable, run_and_parse

__all__ = ["MANIFEST_TAG", "FreeCADJobError", "find_freecad", "run_template"]
_DEFAULT_GLOB = r"C:\Program Files\FreeCAD *\bin\FreeCADCmd.exe"


class FreeCADJobError(RuntimeError):
    pass


def find_freecad(freecad_bin: str | None = None) -> str:
    """Resolve the FreeCADCmd executable: explicit arg, $FREECAD_BIN, PATH (freecadcmd/FreeCADCmd),
    then the default Windows install glob. Raise FreeCADJobError with an actionable message if none."""
    return find_executable(
        explicit=freecad_bin, env_var="FREECAD_BIN", path_names=("freecadcmd", "FreeCADCmd"),
        default_glob=_DEFAULT_GLOB, error_cls=FreeCADJobError,
        missing_hint="FreeCADCmd not found — install FreeCAD >= 1.0, put FreeCADCmd on PATH, "
                     "or set $FREECAD_BIN (or pass --freecad-bin)")


def run_template(template_path, params: dict, *, freecad_bin=None, timeout=600,
                 _runner=subprocess.run) -> dict:
    """Run a FreeCAD template headless with `params` (a temp JSON file passed via env).
    Return the parsed manifest dict. Raise FreeCADJobError on timeout, nonzero exit, corrupt
    manifest JSON, or a missing manifest line (with stderr surfaced — a script-level exception,
    e.g. a bad FreeCAD API call, is printed to stderr while FreeCADCmd still exits 0, and the
    CAD loop's revise feedback needs it to self-correct). The temp params file is removed even
    on error."""
    exe = find_freecad(freecad_bin)
    fd, pfile = tempfile.mkstemp(prefix="chimera_cad_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(params, fh)
        # Hand the params path to the template via ENV, not a CLI arg: FreeCAD 1.1.x treats a
        # trailing file as a document to OPEN (a .json hits the FEM importer and throws),
        # polluting stderr + the CAD loop's revise feedback. The template reads
        # $CHIMERA_CAD_PARAMS (sys.argv fallback).
        argv = [exe, str(template_path)]
        env = {**os.environ, "CHIMERA_CAD_PARAMS": pfile}
        return run_and_parse(argv, timeout=timeout, _runner=_runner, error_cls=FreeCADJobError,
                             exe_label="FreeCADCmd", job_label="FreeCAD", reason="script error?",
                             env=env)
    finally:
        try:
            os.unlink(pfile)
        except OSError:
            pass

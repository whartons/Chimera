"""Headless Blender job runner: spawn `blender --background --python <template> -- <json>` per
job (fresh process — bpy imports once), parse the one-line result manifest the template prints.
Pure host-side plumbing; templates carry all bpy knowledge. The `_runner` seam keeps it GPU-free
testable (mock the subprocess). Shared plumbing lives in dcc.py (same core as the FreeCAD runner)."""
from __future__ import annotations
import json
import subprocess

from .dcc import MANIFEST_TAG, find_executable, run_and_parse

__all__ = ["MANIFEST_TAG", "BlenderJobError", "find_blender", "run_template"]
_DEFAULT_GLOB = r"C:\Program Files\Blender Foundation\Blender *\blender.exe"


class BlenderJobError(RuntimeError):
    pass


def find_blender(blender_bin: str | None = None) -> str:
    """Resolve the blender executable: explicit arg, $BLENDER_BIN, PATH, then the default Windows
    install glob (any version, newest wins — parallels the FreeCAD runner). Raise BlenderJobError
    with an actionable message if none is found."""
    return find_executable(
        explicit=blender_bin, env_var="BLENDER_BIN", path_names=("blender",),
        default_glob=_DEFAULT_GLOB, error_cls=BlenderJobError,
        missing_hint="blender executable not found — install Blender >= 5.1, put it on PATH, "
                     "or set $BLENDER_BIN (or pass --blender-bin)")


def run_template(template_path, params: dict, *, blender_bin=None, timeout=600,
                 _runner=subprocess.run) -> dict:
    """Run a bpy template headless with `params` (JSON after `--`). Return the parsed manifest
    dict. Raise BlenderJobError on timeout, nonzero exit, corrupt manifest JSON, or a missing
    manifest line (with stderr surfaced — blender prints template errors there and can exit 0)."""
    exe = find_blender(blender_bin)
    argv = [exe, "--background", "--factory-startup", "--python-exit-code", "1",
            "--python", str(template_path), "--", json.dumps(params)]
    return run_and_parse(argv, timeout=timeout, _runner=_runner, error_cls=BlenderJobError,
                         exe_label="blender", job_label="blender", reason="template error?")

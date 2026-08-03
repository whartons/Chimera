"""Shared core for the headless DCC job runners (Blender + FreeCAD): resolve the executable,
run the template subprocess, and parse the one-line @@CHIMERA_MANIFEST@@ result. The per-tool
modules (blender.py / freecad.py) own their argv/param conventions and error classes; this
module owns the identical plumbing so the two runners can't drift apart again (they already
had once: the Blender side was missing the JSON-error wrap + stderr surfacing FreeCAD had)."""
from __future__ import annotations
import glob
import json
import os
import shutil
import subprocess

MANIFEST_TAG = "@@CHIMERA_MANIFEST@@"


def find_executable(*, explicit=None, env_var=None, path_names=(), default_glob=None,
                    error_cls=RuntimeError, missing_hint=""):
    """Resolve a DCC executable: explicit arg, $ENV var, PATH names in order, then the default
    Windows install glob (any version, newest wins). Raises error_cls(missing_hint) if none."""
    cand = explicit or (os.environ.get(env_var) if env_var else None)
    if not cand:
        for n in path_names:
            cand = shutil.which(n)
            if cand:
                break
    if cand:
        return cand
    hits = sorted(glob.glob(default_glob)) if default_glob else []
    if hits:
        return hits[-1]                 # newest versioned folder if several
    raise error_cls(missing_hint)


def run_and_parse(argv, *, timeout, _runner, error_cls, exe_label, job_label, reason, env=None):
    """Run the job subprocess and parse its manifest line. Raises error_cls on timeout, nonzero
    exit, corrupt manifest JSON, or a missing manifest line — the last with BOTH streams
    surfaced, because these tools print script errors to stderr while still exiting 0."""
    kw = {"env": env} if env is not None else {}
    try:
        proc = _runner(argv, capture_output=True, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired as e:
        raise error_cls(f"{job_label} job timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise error_cls(f"{exe_label} exited {proc.returncode}:\n{tail}")
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(MANIFEST_TAG):
            payload = line[len(MANIFEST_TAG):].strip()
            try:
                return json.loads(payload)
            except json.JSONDecodeError as e:
                raise error_cls(
                    f"{job_label} manifest line was not valid JSON ({e}): {payload[:500]}") from e
    raise error_cls(
        f"{job_label} job printed no manifest line ({reason}):\n"
        + ("--- stderr ---\n" + (proc.stderr or "")[-1800:] + "\n" if proc.stderr else "")
        + "--- stdout ---\n" + (proc.stdout or "")[-800:])

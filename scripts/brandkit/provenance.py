"""Render-time provenance of the pipeline repo itself, recorded in reproducibility sidecars."""
from __future__ import annotations
import subprocess


def git_provenance(repo_root):
    """Best-effort short provenance of the pipeline repo at render time: the HEAD commit (short),
    suffixed `-dirty` if the working tree has uncommitted changes. None when it isn't a git repo or
    git is absent — so a tarball/non-git install still renders. Recorded in the sidecar so a render
    traces back to the exact pipeline code that produced it. Best-effort: never raises."""
    try:
        rev = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if rev.returncode != 0:
            return None
        sha = rev.stdout.strip()
        st = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=5)
        return sha + ("-dirty" if st.stdout.strip() else "")
    except Exception:
        return None

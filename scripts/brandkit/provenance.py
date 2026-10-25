"""Render-time provenance recorded in reproducibility sidecars: the pipeline repo's own commit, and what
the render's input files held."""
from __future__ import annotations
import hashlib, subprocess


def file_digest(path):
    """A short sha256 (16 hex digits) of a file's content, or None if it can't be read. Sidecars keep only an
    input's file name, so replay used whatever file had that name (a Downloads photo instead of the brand's own
    products/rover.png, a logo replaced in place) and reported no drift (2026-10-25 review)."""
    try:
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()[:16]
    except OSError:
        return None


def git_provenance(repo_root):
    """Best-effort short provenance of the pipeline repo at render time: the HEAD commit (short),
    suffixed `-dirty` if a tracked file has uncommitted changes. None when it isn't a git repo or
    git is absent — so a tarball/non-git install still renders. Recorded in the sidecar so a render
    traces back to the exact pipeline code that produced it. Best-effort: never raises."""
    try:
        rev = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if rev.returncode != 0:
            return None
        sha = rev.stdout.strip()
    except Exception:
        return None
    try:
        # untracked files aren't pipeline code: the example brand's new renders made every later one -dirty
        st = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=no"],
                            capture_output=True, text=True, timeout=5)
    except Exception:   # a slow status (a big tree, a cold disk) used to discard the commit read above
        return sha
    return sha + ("-dirty" if st.stdout.strip() else "")

"""`chimera update-check` — report what's outdated across the stack and how to update it, WITHOUT
blindly auto-updating. The security posture matters here: custom node packs are pinned + audited, so
the tool reports + guides rather than pulling `@latest`. Returns a [(level, message)] checklist (same
shape as scaffold.lint_brand / doctor), rendered ASCII-only (Windows cp1252 safe).

Best-effort and offline-tolerant: the GitHub release lookup is injected so it's testable/skippable,
and the git/network calls never raise out of the checker."""
from __future__ import annotations
import json
import urllib.request

from .scaffold import _LEVEL_MARK


def _repo_behind(repo_root):
    """How many commits the local checkout is behind origin/main (int), or None if it isn't a git
    checkout / git is unavailable. Does a best-effort `git fetch` first; offline, it compares against
    the last-known origin/main."""
    import subprocess

    def git(*a):
        return subprocess.run(["git", "-C", str(repo_root), *a],
                              capture_output=True, text=True, timeout=15)
    try:
        if git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return None
    except Exception:
        return None
    try:
        git("fetch", "--quiet", "origin", "main")
    except Exception:
        pass   # hung/offline fetch is fine — compare against the last-known origin/main below
    try:
        r = git("rev-list", "--count", "HEAD..origin/main")
        out = r.stdout.strip()
        return int(out) if r.returncode == 0 and out.isdigit() else None
    except Exception:
        return None


def latest_comfyui_release(timeout=10):
    """Best-effort latest ComfyUI release tag from GitHub, or None (offline / rate-limited)."""
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "chimera"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("tag_name") or None
    except Exception:
        return None


def check_updates(client, repo_root, *, latest_comfyui=None):
    """Report available updates as a [(level, message)] checklist. `latest_comfyui` (a tag string or
    None) is injected so the network lookup is testable/skippable. Never raises."""
    out = []

    # 1. the chimera repo itself
    behind = _repo_behind(repo_root)
    if behind is None:
        out.append(("info", "chimera: not a git checkout (or git unavailable) - skipping repo check"))
    elif behind == 0:
        out.append(("ok", "chimera: up to date with origin/main"))
    else:
        out.append(("warn", f"chimera: {behind} commit(s) behind origin/main - update: git pull --ff-only"))

    # 2. ComfyUI engine (self-updates via the Desktop app; we just surface the gap)
    running = client.comfyui_version()
    if running and latest_comfyui and running.lstrip("v") != latest_comfyui.lstrip("v"):
        out.append(("warn", f"ComfyUI: running {running}, latest {latest_comfyui} - "
                            "update via the ComfyUI Desktop app"))
    elif running:
        out.append(("ok", f"ComfyUI: {running}" + (" (latest)" if latest_comfyui else "")))
    else:
        out.append(("info", "ComfyUI: not reachable - start it to check the version (or --comfy-url)"))

    # 3. Python deps — Dependabot already tracks these on GitHub
    out.append(("info", "pip deps: Dependabot opens weekly update PRs on GitHub; "
                        "locally `pip install -U -e \".[dev]\"`"))

    # 4. pinned third-party deps — security-PINNED, never @latest. Names come from
    # update_report's tables (the same ones the weekly CI check reads) so this line can't drift.
    try:
        from scripts import update_report as _ur
        pins = ", ".join(t[0].split(" (")[0]
                         for t in (_ur.GIT_PACKS + _ur.GITEA_PACKS + _ur.NPM_PACKS))
    except Exception:
        pins = "see docs/STACK.md"
    out.append(("info", f"pinned packs/bridges ({pins}): security-PINNED to audited "
                        "versions - RE-AUDIT before bumping a pin; see docs/UPDATING.md"))
    return out


def print_updates(results) -> int:
    """Print the update checklist (ASCII only, Windows-safe). Returns the number of 'warn' entries
    (things with an available update)."""
    warns = sum(1 for lvl, _ in results if lvl == "warn")
    print("update-check:")
    for lvl, msg in results:
        print(f"  {_LEVEL_MARK.get(lvl, '[?]   ')} {msg}")
    print(f"  -> {warns} update(s) available")
    return warns

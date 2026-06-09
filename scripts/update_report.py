#!/usr/bin/env python3
"""Weekly stack update report — run by `.github/workflows/update-check.yml` on a cron (and on demand).

Checks whether the security-PINNED ComfyUI node packs / MCP server are behind their upstreams and
surfaces the latest ComfyUI release, then lists the standing manual reviews (Python deps via
Dependabot; models via a quarterly CATALOG review). Prints MARKDOWN to stdout, which the workflow
posts as the single "🔄 Weekly update report" issue.

REPORT-ONLY by design — it NEVER bumps a pin. Pins advance only after a fresh manual re-audit (the
pin-and-audit policy); a human acts on this report via docs/UPDATING.md. Best-effort + offline
tolerant: any failed query is reported as "could not check", never raised."""
from __future__ import annotations
import json
import os
import sys
import urllib.request

# Source of truth for the pins is docs/STACK.md — keep this table in sync (see CLAUDE.md docs rule).
GIT_PACKS = [
    ("ComfyUI-LTXVideo", "Lightricks", "ComfyUI-LTXVideo", "229437c"),
    ("ComfyUI-HunyuanVideo-Foley", "phazei", "ComfyUI-HunyuanVideo-Foley", "afd2960"),
    ("ComfyUI-QwenVL", "1038lab", "ComfyUI-QwenVL", "fcd1ada"),
]
NPM_PACKS = [("comfyui-mcp (MCP bridge)", "comfyui-mcp", "0.9.4")]
COMFY_REF = "0.24.1"   # the reference build documented in docs/STACK.md / SETUP.md
MARK = {"ok": "✅", "warn": "⚠️", "info": "ℹ️"}


def _gh(path):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "chimera-update"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")   # higher rate limit in CI
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def check_git_pack(name, owner, repo, pin):
    """Compare the pinned commit to the repo's default branch (GitHub compare API → ahead_by)."""
    try:
        branch = _gh(f"/repos/{owner}/{repo}").get("default_branch", "main")
        cmp = _gh(f"/repos/{owner}/{repo}/compare/{pin}...{branch}")
        ahead = cmp.get("ahead_by", 0)
        if ahead == 0:
            return ("ok", f"**{name}** — pin `{pin}` is current with `{branch}`.")
        newest = (cmp.get("commits") or [{}])[-1].get("sha", "")[:7]
        return ("warn", f"**{name}** — pin `{pin}` is **{ahead} commit(s) behind** `{branch}` "
                        f"(newest `{newest}`). RE-AUDIT the diff before bumping (see UPDATING.md).")
    except Exception as e:
        return ("info", f"**{name}** — could not check upstream ({type(e).__name__}).")


def check_npm(name, pkg, pin):
    try:
        with urllib.request.urlopen(f"https://registry.npmjs.org/{pkg}/latest", timeout=20) as r:
            latest = json.loads(r.read()).get("version")
        if latest and latest != pin:
            return ("warn", f"**{name}** — pinned `{pin}`, latest npm `{latest}`. RE-AUDIT before bumping.")
        return ("ok", f"**{name}** — pinned `{pin}` is the latest.")
    except Exception as e:
        return ("info", f"**{name}** — could not check npm ({type(e).__name__}).")


def check_comfyui():
    """Reference pointer, NOT a 'behind' verdict: ComfyUI Desktop (what Chimera targets) versions
    independently of the comfyanonymous/ComfyUI core repo's GitHub releases, so comparing the two
    streams can't reliably say 'behind'. The authoritative check is `chimera update-check` against
    the running Desktop instance."""
    try:
        tag = _gh("/repos/comfyanonymous/ComfyUI/releases/latest").get("tag_name", "").lstrip("v")
        note = f"latest core GitHub release `{tag}`" if tag else "core release lookup unavailable"
        return ("info", f"**ComfyUI** — reference build `{COMFY_REF}`; {note}. The Desktop app versions "
                        "independently — run `chimera update-check` against your running instance for the "
                        "authoritative check, then smoke-render each modality after any update.")
    except Exception as e:
        return ("info", f"**ComfyUI** — could not check latest release ({type(e).__name__}).")


def gather():
    """Run every (network) check and return the [(level, message)] rows."""
    rows = [check_git_pack(*p) for p in GIT_PACKS]
    rows += [check_npm(*p) for p in NPM_PACKS]
    rows.append(check_comfyui())
    return rows


def build(rows, repo="whartons/ComfyUI-Chimera"):
    """Render the rows into the issue markdown (pure — unit-tested)."""
    base = f"https://github.com/{repo}/blob/main"
    warns = sum(1 for lvl, _ in rows if lvl == "warn")
    lines = [
        "## 🔄 Weekly stack update report",
        "",
        f"**{warns} item(s) flagged.** Report-only — pins are never auto-bumped. Act on anything "
        f"below via [`docs/UPDATING.md`]({base}/docs/UPDATING.md).",
        "",
        "### Pinned node packs · MCP · ComfyUI",
        *[f"- {MARK.get(lvl, 'ℹ️')} {msg}" for lvl, msg in rows],
        "",
        "### Standing manual reviews (not auto-checkable)",
        "- **Python deps & GitHub Actions** — Dependabot opens weekly PRs; review + merge when CI is green.",
        f"- **Models (the quality lever)** — review [`docs/CATALOG.md`]({base}/docs/CATALOG.md) "
        "**quarterly**: has a better model shipped for any modality (image / video / audio / 3D / "
        "judge)? If so, download → smoke-test vs the current default → swap if clearly better → "
        "update CATALOG + STACK.",
        "",
        "_Generated by `.github/workflows/update-check.yml` — re-run it from the Actions tab any time._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")   # the report has emoji; issue body is UTF-8
    print(build(gather(), repo=os.environ.get("GITHUB_REPOSITORY", "whartons/ComfyUI-Chimera")))

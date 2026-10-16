#!/usr/bin/env python3
"""Weekly stack update report — run by `.github/workflows/update-check.yml` on a cron (and on demand).

Checks whether the security-PINNED ComfyUI node packs / MCP servers are behind their upstreams, lists
the published security advisories that affect a pin or a host app's reference version, and compares
the host apps (ComfyUI, Ollama, FreeCAD, Blender, Node.js, Python) with their latest releases and
end-of-life dates, then lists the standing manual reviews (Python deps via Dependabot; models via a
quarterly CATALOG review). Prints MARKDOWN to stdout, which the workflow posts as the single
"🔄 Weekly update report" issue. docs/MAINTENANCE.md says when to act on what.

REPORT-ONLY by design — it NEVER bumps a pin. Pins advance only after a fresh manual re-audit (the
pin-and-audit policy); a human acts on this report via docs/UPDATING.md. Best-effort + offline
tolerant: any failed query is reported as "could not check", never raised."""
from __future__ import annotations
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# Source of truth for the pins is docs/STACK.md — keep this table in sync (see CLAUDE.md docs rule).
GIT_PACKS = [
    ("ComfyUI-LTXVideo", "Lightricks", "ComfyUI-LTXVideo", "15d09ab"),
    ("ComfyUI-HunyuanVideo-Foley", "phazei", "ComfyUI-HunyuanVideo-Foley", "afd2960"),
    ("ComfyUI_IPAdapter_plus", "cubiq", "ComfyUI_IPAdapter_plus", "a0f451a"),
    ("freecad-mcp (FreeCAD MCP)", "neka-nat", "freecad-mcp", "78bf023"),
]
# blender_mcp lives on Blender's Gitea (not GitHub) — checked via the Gitea compare API.
GITEA_PACKS = [("blender_mcp (Blender MCP)", "https://projects.blender.org", "lab", "blender_mcp", "4309a396")]
NPM_PACKS = [("comfyui-mcp (MCP bridge)", "comfyui-mcp", "0.18.0")]
# npm packages held below their latest on purpose, with the issue that tracks why (comfyui-mcp: default-on
# self-update and panel auto-install; the weekly security routine re-scans new releases there)
NPM_HOLDS = {"comfyui-mcp": "#56"}
# the released version a pinned pack is at, where the project tags versions: advisories name affected versions
PACK_VERSIONS = {"neka-nat/freecad-mcp": "0.1.27"}
COMFY_REF = "0.40.0"   # the reference build documented in docs/STACK.md / SETUP.md
# The host apps besides ComfyUI that Chimera is validated against (docs/STACK.md §7 — keep in sync): (name,
# reference version, GitHub repo for releases + security advisories, endoflife.date product for end of life)
HOST_APPS = [
    ("Ollama", "0.40.4", "ollama/ollama", None),
    ("FreeCAD", "1.1.4", "FreeCAD/FreeCAD", None),
    ("Blender", "5.1.2", None, "blender"),
    ("Node.js", "24", None, "nodejs"),
    ("Python (CI)", "3.12", None, "python"),
]
# an advisory with no version range this script can read counts while it is this new (a weekly report then
# shows it about five times, and the monthly update window can't miss it)
ADVISORY_WINDOW_DAYS = 35
MARK = {"ok": "✅", "warn": "⚠️", "info": "ℹ️"}


def _errname(e):
    """Exception label for the report rows: type name + HTTP status when there is one, so a
    failed week reads 'HTTPError 403' (triageable) instead of a bare 'HTTPError'."""
    code = getattr(e, "code", None)
    return f"{type(e).__name__} {code}" if code else type(e).__name__


def _gh(path, _retries=1):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "chimera-update"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")   # higher rate limit in CI
    for attempt in range(_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # retry a transient 5xx once; a 4xx (403 rate limit etc.) won't clear in seconds,
            # so don't burn more quota on it
            if attempt < _retries and e.code >= 500:
                time.sleep(2)
                continue
            raise


def _gitea(host, path):
    req = urllib.request.Request(
        host.rstrip("/") + path,
        headers={"Accept": "application/json", "User-Agent": "chimera-update"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def check_gitea_pack(name, host, owner, repo, pin):
    """Gitea (e.g. projects.blender.org) compare API -> commits-ahead. The Blender MCP is NOT on
    GitHub, so check_git_pack / Dependabot can't reach it."""
    try:
        branch = _gitea(host, f"/api/v1/repos/{owner}/{repo}").get("default_branch", "main")
        ahead = _gitea(host, f"/api/v1/repos/{owner}/{repo}/compare/{pin}...{branch}").get("total_commits", 0)
        if ahead == 0:
            return ("ok", f"**{name}** — pin `{pin}` is current with `{branch}`.")
        return ("warn", f"**{name}** — pin `{pin}` is **{ahead} commit(s) behind** `{branch}`. "
                        f"RE-AUDIT the diff before bumping (see UPDATING.md).")
    except Exception as e:
        return ("info", f"**{name}** — could not check Gitea ({_errname(e)}).")


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
        return ("info", f"**{name}** — could not check upstream ({_errname(e)}).")


def check_npm(name, pkg, pin):
    try:
        with urllib.request.urlopen(f"https://registry.npmjs.org/{pkg}/latest", timeout=20) as r:
            latest = json.loads(r.read()).get("version")
        if latest and latest != pin and pkg in NPM_HOLDS:
            return ("info", f"**{name}** — held at `{pin}` by policy (see {NPM_HOLDS[pkg]}); latest npm `{latest}`. "
                            "The weekly security routine re-scans new releases there.")
        if latest and latest != pin:
            return ("warn", f"**{name}** — pinned `{pin}`, latest npm `{latest}`. RE-AUDIT before bumping.")
        return ("ok", f"**{name}** — pinned `{pin}` is the latest.")
    except Exception as e:
        return ("info", f"**{name}** — could not check npm ({_errname(e)}).")


def _vkey(v):
    """A version's leading numbers as a tuple ('v0.41.0' -> (0, 41, 0)), or None when it starts with none."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(v or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _cmp(a, b):
    """-1 / 0 / 1 for two version tuples, the shorter padded with zeros ('0.40' equals '0.40.0')."""
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


_OPS = {"<": lambda c: c < 0, "<=": lambda c: c <= 0, ">": lambda c: c > 0, ">=": lambda c: c >= 0,
        "=": lambda c: c == 0, "==": lambda c: c == 0}


def _affects(version, vrange):
    """True when a version falls in an advisory's vulnerable_version_range ('<= 1.1.3', '>= 0.19, <= 1.1.0',
    '< 0.28.0'), False when it doesn't, None when either can't be read (free text, or no version known)."""
    v = _vkey(version)
    if v is None or not vrange:
        return None
    for part in str(vrange).split(","):
        m = re.fullmatch(r"\s*(<=|>=|==|<|>|=)?\s*v?(\d+(?:\.\d+)*)\s*", part)
        if not m:
            return None
        if not _OPS[m.group(1) or "="](_cmp(v, _vkey(m.group(2)))):
            return False
    return True


def _recent(iso, days=ADVISORY_WINDOW_DAYS, now=None):
    """Whether an ISO timestamp is at most `days` old (an unreadable one counts, so nothing is dropped)."""
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return True
    now = now or datetime.datetime.now(datetime.UTC)
    return (now - t).days <= days


def check_advisories(name, slug, version=None, pin=None):
    """The repo's published GitHub security advisories that matter here: one whose version range covers the
    version we run; or, when the range can't be read (or we run a commit, not a release), one published after
    the pinned commit, or in the last ADVISORY_WINDOW_DAYS when there is no pin. The freecad-mcp advisory
    (GHSA-v4pw-r6h3-v75q) went unnoticed for three weeks because the report checked only commits."""
    try:
        advisories = _gh(f"/repos/{slug}/security-advisories?state=published&per_page=100") or []
        since = _gh(f"/repos/{slug}/commits/{pin}")["commit"]["committer"]["date"] if pin else None
        hits = []
        for a in advisories:
            verdicts = [_affects(version, v.get("vulnerable_version_range")) for v in a.get("vulnerabilities") or []]
            if verdicts and None not in verdicts:
                if any(verdicts):
                    fixed = sorted({v["patched_versions"] for v in a["vulnerabilities"] if v.get("patched_versions")})
                    hits.append((a, f"affects `{version}`" + (f", fixed in {', '.join(fixed)}" if fixed else "")))
                continue
            published = a.get("published_at") or ""
            if (since and published > since) or (not since and _recent(published)):
                hits.append((a, "published after the pin" if since else "new"))
        what = f"`{version}`" if version else f"pin `{pin}`"
        if not hits:
            return ("ok", f"**{name}** — no published advisory affects {what}.")
        items = "; ".join(f"[{a.get('ghsa_id')}]({a.get('html_url')}) ({a.get('severity', '?')}, {why}): "
                          f"{(a.get('summary') or '').strip()}" for a, why in hits)
        return ("warn", f"**{name}** — {len(hits)} security advisory(ies) to check: {items}")
    except Exception as e:
        return ("info", f"**{name}** — could not check advisories ({_errname(e)}).")


def check_npm_advisories(name, pkg, pin):
    """GitHub's advisory database for an npm package at the pinned version."""
    try:
        advisories = _gh(f"/advisories?ecosystem=npm&affects={pkg}@{pin}&per_page=100") or []
        if not advisories:
            return ("ok", f"**{name}** — no published advisory affects `{pin}`.")
        items = "; ".join(f"[{a.get('ghsa_id')}]({a.get('html_url')}) ({a.get('severity', '?')}): "
                          f"{(a.get('summary') or '').strip()}" for a in advisories)
        return ("warn", f"**{name}** — {len(advisories)} security advisory(ies) affect `{pin}`: {items}")
    except Exception as e:
        return ("info", f"**{name}** — could not check advisories ({_errname(e)}).")


def _eol(product):
    req = urllib.request.Request(f"https://endoflife.date/api/{product}.json", headers={"User-Agent": "chimera-update"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def check_app(name, ref, repo=None, eol=None, today=None):
    """A host app's reference version against its latest GitHub release, or its release line against
    endoflife.date: a newer release is information for the monthly update window, a line past its end of
    life is flagged."""
    try:
        if repo:
            latest = (_gh(f"/repos/{repo}/releases/latest").get("tag_name") or "").lstrip("v")
            if _vkey(latest) and _cmp(_vkey(latest), _vkey(ref)) > 0:
                return ("info", f"**{name}** — reference `{ref}`; latest release `{latest}`.")
            return ("ok", f"**{name}** — reference `{ref}` is the latest release.")
        today = today or datetime.date.today().isoformat()
        cycles = _eol(eol) or []
        rk = _vkey(ref)
        line = next((c for c in cycles if _vkey(c.get("cycle")) and rk[:len(_vkey(c["cycle"]))] == _vkey(c["cycle"])),
                    None)
        if line is None:
            return ("info", f"**{name}** — reference `{ref}`; its release line isn't listed on endoflife.date.")
        end = line.get("eol")
        ended = end is True or (isinstance(end, str) and end <= today)
        newest = cycles[0]
        newer = (f" Newest `{newest.get('latest') or newest.get('cycle')}`"
                 + (" (LTS)" if newest.get("lts") is True else "") + "."
                 if newest is not line else "")
        if ended:
            when = f" on {end}" if isinstance(end, str) else ""
            return ("warn", f"**{name}** — reference `{ref}`: the `{line['cycle']}` line reached end of life{when}."
                            + newer)
        support = f", supported until {end}" if isinstance(end, str) else ""
        return ("info" if newer else "ok",
                f"**{name}** — reference `{ref}` (latest `{line.get('latest')}`{support}).{newer}")
    except Exception as e:
        return ("info", f"**{name}** — could not check releases ({_errname(e)}).")


def check_comfyui():
    """Reference pointer, NOT a 'behind' verdict: ComfyUI Desktop (what Chimera targets) versions
    independently of the Comfy-Org/ComfyUI core repo's GitHub releases, so comparing the two
    streams can't reliably say 'behind'. The authoritative check is `chimera update-check` against
    the running Desktop instance."""
    try:
        tag = _gh("/repos/Comfy-Org/ComfyUI/releases/latest").get("tag_name", "").lstrip("v")
        note = f"latest core GitHub release `{tag}`" if tag else "core release lookup unavailable"
        return ("info", f"**ComfyUI** — reference build `{COMFY_REF}`; {note}. The Desktop app versions "
                        "independently — run `chimera update-check` against your running instance for the "
                        "authoritative check, then smoke-render each modality after any update.")
    except Exception as e:
        return ("info", f"**ComfyUI** — could not check latest release ({_errname(e)}).")


def gather():
    """Run every pin check (network) and return the [(level, message)] rows."""
    rows = [check_git_pack(*p) for p in GIT_PACKS]
    rows += [check_gitea_pack(*p) for p in GITEA_PACKS]
    rows += [check_npm(*p) for p in NPM_PACKS]
    return rows


def gather_advisories():
    """Security advisories against every pin and host app on GitHub (blender_mcp and Blender aren't)."""
    rows = [check_advisories(name, f"{owner}/{repo}", PACK_VERSIONS.get(f"{owner}/{repo}"), pin)
            for name, owner, repo, pin in GIT_PACKS]
    rows += [check_npm_advisories(*p) for p in NPM_PACKS]
    rows.append(check_advisories("ComfyUI", "Comfy-Org/ComfyUI", COMFY_REF))
    rows += [check_advisories(name, repo, ref) for name, ref, repo, _ in HOST_APPS if repo]
    return rows


def gather_apps():
    """The host apps' reference versions against their latest releases and end-of-life dates."""
    return [check_comfyui()] + [check_app(*a) for a in HOST_APPS]


def build(rows, repo="whartons/Chimera", advisories=(), apps=()):
    """Render the rows into the issue markdown (pure — unit-tested)."""
    base = f"https://github.com/{repo}/blob/main"
    warns = sum(1 for lvl, _ in (*rows, *advisories, *apps) if lvl == "warn")

    def section(title, items):
        return [title, *[f"- {MARK.get(lvl, 'ℹ️')} {msg}" for lvl, msg in items], ""] if items else []
    lines = [
        "## 🔄 Weekly stack update report",
        "",
        f"**{warns} item(s) flagged.** Report-only — pins are never auto-bumped. Act on anything "
        f"below via [`docs/UPDATING.md`]({base}/docs/UPDATING.md); "
        f"[`docs/MAINTENANCE.md`]({base}/docs/MAINTENANCE.md) says what can wait for the monthly update window.",
        "",
        *section("### Pinned node packs · MCP servers", rows),
        *section("### Security advisories (pins, ComfyUI, host apps)", advisories),
        *section("### Host apps: reference version vs latest (for the monthly update window)", apps),
        "### Standing manual reviews (not auto-checkable)",
        "- **Python deps, GitHub Actions & pre-commit hooks** — Dependabot opens weekly PRs; review + merge "
        "when CI is green.",
        f"- **Models (the quality lever)** — review [`docs/CATALOG.md`]({base}/docs/CATALOG.md) "
        "**quarterly**: has a better model shipped for any modality (image / video / audio / 3D / "
        "judge)? If so, download → smoke-test vs the current default → swap if clearly better → "
        "update CATALOG + STACK. The monthly update window and the quarterly review each open their own "
        "checklist issue (`.github/workflows/maintenance.yml`).",
        "- **Optional ComfyUI judge (ComfyUI-QwenVL)** — no longer the default (the agent judge runs on a "
        "local Ollama model sized to the GPU). If you use the ComfyUI judge node, re-pin it to a Qwen3-VL-capable commit "
        "(≥ v1.0.4) + re-run the node-pack scan before bumping — it is NOT auto-checked here.",
        "",
        "_Generated by `.github/workflows/update-check.yml` — re-run it from the Actions tab any time._",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")   # the report has emoji; issue body is UTF-8
    print(build(gather(), repo=os.environ.get("GITHUB_REPOSITORY", "whartons/Chimera"),
                advisories=gather_advisories(), apps=gather_apps()))

from __future__ import annotations
from scripts.update_report import build


def test_build_counts_warns_and_renders_sections():
    rows = [
        ("ok", "**A** — pin current."),
        ("warn", "**B** — 3 commit(s) behind."),
        ("info", "**ComfyUI** — reference build."),
    ]
    md = build(rows, repo="owner/repo")
    assert "1 item(s) flagged" in md                          # the single warn is counted
    assert "Weekly stack update report" in md
    assert "Pinned node packs" in md
    assert "Models (the quality lever)" in md                 # the standing quarterly model-review nudge
    assert "owner/repo/blob/main/docs/UPDATING.md" in md      # repo-derived link to the runbook
    assert "✅" in md and "⚠️" in md and "ℹ️" in md           # level marks rendered


def test_build_zero_warns_when_all_ok():
    md = build([("ok", "x"), ("info", "y")])
    assert "0 item(s) flagged" in md


from scripts import update_report as ur


def test_check_gitea_pack_counts_ahead(monkeypatch):
    def fake(host, path):
        return {"total_commits": 4} if "/compare/" in path else {"default_branch": "main"}
    monkeypatch.setattr(ur, "_gitea", fake)
    lvl, msg = ur.check_gitea_pack("blender_mcp", "https://projects.blender.org", "lab", "blender_mcp", "03004fd")
    assert lvl == "warn" and "4 commit(s) behind" in msg


def test_check_gitea_pack_ok_when_current(monkeypatch):
    def fake(host, path):
        return {"total_commits": 0} if "/compare/" in path else {"default_branch": "main"}
    monkeypatch.setattr(ur, "_gitea", fake)
    lvl, _ = ur.check_gitea_pack("blender_mcp", "https://projects.blender.org", "lab", "blender_mcp", "03004fd")
    assert lvl == "ok"


def test_comfyui_qwenvl_not_auto_pinned():
    # The agent judge moved to Ollama Qwen3-VL; ComfyUI-QwenVL is an OPTIONAL path, not an auto-checked pin.
    assert not any(repo == "ComfyUI-QwenVL" for _, _, repo, _ in ur.GIT_PACKS)


def test_freecad_pinned_via_github_git_pack():
    # FreeCAD MCP is on GitHub -> tracked by check_git_pack (GIT_PACKS), pinned to commit 78bf023.
    assert any(owner == "neka-nat" and repo == "freecad-mcp" and pin == "78bf023"
               for _, owner, repo, pin in ur.GIT_PACKS)


# ---- the GitHub / npm / ComfyUI checker arms (previously zero coverage — these guard 4 of the
# ---- 6 pins; a parsing regression would silently degrade the weekly report to info rows)

def test_check_git_pack_warns_when_behind(monkeypatch):
    def fake(path):
        if path.endswith("/compare/abc1234...main"):
            return {"ahead_by": 4, "commits": [{"sha": "1111111aaa"}, {"sha": "3b9c5cde4700"}]}
        return {"default_branch": "main"}
    monkeypatch.setattr(ur, "_gh", fake)
    lvl, msg = ur.check_git_pack("PackX", "owner", "repo", "abc1234")
    assert lvl == "warn"
    assert "4 commit(s) behind" in msg
    assert "`3b9c5cd`" in msg          # newest short sha from the LAST compare commit
    assert "RE-AUDIT" in msg


def test_check_git_pack_ok_when_current(monkeypatch):
    def fake(path):
        return {"ahead_by": 0} if "/compare/" in path else {"default_branch": "master"}
    monkeypatch.setattr(ur, "_gh", fake)
    lvl, msg = ur.check_git_pack("PackX", "owner", "repo", "abc1234")
    assert lvl == "ok" and "current with `master`" in msg


def test_check_git_pack_network_failure_degrades_to_info(monkeypatch):
    def boom(path):
        raise OSError("rate limited")
    monkeypatch.setattr(ur, "_gh", boom)
    lvl, msg = ur.check_git_pack("PackX", "owner", "repo", "abc1234")
    assert lvl == "info" and "could not check upstream (OSError)" in msg


def _npm_resp(monkeypatch, payload):
    import io, json as _json
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(ur.urllib.request, "urlopen",
                        lambda url, timeout=0: Resp(_json.dumps(payload).encode()))


def test_check_npm_warns_on_newer_version(monkeypatch):
    _npm_resp(monkeypatch, {"version": "0.48.1"})
    lvl, msg = ur.check_npm("some-mcp", "some-mcp", "0.18.0")
    assert lvl == "warn" and "latest npm `0.48.1`" in msg and "RE-AUDIT" in msg


def test_check_npm_reports_a_held_package_as_policy_not_a_warning(monkeypatch):
    # comfyui-mcp is held on purpose (#56): a weekly warning for it was noise
    _npm_resp(monkeypatch, {"version": "0.52.206"})
    lvl, msg = ur.check_npm("comfyui-mcp (MCP bridge)", "comfyui-mcp", "0.18.0")
    assert lvl == "info" and "held at `0.18.0` by policy (see #56)" in msg and "`0.52.206`" in msg


def test_check_npm_ok_when_pin_is_latest(monkeypatch):
    _npm_resp(monkeypatch, {"version": "0.18.0"})
    lvl, msg = ur.check_npm("comfyui-mcp (MCP bridge)", "comfyui-mcp", "0.18.0")
    assert lvl == "ok" and "is the latest" in msg


def test_check_comfyui_is_reference_info_not_behind_verdict(monkeypatch):
    # Desktop versions independently of the core repo -> ALWAYS an info pointer, never a warn
    monkeypatch.setattr(ur, "_gh", lambda path: {"tag_name": "v0.99.0"})
    lvl, msg = ur.check_comfyui()
    assert lvl == "info"
    assert ur.COMFY_REF in msg and "`0.99.0`" in msg and "update-check" in msg


def test_check_git_pack_failure_includes_http_status(monkeypatch):
    # 'could not check upstream (HTTPError)' told us nothing when all four GitHub rows failed
    # in the 2026-08-10 report — the row must carry the status code for after-the-fact triage
    import urllib.error
    def boom(path):
        raise urllib.error.HTTPError("https://api.github.com" + path, 403, "rate limited", {}, None)
    monkeypatch.setattr(ur, "_gh", boom)
    lvl, msg = ur.check_git_pack("PackX", "owner", "repo", "abc1234")
    assert lvl == "info" and "HTTPError 403" in msg


def test_gh_retries_transient_5xx_once(monkeypatch):
    import io, urllib.error
    calls = {"n": 0}
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def flaky(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {}, None)
        return Resp(b'{"default_branch": "main"}')
    monkeypatch.setattr(ur.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(ur.time, "sleep", lambda s: None)
    assert ur._gh("/repos/o/r") == {"default_branch": "main"}
    assert calls["n"] == 2


def test_gh_does_not_retry_4xx(monkeypatch):
    import urllib.error
    calls = {"n": 0}
    def limited(req, timeout=0):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 403, "rate limited", {}, None)
    monkeypatch.setattr(ur.urllib.request, "urlopen", limited)
    monkeypatch.setattr(ur.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(urllib.error.HTTPError):
        ur._gh("/repos/o/r")
    assert calls["n"] == 1   # a rate limit won't clear in seconds — don't burn more quota


def test_gh_sends_bearer_token_when_env_set(monkeypatch):
    import io, json as _json
    seen = {}
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def capture(req, timeout=0):
        seen["auth"] = req.get_header("Authorization")
        return Resp(_json.dumps({}).encode())
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setattr(ur.urllib.request, "urlopen", capture)
    ur._gh("/repos/o/r")
    assert seen["auth"] == "Bearer tok123"


def test_failure_rows_carry_errname_across_all_checkers(monkeypatch):
    # npm / comfyui / gitea failure paths all degrade to an info row labeled with _errname
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(ur.urllib.request, "urlopen", boom)
    lvl, msg = ur.check_npm("N", "pkg", "1.0.0")
    assert lvl == "info" and "OSError" in msg
    monkeypatch.setattr(ur, "_gh", boom)
    lvl, msg = ur.check_comfyui()
    assert lvl == "info" and "OSError" in msg
    monkeypatch.setattr(ur, "_gitea", boom)
    lvl, msg = ur.check_gitea_pack("G", "https://host", "o", "r", "abc")
    assert lvl == "info" and "OSError" in msg


def test_gather_composes_all_pin_rows(monkeypatch):
    monkeypatch.setattr(ur, "check_git_pack", lambda *a: ("ok", "git"))
    monkeypatch.setattr(ur, "check_gitea_pack", lambda *a: ("ok", "gitea"))
    monkeypatch.setattr(ur, "check_npm", lambda *a: ("ok", "npm"))
    rows = ur.gather()
    assert len(rows) == len(ur.GIT_PACKS) + len(ur.GITEA_PACKS) + len(ur.NPM_PACKS)
    assert rows[-1] == ("ok", "npm")


# ---- security advisories and host-app currency (the maintenance cadence, 2026-10) ----------------------

def test_affects_reads_advisory_version_ranges():
    assert ur._affects("1.1.3", "<=1.1.3") is True and ur._affects("1.1.4", "<=1.1.3") is False
    assert ur._affects("1.0.5", ">= 0.19, <= 1.1.0") is True and ur._affects("0.18", ">= 0.19, <= 1.1.0") is False
    assert ur._affects("1.1.4", "< 26.3.0") is True and ur._affects("v0.40.0", "< 0.28.0") is False
    assert ur._affects("0.1.24", "= 0.1.24") is True and ur._affects("0.40", "== 0.40.0") is True
    assert ur._affects("1.1.4", "all versions before the fix") is None    # free text: can't tell
    assert ur._affects(None, "<= 1.0") is None and ur._affects("1.0", None) is None


def _adv(ghsa, published, vrange=None, patched=None, severity="high"):
    vulns = [{"vulnerable_version_range": vrange, "patched_versions": patched}] if vrange else []
    return {"ghsa_id": ghsa, "html_url": f"https://github.com/advisories/{ghsa}", "severity": severity,
            "summary": f"{ghsa} summary", "published_at": published, "vulnerabilities": vulns}


def _fake_gh(advisories, pin_date="2026-09-01T00:00:00Z"):
    def fake(path):
        if "/security-advisories" in path:
            return advisories
        if "/commits/" in path:
            return {"commit": {"committer": {"date": pin_date}}}
        raise AssertionError(path)
    return fake


def test_check_advisories_flags_one_whose_range_covers_our_version(monkeypatch):
    # the FreeCAD one found on the first live run: GHSA-2mfq-2h69-c873 affects 1.1.4, fixed in 26.3.0
    monkeypatch.setattr(ur, "_gh", _fake_gh([_adv("GHSA-aaaa", "2026-07-23T19:12:18Z", "< 26.3.0", "26.3.0"),
                                              _adv("GHSA-bbbb", "2026-09-29T00:00:00Z", "<=1.1.3", "1.1.4")]))
    lvl, msg = ur.check_advisories("FreeCAD", "FreeCAD/FreeCAD", "1.1.4")
    assert lvl == "warn" and "1 security advisory(ies)" in msg
    assert "GHSA-aaaa" in msg and "affects `1.1.4`, fixed in 26.3.0" in msg and "GHSA-bbbb" not in msg


def test_check_advisories_ok_when_no_range_covers_our_version(monkeypatch):
    monkeypatch.setattr(ur, "_gh", _fake_gh([_adv("GHSA-cccc", "2026-07-15T00:00:00Z", "< 0.28.0", "0.28.0")]))
    lvl, msg = ur.check_advisories("ComfyUI", "Comfy-Org/ComfyUI", "0.40.0")
    assert lvl == "ok" and "no published advisory affects `0.40.0`" in msg


def test_check_advisories_flags_one_published_after_a_pin_without_versions(monkeypatch):
    # a node pack pinned to a commit: an advisory after the pin date means the pin's audit predates it
    advs = [_adv("GHSA-late", "2026-09-24T00:00:00Z"), _adv("GHSA-early", "2026-08-01T00:00:00Z")]
    monkeypatch.setattr(ur, "_gh", _fake_gh(advs, pin_date="2026-09-01T00:00:00Z"))
    lvl, msg = ur.check_advisories("PackX", "o/r", pin="abc1234")
    assert lvl == "warn" and "GHSA-late" in msg and "published after the pin" in msg and "GHSA-early" not in msg


def test_check_advisories_counts_an_unreadable_range_only_while_it_is_new(monkeypatch):
    import datetime
    now = datetime.datetime.now(datetime.UTC)
    fresh = (now - datetime.timedelta(days=3)).isoformat().replace("+00:00", "Z")
    stale = (now - datetime.timedelta(days=ur.ADVISORY_WINDOW_DAYS + 10)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(ur, "_gh", _fake_gh([_adv("GHSA-new", fresh, "all versions"),
                                              _adv("GHSA-old", stale, "all versions")]))
    lvl, msg = ur.check_advisories("Ollama", "ollama/ollama", "0.40.4")
    assert lvl == "warn" and "GHSA-new" in msg and "(high, new)" in msg and "GHSA-old" not in msg


def test_check_advisories_degrades_to_info_on_failure(monkeypatch):
    def boom(path):
        raise OSError("offline")
    monkeypatch.setattr(ur, "_gh", boom)
    assert ur.check_advisories("X", "o/r", "1.0") == ("info", "**X** — could not check advisories (OSError).")


def test_check_npm_advisories(monkeypatch):
    seen = []
    def fake(path):
        seen.append(path)
        return [_adv("GHSA-npm1", "2026-10-01T00:00:00Z")] if "bad-pkg" in path else []
    monkeypatch.setattr(ur, "_gh", fake)
    assert ur.check_npm_advisories("comfyui-mcp", "comfyui-mcp", "0.18.0")[0] == "ok"
    assert "affects=comfyui-mcp@0.18.0" in seen[0]    # asks GitHub's database about the pinned version only
    lvl, msg = ur.check_npm_advisories("Bad", "bad-pkg", "1.0.0")
    assert lvl == "warn" and "GHSA-npm1" in msg and "affect `1.0.0`" in msg


def test_check_app_against_its_latest_github_release(monkeypatch):
    monkeypatch.setattr(ur, "_gh", lambda path: {"tag_name": "v0.40.5"})
    assert ur.check_app("Ollama", "0.40.4", "ollama/ollama") == (
        "info", "**Ollama** — reference `0.40.4`; latest release `0.40.5`.")
    monkeypatch.setattr(ur, "_gh", lambda path: {"tag_name": "1.1.4"})
    assert ur.check_app("FreeCAD", "1.1.4", "FreeCAD/FreeCAD")[0] == "ok"


_CYCLES = [{"cycle": "5.2", "latest": "5.2.2", "eol": "2028-07-14", "lts": True},
           {"cycle": "5.1", "latest": "5.1.2", "eol": "2026-07-14", "lts": False},
           {"cycle": "4.5", "latest": "4.5.14", "eol": "2027-07-14", "lts": True}]


def test_check_app_flags_a_release_line_past_its_end_of_life(monkeypatch):
    monkeypatch.setattr(ur, "_eol", lambda product: _CYCLES)
    lvl, msg = ur.check_app("Blender", "5.1.2", eol="blender", today="2026-10-16")
    assert lvl == "warn" and "the `5.1` line reached end of life on 2026-07-14" in msg and "Newest `5.2.2` (LTS)" in msg


def test_check_app_notes_newer_lines_and_passes_the_newest(monkeypatch):
    monkeypatch.setattr(ur, "_eol", lambda product: _CYCLES)
    lvl, msg = ur.check_app("Blender", "4.5", eol="blender", today="2026-10-16")
    assert lvl == "info" and "supported until 2027-07-14" in msg and "Newest `5.2.2`" in msg
    lvl, msg = ur.check_app("Blender", "5.2.2", eol="blender", today="2026-10-16")
    assert lvl == "ok" and "Newest" not in msg
    assert ur.check_app("Blender", "3.0", eol="blender", today="2026-10-16")[0] == "info"   # line not listed


def test_check_app_degrades_to_info_on_failure(monkeypatch):
    def boom(*a):
        raise OSError("offline")
    monkeypatch.setattr(ur, "_eol", boom)
    assert ur.check_app("Python (CI)", "3.12", eol="python") == (
        "info", "**Python (CI)** — could not check releases (OSError).")


def test_gather_advisories_and_apps_cover_every_pin_and_host_app(monkeypatch):
    calls = []
    monkeypatch.setattr(ur, "check_advisories", lambda name, slug, version=None, pin=None: calls.append(
        (name, slug, version, pin)) or ("ok", name))
    monkeypatch.setattr(ur, "check_npm_advisories", lambda *a: ("ok", "npm"))
    rows = ur.gather_advisories()
    assert len(rows) == len(ur.GIT_PACKS) + len(ur.NPM_PACKS) + 1 + sum(1 for a in ur.HOST_APPS if a[2])
    assert ("freecad-mcp (FreeCAD MCP)", "neka-nat/freecad-mcp", "0.1.27", "78bf023") in calls
    assert ("ComfyUI", "Comfy-Org/ComfyUI", ur.COMFY_REF, None) in calls
    monkeypatch.setattr(ur, "check_comfyui", lambda: ("info", "comfy"))
    monkeypatch.setattr(ur, "check_app", lambda *a: ("ok", a[0]))
    apps = ur.gather_apps()
    assert apps[0] == ("info", "comfy") and [m for _, m in apps[1:]] == [a[0] for a in ur.HOST_APPS]


def test_build_renders_the_advisory_and_app_sections_and_counts_their_warnings():
    md = ur.build([("ok", "pin")], repo="o/r", advisories=[("warn", "adv")], apps=[("warn", "eol"), ("info", "new")])
    assert "2 item(s) flagged" in md
    assert "### Security advisories" in md and "### Host apps" in md and "o/r/blob/main/docs/MAINTENANCE.md" in md
    assert "### Security advisories" not in ur.build([("ok", "pin")])     # an empty section is left out


def test_host_app_reference_versions_match_the_stack_doc():
    # STACK.md §7 is the source of truth for the reference versions (CLAUDE.md docs rule)
    from pathlib import Path
    stack = (Path(__file__).resolve().parents[1] / "docs" / "STACK.md").read_text(encoding="utf-8")
    for name, ref, _, _ in ur.HOST_APPS:
        assert f"| {name.split(' (')[0]} | {ref}" in stack, name
    assert f"**{ur.COMFY_REF}**" in stack


def test_recent_counts_an_unreadable_date():
    assert ur._recent("not a date") is True   # dropping it would hide an advisory


def test_check_npm_advisories_degrades_to_info_on_failure(monkeypatch):
    def boom(path):
        raise OSError("offline")
    monkeypatch.setattr(ur, "_gh", boom)
    assert ur.check_npm_advisories("N", "pkg", "1.0.0") == ("info", "**N** — could not check advisories (OSError).")


def test_eol_reads_endoflife_date_with_a_user_agent(monkeypatch):
    import io, json as _json
    seen = {}
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(req, timeout=0):
        seen["url"], seen["ua"] = req.full_url, req.get_header("User-agent")
        return Resp(_json.dumps(_CYCLES).encode())
    monkeypatch.setattr(ur.urllib.request, "urlopen", fake)
    assert ur._eol("blender") == _CYCLES
    assert seen == {"url": "https://endoflife.date/api/blender.json", "ua": "chimera-update"}


def test_the_script_prints_a_whole_report_even_offline(monkeypatch, capsys):
    # every source down: each row degrades to "could not check" and the report still renders all its sections
    import runpy
    def offline(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(ur.urllib.request, "urlopen", offline)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    runpy.run_path(ur.__file__, run_name="__main__")
    out = capsys.readouterr().out
    assert "## 🔄 Weekly stack update report" in out and "0 item(s) flagged" in out
    for section in ("### Pinned node packs", "### Security advisories", "### Host apps"):
        assert section in out, section
    n_pins = len(ur.GIT_PACKS) + len(ur.GITEA_PACKS) + len(ur.NPM_PACKS)
    n_advisories = len(ur.GIT_PACKS) + len(ur.NPM_PACKS) + 1 + sum(1 for a in ur.HOST_APPS if a[2])
    n_apps = 1 + len(ur.HOST_APPS)
    assert out.count("could not check") == n_pins + n_advisories + n_apps   # every row ran; none raised

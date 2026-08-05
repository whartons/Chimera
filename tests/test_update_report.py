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
    # FreeCAD MCP is on GitHub -> tracked by check_git_pack (GIT_PACKS), pinned to commit 4c3f2ef.
    assert any(owner == "neka-nat" and repo == "freecad-mcp" and pin == "4c3f2ef"
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
    lvl, msg = ur.check_npm("comfyui-mcp (MCP bridge)", "comfyui-mcp", "0.18.0")
    assert lvl == "warn" and "latest npm `0.48.1`" in msg and "RE-AUDIT" in msg


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

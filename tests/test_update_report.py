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


def test_freecad_pinned_via_github_git_pack():
    # FreeCAD MCP is on GitHub -> tracked by check_git_pack (GIT_PACKS), pinned to commit 63acb30.
    assert any(owner == "neka-nat" and repo == "freecad-mcp" and pin == "63acb30"
               for _, owner, repo, pin in ur.GIT_PACKS)

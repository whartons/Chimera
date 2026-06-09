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

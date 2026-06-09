from __future__ import annotations
from pathlib import Path

from scripts.agent.auto_generate import _backend_error, _parse_seeds, _resolve_manifest


def test_parse_seeds_comma_separated():
    assert _parse_seeds("7,8,9") == [7, 8, 9]


def test_parse_seeds_none_and_empty_are_none():
    # None / '' are falsy -> None, so the loop falls back to its deterministic seeds
    assert _parse_seeds(None) is None
    assert _parse_seeds("") is None


def test_parse_seeds_skips_blank_segments():
    # whitespace-only / empty segments are dropped, not parsed as ints
    assert _parse_seeds("7, ,8") == [7, 8]
    assert _parse_seeds(" 3 , 4 ") == [3, 4]


def test_resolve_manifest_brandless_returns_neutral_default():
    # brand=None -> the neutral default_manifest(): no brand traits, so build_rubric collapses
    # to subject + quality only and the loop runs as a general (non-branded) QA gate.
    m = _resolve_manifest(Path("/nonexistent/repo"), None)
    assert m.name == "default"
    assert not m.style and not m.palette and not m.negative


def test_local_backend_is_runnable_headless():
    # the local VLM judge is the autonomous path -> no guard, runs in a bare subprocess
    assert _backend_error("local") is None


def test_assistant_backend_rejected_headless():
    # the assistant consensus judge needs the agent's own vision in the loop; a headless subprocess
    # has none, so the CLI must refuse it with a clear, actionable message (optional + agent-gated).
    msg = _backend_error("assistant")
    assert msg and "assistant" in msg.lower() and "local" in msg.lower()


def test_resolve_manifest_with_brand_loads_its_yaml(tmp_path):
    # --brand <name> still loads brands/<name>/brand.yaml from the repo root, unchanged.
    bdir = tmp_path / "brands" / "acme"
    bdir.mkdir(parents=True)
    (bdir / "brand.yaml").write_text(
        "name: ACME\nstyle: rugged tactical\npalette: ['#1c1f22']\n", encoding="utf-8")
    m = _resolve_manifest(tmp_path, "acme")
    assert m.name == "ACME"
    assert m.style == "rugged tactical"
    assert "#1c1f22" in m.palette

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


def test_write_run_sidecar_records_best_iteration_not_last(tmp_path):
    # on exhaustion best_image comes from the highest-scoring iteration, which is often not the
    # last — the sidecar's winning_seed/prompt must describe the file it sits next to
    import argparse, json
    from scripts.agent.auto_generate import _write_run_sidecar
    from scripts.agent.loop import LoopResult, IterRecord
    from scripts.agent.judge import Verdict
    img = tmp_path / "win.png"; img.write_bytes(b"x")
    v_best = Verdict(passed=False, score=0.8, issues=[])
    v_last = Verdict(passed=False, score=0.3, issues=["worse"])
    hist = [IterRecord(iter=0, seed=111, prompt="best prompt", verdict=v_best),
            IterRecord(iter=1, seed=222, prompt="last prompt", verdict=v_last)]
    res = LoopResult(best_image=str(img), best_verdict=v_best, passed=False, history=hist)
    args = argparse.Namespace(brand=None, subject="s", backend="api", comfy_url="http://x")
    _write_run_sidecar(res, args, tmp_path)
    meta = json.loads(img.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["winning_seed"] == 111
    assert meta["winning_prompt"] == "best prompt"


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

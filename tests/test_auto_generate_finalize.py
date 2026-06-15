"""Validation + tail-call wiring for --finalize (mesh3d), GPU/network-free."""
import sys, pytest
import scripts.agent.auto_generate as AG
from scripts.agent.loop import LoopResult


def _run(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", *argv])
    AG.main()


def test_finalize_requires_mesh3d(monkeypatch):
    with pytest.raises(SystemExit):
        _run(["--subject", "x", "--finalize", "--comfy-output-dir", "/tmp/o"], monkeypatch)


def test_finalize_mutually_exclusive_with_texture(monkeypatch):
    with pytest.raises(SystemExit):
        _run(["--pipeline", "mesh3d", "--subject", "x", "--finalize", "--texture",
              "--comfy-output-dir", "/tmp/o"], monkeypatch)


def test_finalize_views_range_validated(monkeypatch):
    with pytest.raises(SystemExit):
        _run(["--pipeline", "mesh3d", "--subject", "x", "--finalize", "--finalize-views", "9",
              "--comfy-output-dir", "/tmp/o"], monkeypatch)


def _wire_main(monkeypatch, tmp_path, seen):
    import scripts.agent.finalize as FIN
    sheet = tmp_path / "win.png"; sheet.write_text("s")
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())
    monkeypatch.setattr(AG, "make_render_generate", lambda *a, **k: (lambda *x: str(sheet)))
    monkeypatch.setattr(AG, "GeometryAwareJudge", lambda j: j)
    monkeypatch.setattr(AG, "LocalVLMJudge", lambda *a, **k: object())
    monkeypatch.setattr(AG, "run_loop",
                        lambda **kw: LoopResult(best_image=str(sheet), best_verdict=None,
                                                passed=True, history=[]))
    monkeypatch.setattr(AG, "_write_run_sidecar", lambda *a, **k: None)
    monkeypatch.setattr(FIN, "finalize_winner",
                        lambda result, args, **k: seen.update(hit=True, best=result.best_image))
    return sheet


def test_finalize_tail_called_when_flag_set(monkeypatch, tmp_path):
    seen = {}
    sheet = _wire_main(monkeypatch, tmp_path, seen)
    _run(["--pipeline", "mesh3d", "--subject", "a mug", "--finalize",
          "--comfy-output-dir", str(tmp_path)], monkeypatch)
    assert seen.get("hit") and seen["best"] == str(sheet)


def test_no_finalize_no_tail_call(monkeypatch, tmp_path):
    seen = {}
    _wire_main(monkeypatch, tmp_path, seen)
    _run(["--pipeline", "mesh3d", "--subject", "a mug", "--comfy-output-dir", str(tmp_path)],
         monkeypatch)
    assert "hit" not in seen

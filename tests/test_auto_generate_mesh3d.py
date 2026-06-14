import sys, json, argparse
import scripts.agent.auto_generate as AG


def test_run_sidecar_modality_3d(tmp_path, monkeypatch):
    from scripts.agent.loop import LoopResult, IterRecord
    from scripts.agent.judge import Verdict
    img = tmp_path / "agent_7.png"
    img.write_text("x")
    res = LoopResult(best_image=str(img), best_verdict=Verdict(True, 0.9, []), passed=True,
                     history=[IterRecord(0, 7, "p", Verdict(True, 0.9, []))])
    args = argparse.Namespace(pipeline="mesh3d", brand=None, subject="a knight",
                              backend="local", comfy_url="http://x")
    monkeypatch.setattr(AG, "git_provenance", lambda r: "deadbee")
    AG._write_run_sidecar(res, args, tmp_path)
    meta = json.loads((tmp_path / "agent_7.json").read_text())
    assert meta["modality"] == "3d" and meta["kind"] == "agent-run"


def test_main_mesh3d_wires_geometry_judge_and_3d_rubric(monkeypatch):
    captured = {}
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())
    monkeypatch.setattr(AG, "make_render_generate",
                        lambda *a, **k: (lambda pos, neg, seed: "x.png"))
    monkeypatch.setattr(AG, "LocalVLMJudge", lambda *a, **k: object())

    def fake_run_loop(**kw):
        captured.update(kw)
        from scripts.agent.loop import LoopResult
        return LoopResult(best_image=None, best_verdict=None, passed=False, history=[])

    monkeypatch.setattr(AG, "run_loop", fake_run_loop)
    monkeypatch.setattr(sys, "argv",
                        ["auto_generate.py", "--pipeline", "mesh3d", "--subject", "a knight",
                         "--comfy-output-dir", "/tmp/out"])
    AG.main()

    from scripts.agent.judge import GeometryAwareJudge
    assert isinstance(captured["judge"], GeometryAwareJudge)
    assert captured["rubric"].noun == "3D render"
    assert captured["max_iters"] == 3   # mesh3d default


def test_main_image_default_max_iters_unchanged(monkeypatch):
    captured = {}
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())
    monkeypatch.setattr(AG, "_make_generate", lambda *a, **k: (lambda p, n, s: "x.png"))
    monkeypatch.setattr(AG, "LocalVLMJudge", lambda *a, **k: object())

    def fake_run_loop(**kw):
        captured.update(kw)
        from scripts.agent.loop import LoopResult
        return LoopResult(best_image=None, best_verdict=None, passed=False, history=[])

    monkeypatch.setattr(AG, "run_loop", fake_run_loop)
    monkeypatch.setattr(sys, "argv",
                        ["auto_generate.py", "--subject", "a rover",
                         "--comfy-output-dir", "/tmp/out"])
    AG.main()
    assert captured["max_iters"] == 4 and captured["rubric"] is None  # image path unchanged

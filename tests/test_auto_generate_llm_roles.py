"""Wiring for per-role LLM clients + LLMExpander selection (GPU/network-free)."""
import sys, pytest
import scripts.agent.auto_generate as AG
import scripts.agent.llm as LLM


class _Stop(Exception):
    pass


def _capture(argv, monkeypatch):
    calls, captured = [], {}
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: calls.append((role, kw)) or _Releasable([], role))

    def fake_loop(**kw):
        captured.update(kw); raise _Stop()

    monkeypatch.setattr(AG, "run_loop", fake_loop)
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())
    monkeypatch.setattr(AG, "make_render_generate", lambda *a, **k: (lambda *x: "s"))
    monkeypatch.setattr(AG, "_make_generate", lambda *a, **k: (lambda *x: "s"))
    monkeypatch.setattr(AG, "GeometryAwareJudge", lambda j: j)
    monkeypatch.setattr(AG, "LocalVLMJudge", lambda *a, **k: object())
    for k in ("CHIMERA_LLM_BASE_URL", "CHIMERA_LLM_MODEL", "CHIMERA_LLM_API_KEY",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", *argv])
    with pytest.raises(_Stop):
        AG.main()
    return calls, captured


def _role(calls, role):
    return next(kw for r, kw in calls if r == role)


def test_cad_api_builds_codegen_and_judge_with_distinct_models(monkeypatch):
    calls, _ = _capture(["--pipeline", "cad", "--backend", "api", "--subject", "a bracket",
                         "--codegen-model", "A", "--judge-model", "B",
                         "--llm-base-url", "http://x/v1"], monkeypatch)
    assert {r for r, _ in calls} == {"codegen", "judge"}
    assert _role(calls, "codegen")["cli_model"] == "A"
    assert _role(calls, "judge")["cli_model"] == "B"
    assert _role(calls, "codegen")["shared_cli_base"] == "http://x/v1"


def test_shared_llm_model_drives_both_roles(monkeypatch):
    calls, _ = _capture(["--pipeline", "cad", "--backend", "api", "--subject", "a bracket",
                         "--llm-base-url", "http://x/v1", "--llm-model", "Z"], monkeypatch)
    for role in ("codegen", "judge"):
        kw = _role(calls, role)
        assert kw["cli_model"] is None and kw["shared_cli_model"] == "Z"


def test_rewrite_prompts_selects_llmexpander(monkeypatch):
    calls, captured = _capture(["--pipeline", "image", "--backend", "local", "--subject", "a knight",
                                "--comfy-output-dir", "/tmp/o", "--rewrite-prompts",
                                "--rewriter-model", "C", "--llm-base-url", "http://x/v1"], monkeypatch)
    assert _role(calls, "rewriter")["cli_model"] == "C"
    assert type(captured["expander"]).__name__ == "LLMExpander"


def test_reasoning_effort_flags_reach_each_role(monkeypatch):
    calls, _ = _capture(["--pipeline", "cad", "--backend", "api", "--subject", "a bracket",
                         "--llm-base-url", "http://x/v1", "--llm-model", "Z",
                         "--llm-reasoning-effort", "none", "--codegen-reasoning-effort", "low"], monkeypatch)
    assert _role(calls, "codegen")["cli_reasoning"] == "low"
    assert _role(calls, "judge")["cli_reasoning"] is None
    assert _role(calls, "judge")["shared_cli_reasoning"] == "none"


class _Releasable:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def release(self):
        self.log.append(("release", self.name))


def test_image_loop_hands_the_gpu_back_before_each_render(monkeypatch):
    # unload the run's Ollama models before every ComfyUI render (keep_alive 0), so a resident LLM
    # never starves ComfyUI on a single GPU
    log, captured = [], {}
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: _Releasable(log, role))
    monkeypatch.setattr(AG, "_make_generate", lambda *a, **k: (lambda p, n, s: log.append(("render", s)) or "x.png"))
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())

    def fake_loop(**kw):
        captured.update(kw)
        raise _Stop()
    monkeypatch.setattr(AG, "run_loop", fake_loop)
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--pipeline", "image", "--backend", "api",
                                      "--subject", "a knight", "--comfy-output-dir", "/tmp/o",
                                      "--rewrite-prompts", "--llm-base-url", "http://x/v1", "--llm-model", "Z"])
    with pytest.raises(_Stop):
        AG.main()
    log.clear()   # drop the end-of-run releases; this checks the per-render hand-off
    captured["generate"]("p", "n", 7)
    assert log == [("release", "judge"), ("release", "rewriter"), ("render", 7)]


class _Result:
    def __init__(self, passed):
        self.passed, self.history, self.best_image, self.best_verdict = passed, [], None, None


def test_every_run_releases_its_llms_when_it_ends(monkeypatch):
    # 2026-10-14: a finished CAD run left its 27B codegen model resident (Ollama keep-alive) and the next
    # ComfyUI job hung. Every run now hands the GPU back on the way out — even when the loop raises.
    log = []
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: _Releasable(log, role))
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())

    def boom(**kw):
        raise RuntimeError("render failed")
    monkeypatch.setattr(AG, "run_loop", boom)
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--pipeline", "cad", "--backend", "api",
                                      "--subject", "a bracket", "--llm-base-url", "http://x/v1",
                                      "--llm-model", "Z"])
    with pytest.raises(RuntimeError):
        AG.main()
    assert sorted(log) == [("release", "codegen"), ("release", "judge")]


def test_finalize_hands_the_gpu_back_before_its_repaint(monkeypatch):
    # --finalize repaints the winner through ComfyUI, so the judge/rewriter models leave the GPU first
    import scripts.agent.finalize as FIN
    log = []
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: _Releasable(log, role))
    monkeypatch.setattr(AG, "make_render_generate", lambda *a, **k: (lambda *x: "s"))
    monkeypatch.setattr(AG, "run_loop", lambda **kw: _Result(True))
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())
    monkeypatch.setattr(AG, "_print_summary", lambda r: None)
    monkeypatch.setattr(AG, "_write_run_sidecar", lambda *a, **k: None)
    monkeypatch.setattr(FIN, "finalize_winner", lambda *a, **k: log.append(("finalize", None)))
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--pipeline", "mesh3d", "--backend", "api",
                                      "--mesh-model", "hunyuan21",   # finalize colors a shape-only mesh
                                      "--finalize", "--rewrite-prompts", "--subject", "a robot",
                                      "--comfy-output-dir", "/tmp/o", "--llm-base-url", "http://x/v1",
                                      "--llm-model", "Z"])
    AG.main()
    assert log[:3] == [("release", "judge"), ("release", "rewriter"), ("finalize", None)]


def _run_to_end(passed, monkeypatch):
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: _Releasable([], role))
    monkeypatch.setattr(AG, "run_loop", lambda **kw: _Result(passed))
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())
    monkeypatch.setattr(AG, "_print_summary", lambda r: None)
    monkeypatch.setattr(AG, "_write_run_sidecar", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--pipeline", "cad", "--backend", "api",
                                      "--subject", "a bracket", "--llm-base-url", "http://x/v1",
                                      "--llm-model", "Z"])
    AG.main()


def test_exit_status_nonzero_when_nothing_passed(monkeypatch):
    # scripts/CI can tell a failed run from a passing one (the 2026-10-14 smoke exited 0 on a total failure)
    with pytest.raises(SystemExit) as e:
        _run_to_end(False, monkeypatch)
    assert e.value.code == 1


def test_exit_status_zero_when_passed(monkeypatch):
    _run_to_end(True, monkeypatch)   # returns normally


def test_no_rewrite_uses_templated_expander(monkeypatch):
    _, captured = _capture(["--pipeline", "image", "--backend", "local", "--subject", "a knight",
                            "--comfy-output-dir", "/tmp/o"], monkeypatch)
    assert type(captured["expander"]).__name__ == "TemplatedExpander"

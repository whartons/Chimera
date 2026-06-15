"""Wiring for per-role LLM clients + LLMExpander selection (GPU/network-free)."""
import sys, pytest
import scripts.agent.auto_generate as AG
import scripts.agent.llm as LLM


class _Stop(Exception):
    pass


def _capture(argv, monkeypatch):
    calls, captured = [], {}
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: calls.append((role, kw)) or object())

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


def test_no_rewrite_uses_templated_expander(monkeypatch):
    _, captured = _capture(["--pipeline", "image", "--backend", "local", "--subject", "a knight",
                            "--comfy-output-dir", "/tmp/o"], monkeypatch)
    assert type(captured["expander"]).__name__ == "TemplatedExpander"

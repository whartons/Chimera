"""Arg-validation wiring for the cad pipeline + the api judge backend (early-exit paths, no GPU/net)."""
import sys, pytest
import scripts.agent.auto_generate as AG


def _run(argv, monkeypatch):
    for k in ("CHIMERA_LLM_BASE_URL", "CHIMERA_LLM_MODEL", "CHIMERA_LLM_API_KEY",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", *argv])
    AG.main()


def test_image_requires_comfy_output_dir(monkeypatch):
    with pytest.raises(SystemExit):
        _run(["--subject", "a rover"], monkeypatch)   # no --comfy-output-dir


def test_cad_local_requires_comfy_output_dir(monkeypatch):
    # cad + local Qwen judge still needs comfy-output-dir (the judge writes there)
    with pytest.raises(SystemExit):
        _run(["--pipeline", "cad", "--subject", "a mug", "--backend", "local"], monkeypatch)


def test_cad_api_with_no_llm_config_uses_chimeras_local_models(monkeypatch):
    # cad + api needs no comfy-output-dir, and with nothing configured every role falls back to Chimera's local
    # Ollama model with thinking off (it used to stop with "set CHIMERA_LLM_BASE_URL")
    import scripts.agent.llm as LLM
    calls = {}

    class _Stop(Exception):
        pass
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: calls.setdefault(role, kw) and None or
                        type("C", (), {"release": lambda self: None, "make_room": None})())
    monkeypatch.setattr(AG, "run_loop", lambda **kw: (_ for _ in ()).throw(_Stop()))
    monkeypatch.setattr(AG, "make_cad_generate", lambda *a, **k: (lambda *x: "s"), raising=False)
    with pytest.raises(_Stop):
        _run(["--pipeline", "cad", "--subject", "a mug", "--backend", "api", "--llm-tier", "small"], monkeypatch)
    small = LLM.LOCAL_TIERS["small"]
    assert (calls["codegen"]["default_model"], calls["codegen"]["default_reasoning"]) == small["codegen"]
    assert (calls["judge"]["default_model"], calls["judge"]["default_reasoning"]) == small["judge"]


def test_assistant_backend_still_gated(monkeypatch):
    with pytest.raises(SystemExit):
        _run(["--subject", "x", "--backend", "assistant", "--comfy-output-dir", "/tmp/o"], monkeypatch)

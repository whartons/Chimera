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


def test_cad_api_without_llm_config_errors(monkeypatch):
    # cad + api needs no comfy-output-dir, but errors without LLM config
    with pytest.raises(SystemExit):
        _run(["--pipeline", "cad", "--subject", "a mug", "--backend", "api"], monkeypatch)


def test_assistant_backend_still_gated(monkeypatch):
    with pytest.raises(SystemExit):
        _run(["--subject", "x", "--backend", "assistant", "--comfy-output-dir", "/tmp/o"], monkeypatch)

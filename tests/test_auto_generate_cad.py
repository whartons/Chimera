"""Arg-validation wiring for the cad pipeline + the api judge backend (early-exit paths, no GPU/net)."""
import sys, pytest
import scripts.agent.auto_generate as AG


def _run(argv, monkeypatch):
    for k in ("CHIMERA_LLM_BASE_URL", "CHIMERA_LLM_MODEL", "CHIMERA_LLM_API_KEY",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", *argv])
    AG.main()


def test_image_requires_comfy_output_dir(monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        _run(["--subject", "a rover"], monkeypatch)   # no --comfy-output-dir
    assert e.value.code == 2 and "--comfy-output-dir is required" in capsys.readouterr().err


def test_cad_local_requires_comfy_output_dir(monkeypatch):
    # cad + local Qwen judge still needs comfy-output-dir (the judge writes there)
    with pytest.raises(SystemExit) as e:
        _run(["--pipeline", "cad", "--subject", "a mug", "--backend", "local"], monkeypatch)
    assert e.value.code == 2


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


def test_assistant_backend_still_gated(monkeypatch, capsys):
    # refused before anything runs: with the gate deleted the whole loop ran and the old test still passed
    monkeypatch.setattr(AG, "run_loop", lambda **kw: pytest.fail("the loop must not run"))
    monkeypatch.setattr(AG, "ComfyClient", lambda url: pytest.fail("no ComfyUI client either"))
    with pytest.raises(SystemExit) as e:
        _run(["--subject", "x", "--backend", "assistant", "--comfy-output-dir", "/tmp/o"], monkeypatch)
    assert e.value.code == 2 and "agent's own vision" in capsys.readouterr().err



def test_the_cad_loop_also_unloads_the_judge_and_rewriter_before_rendering(monkeypatch):
    # code-gen released itself before Blender, but a resident judge sat beside the next iteration's renders
    import scripts.agent.llm as LLM

    class _C:
        def __init__(self, role):
            self.role, self.make_room = role, None

        def release(self):
            return None
    made, wrapped = {}, {}
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: made.setdefault(role, _C(role)))
    monkeypatch.setattr(AG, "_hand_gpu_back",
                        lambda gen, clients: wrapped.setdefault("roles", [c.role for c in clients if c]) and gen)

    class _Stop(Exception):
        pass
    monkeypatch.setattr(AG, "run_loop", lambda **kw: (_ for _ in ()).throw(_Stop()))
    monkeypatch.setattr(AG, "make_cad_generate", lambda *a, **k: (lambda *x: "s"), raising=False)
    with pytest.raises(_Stop):
        _run(["--pipeline", "cad", "--subject", "a mug", "--backend", "api", "--rewrite-prompts",
              "--llm-tier", "small"], monkeypatch)
    assert wrapped["roles"] == ["judge", "rewriter"]


def test_a_judge_on_the_codegen_model_is_left_to_codegen():
    # the large tier runs one model for every role: unloading the judge only made code-gen reload it
    from types import SimpleNamespace as NS
    gen = NS(model="qwen3.8:27b", base_url="http://127.0.0.1:11434/v1")
    assert AG._same_llm(NS(model="Qwen3.8:27b", base_url="http://127.0.0.1:11434/v1"), gen)
    assert not AG._same_llm(NS(model="qwen3-vl:8b-instruct", base_url="http://127.0.0.1:11434/v1"), gen)
    assert not AG._same_llm(NS(model="qwen3.8:27b", base_url="https://api.example.com/v1"), gen)
    assert not AG._same_llm(None, gen) and not AG._same_llm(gen, None)

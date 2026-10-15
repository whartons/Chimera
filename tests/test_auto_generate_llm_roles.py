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
    monkeypatch.setattr(AG, "GeometryAwareJudge", lambda j, **k: j)
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


def test_cad_pipeline_judge_is_geometry_gated(monkeypatch):
    # BREP is manifold, but a script can still build disconnected bodies: the cad judge must be wrapped in
    # the same geometry gate as mesh3d (a VLM passed a fan whose blades floated free of the hub, 2026-10).
    captured = {}
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: _Releasable([], role))
    monkeypatch.setattr(AG, "run_loop", lambda **kw: captured.update(kw) or (_ for _ in ()).throw(_Stop()))
    for k in ("CHIMERA_LLM_BASE_URL", "CHIMERA_LLM_MODEL", "CHIMERA_LLM_API_KEY", "OPENAI_API_KEY",
              "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--pipeline", "cad", "--backend", "api", "--subject",
                                      "a fan rotor", "--llm-base-url", "http://x/v1", "--llm-model", "Z"])
    with pytest.raises(_Stop):
        AG.main()
    assert isinstance(captured["judge"], AG.GeometryAwareJudge)



def test_run_seeds_are_fresh_per_run_unless_given(capsys):
    # the loop's fixed 1000+i default made a second run overwrite the first run's winner
    assert AG._run_seeds("7,8", 3) == [7, 8]
    a, b = AG._run_seeds(None, 3), AG._run_seeds(None, 3)
    assert len(a) == 3 and a[1] == a[0] + 1 and a != b
    assert "repeat this run with --seeds" in capsys.readouterr().err



@pytest.mark.parametrize("gpu_gb, tier", [(31.8, "large"), (23.99, "large"), (16.0, "medium"), (11.99, "medium"),
                                          (8.0, "small"), (None, "medium")])
def test_the_default_judge_is_a_local_ollama_model_sized_to_the_gpu(monkeypatch, capsys, gpu_gb, tier):
    # chosen on a 32 GB card, but forks have less: the local models come in tiers picked from the GPU's memory
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("CHIMERA_LLM_TIER", raising=False)
    monkeypatch.setattr(AG.gpu, "total_memory_gb", lambda client: gpu_gb)
    calls, _ = _capture(["--subject", "a knight", "--comfy-output-dir", "/tmp/o"], monkeypatch)
    judge = _role(calls, "judge")
    assert judge["default_base"] == "http://127.0.0.1:11434/v1"
    assert (judge["default_model"], judge["default_reasoning"]) == LLM.LOCAL_TIERS[tier]["judge"]


def test_an_explicit_tier_skips_the_gpu_probe(monkeypatch):
    monkeypatch.setattr(AG.gpu, "total_memory_gb", lambda client: (_ for _ in ()).throw(AssertionError("probed")))
    calls, _ = _capture(["--subject", "a knight", "--comfy-output-dir", "/tmp/o", "--llm-tier", "large"], monkeypatch)
    assert _role(calls, "judge")["default_model"] == LLM.LOCAL_TIERS["large"]["judge"][0]


def test_the_run_says_which_local_models_it_fell_back_to(monkeypatch, capsys):
    import types
    monkeypatch.setattr(AG.gpu, "total_memory_gb", lambda client: 31.8)
    monkeypatch.setattr(LLM, "client_for_role", lambda role, **kw: types.SimpleNamespace(
        model=kw["default_model"], from_default=True, release=lambda: None, make_room=None))
    monkeypatch.setattr(AG, "ComfyClient", lambda url: object())
    monkeypatch.setattr(AG, "_make_generate", lambda *a, **k: (lambda *x: "s"))
    monkeypatch.setattr(AG, "run_loop", lambda **kw: (_ for _ in ()).throw(_Stop()))
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--subject", "a knight", "--comfy-output-dir", "/tmp/o"])
    with pytest.raises(_Stop):
        AG.main()
    assert "local models, large tier (32 GB GPU): judge qwen3.8:27b" in capsys.readouterr().err



def test_the_loop_lets_local_llms_make_room_on_a_local_comfyui(monkeypatch):
    # the reverse hand-off: before a local Ollama model loads, ComfyUI unloads if the card is full
    import types
    seen = {}
    made = []

    def client_for(role, **kw):
        seen[role] = types.SimpleNamespace(release=lambda: None, make_room=None)
        return seen[role]
    monkeypatch.setattr(LLM, "client_for_role", client_for)
    monkeypatch.setattr(AG, "ComfyClient", lambda url: types.SimpleNamespace(base=url))
    monkeypatch.setattr(AG.gpu, "make_room", lambda client, need: made.append((client.base, need)))
    monkeypatch.setattr(AG, "_make_generate", lambda *a, **k: (lambda *x: "s"))
    monkeypatch.setattr(AG, "run_loop", lambda **kw: (_ for _ in ()).throw(_Stop()))
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--subject", "a knight", "--comfy-output-dir", "/tmp/o"])
    with pytest.raises(_Stop):
        AG.main()
    seen["judge"].make_room(123)
    assert made == [("http://127.0.0.1:8000", 123)]
    seen.clear()
    monkeypatch.setattr(sys, "argv", ["auto_generate.py", "--subject", "a knight", "--comfy-output-dir", "/tmp/o",
                                      "--comfy-url", "http://10.0.0.9:8000"])
    with pytest.raises(_Stop):
        AG.main()
    assert seen["judge"].make_room is None        # a remote ComfyUI can't free this machine's GPU



def test_the_loop_unloads_other_ollama_models_before_its_first_render(monkeypatch, capsys):
    # ComfyUI can't see an Ollama model's memory: an 18 GB model left by another tool plus a render overcommits
    import types
    unloaded = []
    judge = types.SimpleNamespace(base_url="http://127.0.0.1:11434/v1", ollama_name="qwen3-vl:8b-instruct",
                                  release=lambda: None, make_room=None)
    monkeypatch.delenv("CHIMERA_KEEP_LLM_LOADED", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(AG.gpu, "unload_others",
                        lambda root, keep: unloaded.append((root, set(keep))) or [("other-tool:latest", 18 * 2**30)])
    AG._clear_other_ollama_models([None, judge, None])
    assert unloaded == [("http://127.0.0.1:11434", {"qwen3-vl:8b-instruct"})]
    assert "unloaded other-tool:latest (18.0 GB)" in capsys.readouterr().err
    monkeypatch.setenv("CHIMERA_KEEP_LLM_LOADED", "1")
    unloaded.clear()
    AG._clear_other_ollama_models([judge])
    assert unloaded == []



def test_a_remote_default_ollama_is_left_alone(monkeypatch):
    # another machine's Ollama doesn't share this GPU: never unload its models
    monkeypatch.delenv("CHIMERA_KEEP_LLM_LOADED", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:11434")
    called = []
    monkeypatch.setattr(AG.gpu, "unload_others", lambda root, keep: called.append(root) or [])
    AG._clear_other_ollama_models([None])
    assert called == []

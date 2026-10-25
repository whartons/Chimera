import json, pytest
from scripts.agent.llm import (LLMClient, LLMJudge, LLMCadGenerator, LLMConfigError, LLMError,
                               _extract_code)
from scripts.agent.judge import Verdict


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(payload, capture=None):
    def open_(req, timeout=None):
        if capture is not None:
            capture["url"] = req.full_url
            capture["body"] = json.loads(req.data)
            capture["headers"] = {k.lower(): v for k, v in req.header_items()}
            capture["redirected"] = {k.lower() for k in req.headers}   # what urllib copies onto a redirect
        return _Resp(payload)
    return open_


def _msg(content):
    return {"choices": [{"message": {"content": content}}]}


class _Rub:
    def as_prompt(self):
        return "RUBRIC-PROMPT"


def _clear_env(mp):
    for k in ("CHIMERA_LLM_BASE_URL", "CHIMERA_LLM_MODEL", "CHIMERA_LLM_API_KEY",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CHIMERA_LLM_REASONING_EFFORT",
              "CHIMERA_CODEGEN_REASONING_EFFORT", "CHIMERA_JUDGE_REASONING_EFFORT",
              "CHIMERA_REWRITER_REASONING_EFFORT"):
        mp.delenv(k, raising=False)


def test_config_requires_base_url_and_model(monkeypatch):
    _clear_env(monkeypatch)
    with pytest.raises(LLMConfigError, match="BASE_URL"):
        LLMClient(model="m")
    with pytest.raises(LLMConfigError, match="MODEL"):
        LLMClient(base_url="http://x/v1")


def test_config_reads_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_LLM_BASE_URL", "http://e/v1")
    monkeypatch.setenv("CHIMERA_LLM_MODEL", "envmodel")
    monkeypatch.setenv("CHIMERA_LLM_API_KEY", "envkey")
    c = LLMClient()
    assert c.base_url == "http://e/v1" and c.model == "envmodel" and c.api_key == "envkey"


def test_chat_builds_openai_request_and_parses(monkeypatch):
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1/", api_key="k", model="m")   # trailing slash stripped
    cap = {}
    out = c.chat([{"role": "user", "content": "hi"}], _opener=_opener(_msg("hello"), cap))
    assert out == "hello"
    assert cap["url"] == "http://x/v1/chat/completions"
    assert cap["body"]["model"] == "m" and cap["body"]["messages"][0]["content"] == "hi"
    assert cap["headers"]["authorization"] == "Bearer k"


def test_chat_omits_auth_when_keyless(monkeypatch):
    _clear_env(monkeypatch)   # local Ollama-style, no key
    c = LLMClient(base_url="http://localhost:11434/v1", model="llava")
    cap = {}
    c.chat([{"role": "user", "content": "x"}], _opener=_opener(_msg("ok"), cap))
    assert "authorization" not in cap["headers"]


def test_vision_inlines_base64_image(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    img = tmp_path / "i.png"; img.write_bytes(b"\x89PNGfakedata")
    c = LLMClient(base_url="http://x/v1", model="m")
    cap = {}
    c.vision("judge this", str(img), _opener=_opener(_msg("PASS"), cap))
    content = cap["body"]["messages"][0]["content"]
    assert content[0]["text"] == "judge this"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_chat_raises_on_bad_response_shape(monkeypatch):
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m")
    with pytest.raises(LLMError, match="unexpected"):
        c.chat([{"role": "user", "content": "x"}], _opener=_opener({"no_choices": True}))


def test_chat_raises_on_empty_content(monkeypatch):
    # A plain empty/whitespace content is a failure, not a silent "" that flows downstream.
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m")
    with pytest.raises(LLMError, match="empty content"):
        c.chat([{"role": "user", "content": "x"}], _opener=_opener(_msg("   ")))


def test_chat_empty_content_from_thinking_model_explains_cause(monkeypatch):
    # The real-world trap: a 'thinking' VLM (e.g. Ollama qwen3-vl:8b, not -instruct) spends the whole
    # max_tokens budget on its `reasoning` field and returns empty content (finish_reason='length').
    # The error must name the cause + the -instruct fix, not just "empty".
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m")
    thinking = {"choices": [{"finish_reason": "length",
                             "message": {"content": "", "reasoning": "let me think... " * 50}}]}
    with pytest.raises(LLMError, match="thinking.*instruct"):
        c.chat([{"role": "user", "content": "x"}], _opener=_opener(thinking))


# --- reasoning_effort: hybrid-thinking models (Ollama >= 0.40 serves Qwen3.x thinking ON by default) ---
_THINKING = {"choices": [{"finish_reason": "length",
                          "message": {"content": "", "reasoning": "let me think... " * 50}}]}


def _seq_opener(payloads, bodies):
    it = iter(payloads)

    def open_(req, timeout=None):
        bodies.append(json.loads(req.data))
        return _Resp(next(it))
    return open_


def test_chat_omits_reasoning_effort_by_default(monkeypatch):
    # provider-agnostic: never send the knob unless configured (OpenAI non-reasoning models reject it)
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m")
    cap = {}
    c.chat([{"role": "user", "content": "x"}], _opener=_opener(_msg("ok"), cap))
    assert "reasoning_effort" not in cap["body"]


def test_chat_sends_configured_reasoning_effort(monkeypatch):
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m", reasoning_effort="none")
    cap = {}
    c.chat([{"role": "user", "content": "x"}], _opener=_opener(_msg("ok"), cap))
    assert cap["body"]["reasoning_effort"] == "none"


def test_reasoning_effort_reads_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_LLM_REASONING_EFFORT", "low")
    assert LLMClient(base_url="http://x/v1", model="m").reasoning_effort == "low"


def test_thinking_exhaustion_retries_once_with_reasoning_off_and_sticks(monkeypatch):
    # One retry with reasoning_effort="none" recovers; the client keeps it so later calls skip the
    # wasted thinking pass (the 2026-10-14 smoke: Qwen3.6 codegen on Ollama 0.40 thought until max_tokens).
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m")
    bodies = []
    assert c.chat([{"role": "user", "content": "x"}], _opener=_seq_opener([_THINKING, _msg("code")], bodies)) == "code"
    assert "reasoning_effort" not in bodies[0] and bodies[1]["reasoning_effort"] == "none"
    assert c.reasoning_effort == "none"
    c.chat([{"role": "user", "content": "y"}], _opener=_seq_opener([_msg("again")], bodies))
    assert len(bodies) == 3 and bodies[2]["reasoning_effort"] == "none"


def test_thinking_retry_rejected_by_provider_reports_original_cause(monkeypatch):
    import io, urllib.error
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m")

    def open_(req, timeout=None):
        if "reasoning_effort" in json.loads(req.data):
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"unknown field"}'))
        return _Resp(_THINKING)
    with pytest.raises(LLMError, match="thinking.*instruct"):
        c.chat([{"role": "user", "content": "x"}], _opener=open_)
    assert c.reasoning_effort is None   # nothing learned from a failed retry


def test_explicit_reasoning_effort_is_respected_not_retried(monkeypatch):
    _clear_env(monkeypatch)
    c = LLMClient(base_url="http://x/v1", model="m", reasoning_effort="high")
    bodies = []
    with pytest.raises(LLMError, match="thinking"):
        c.chat([{"role": "user", "content": "x"}], _opener=_seq_opener([_THINKING], bodies))
    assert len(bodies) == 1 and bodies[0]["reasoning_effort"] == "high"


class _FakeClient:
    def __init__(self, replies):
        self.replies = list(replies); self.calls = 0; self.seen = []

    def vision(self, prompt, image_path, **kw):
        self.seen.append(("vision", prompt))
        r = self.replies[self.calls % len(self.replies)]; self.calls += 1; return r

    def chat(self, messages, **kw):
        self.seen.append(("chat", messages)); r = self.replies[self.calls % len(self.replies)]
        self.calls += 1; return r


def test_llmjudge_single_pass_parses_verdict():
    j = LLMJudge(_FakeClient(["Overall: PASS\nscore: 0.9"]))
    v = j.judge("img.png", _Rub())
    assert isinstance(v, Verdict) and v.passed and v.score == 0.9


def test_llmjudge_consensus_multi_pass():
    fc = _FakeClient(["Overall: PASS\nscore: 0.8", "Overall: FAIL\nscore: 0.4\nNOT-MET: wrong",
                      "Overall: PASS\nscore: 0.85"])
    j = LLMJudge(fc, passes=3)
    v = j.judge("img.png", _Rub())
    assert fc.calls == 3 and v.passed        # 2/3 PASS -> consensus PASS
    assert fc.seen[0] == ("vision", "RUBRIC-PROMPT")


def test_extract_code_pulls_python_block():
    assert _extract_code("blah\n```python\nimport Part\nx=1\n```\nmore") == "import Part\nx=1"
    assert _extract_code("import Part\nx=1") == "import Part\nx=1"   # unfenced fallback


def test_cad_generator_first_then_revise():
    fc = _FakeClient(["```python\nbox = 1\n```", "```python\nbox = 2  # revised\n```"])
    g = LLMCadGenerator(fc)
    s1 = g.generate_script("a mug")
    assert s1 == "box = 1" and g.prev == "box = 1"
    # first call is a fresh "Create"; second is a "Revise" carrying the previous script + feedback
    assert "Create a parametric FreeCAD script" in fc.seen[0][1][1]["content"]
    s2 = g.generate_script("a mug", fix_feedback="handle too thin")
    assert s2 == "box = 2  # revised"
    revise_msg = fc.seen[1][1][1]["content"]
    assert "Revise this FreeCAD script" in revise_msg and "handle too thin" in revise_msg and "box = 1" in revise_msg


from scripts.agent.llm import client_for_role


def test_client_for_role_role_cli_wins(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_CODEGEN_MODEL", "envRole")
    monkeypatch.setenv("CHIMERA_LLM_MODEL", "envShared")
    c = client_for_role("codegen", cli_base="http://role/v1", cli_model="cliRole",
                        shared_cli_base="http://shared/v1", shared_cli_model="cliShared")
    assert c.base_url == "http://role/v1" and c.model == "cliRole"


def test_client_for_role_role_env_beats_shared_cli(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_CODEGEN_BASE_URL", "http://roleenv/v1")
    monkeypatch.setenv("CHIMERA_CODEGEN_MODEL", "roleEnvModel")
    c = client_for_role("codegen", shared_cli_base="http://shared/v1", shared_cli_model="cliShared")
    assert c.base_url == "http://roleenv/v1" and c.model == "roleEnvModel"   # specific-wins


def test_client_for_role_falls_back_to_shared(monkeypatch):
    _clear_env(monkeypatch)
    c = client_for_role("judge", shared_cli_base="http://shared/v1", shared_cli_model="shared-model")
    assert c.base_url == "http://shared/v1" and c.model == "shared-model"


def test_client_for_role_key_role_beats_generic(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_LLM_API_KEY", "ok")
    assert client_for_role("judge", shared_cli_base="http://x/v1", shared_cli_model="m").api_key == "ok"
    monkeypatch.setenv("CHIMERA_JUDGE_API_KEY", "jk")
    assert client_for_role("judge", shared_cli_base="http://x/v1", shared_cli_model="m").api_key == "jk"


def test_client_for_role_reasoning_effort_precedence(monkeypatch):
    # specific-wins, same as base_url/model: role CLI > role env > shared CLI > shared env
    _clear_env(monkeypatch)
    kw = dict(shared_cli_base="http://x/v1", shared_cli_model="m")
    assert client_for_role("judge", **kw).reasoning_effort is None
    monkeypatch.setenv("CHIMERA_LLM_REASONING_EFFORT", "medium")
    assert client_for_role("judge", **kw).reasoning_effort == "medium"
    assert client_for_role("judge", shared_cli_reasoning="low", **kw).reasoning_effort == "low"
    monkeypatch.setenv("CHIMERA_JUDGE_REASONING_EFFORT", "none")
    assert client_for_role("judge", shared_cli_reasoning="low", **kw).reasoning_effort == "none"
    assert client_for_role("judge", cli_reasoning="minimal", shared_cli_reasoning="low", **kw).reasoning_effort == "minimal"


def test_client_for_role_tagged_error_with_hint(monkeypatch):
    _clear_env(monkeypatch)
    with pytest.raises(LLMConfigError, match=r"\[codegen\].*interactively"):
        client_for_role("codegen")


from scripts.agent.llm import LLMExpander
from scripts.brandkit.manifest import default_manifest


def test_llmexpander_parses_json():
    fc = _FakeClient(['{"positive": "a heroic knight, dramatic light", "negative": "blurry, toy"}'])
    pos, neg = LLMExpander(fc, modality="image").expand("a knight", default_manifest(), ["FIX: add light"])
    assert pos == "a heroic knight, dramatic light" and neg == "blurry, toy"
    assert fc.seen[0][0] == "chat"   # text chat, not vision


def test_llmexpander_falls_back_when_llm_raises():
    class _Boom:
        def chat(self, *a, **k):
            raise RuntimeError("llm down")
    pos, neg = LLMExpander(_Boom()).expand("a knight", default_manifest(), None)
    assert isinstance(pos, str) and pos          # templated fallback, non-empty
    assert isinstance(neg, str)


def test_llmexpander_falls_back_on_bad_json():
    pos, neg = LLMExpander(_FakeClient(["not json at all"])).expand("a knight", default_manifest(), None)
    assert isinstance(pos, str) and pos


def test_vendor_keys_only_go_to_their_own_vendor(monkeypatch):
    # An OPENAI_API_KEY exported for other tools was sent to ANY base URL (OpenRouter, Gemini, a LAN box).
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    for url in ("https://openrouter.ai/api/v1", "http://localhost:11434/v1", "https://api.openai.com.evil.example/v1",
                "https://generativelanguage.googleapis.com/v1beta/openai"):
        assert LLMClient(base_url=url, model="m").api_key is None
        assert not client_for_role("judge", shared_cli_base=url, shared_cli_model="m").api_key
    assert LLMClient(base_url="https://api.openai.com/v1", model="m").api_key == "sk-openai"
    assert client_for_role("codegen", cli_base="https://API.anthropic.com/v1", cli_model="m").api_key == "sk-ant"
    monkeypatch.setenv("CHIMERA_LLM_API_KEY", "chimera")                  # an explicit Chimera key still wins
    assert LLMClient(base_url="https://openrouter.ai/api/v1", model="m").api_key == "chimera"



def test_the_api_key_is_not_copied_onto_a_redirect(monkeypatch):
    _clear_env(monkeypatch)
    cap = {}
    LLMClient(base_url="https://api.example/v1", api_key="k", model="m").chat(
        [{"role": "user", "content": "x"}], _opener=_opener(_msg("ok"), cap))
    assert cap["headers"]["authorization"] == "Bearer k" and "authorization" not in cap["redirected"]


def test_the_shared_key_only_goes_to_the_shared_endpoint(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CHIMERA_LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("CHIMERA_LLM_API_KEY", "sk-shared")
    monkeypatch.delenv("CHIMERA_CODEGEN_API_KEY", raising=False)
    assert not client_for_role("codegen", cli_base="https://openrouter.ai/api/v1", cli_model="m").api_key
    assert client_for_role("codegen", cli_base="https://api.openai.com/v1", cli_model="m2").api_key == "sk-shared"
    assert client_for_role("judge", cli_model="m").api_key == "sk-shared"
    assert not LLMClient(base_url="http://192.168.1.50:11434/v1", model="m").api_key


def test_vendor_keys_need_https(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert LLMClient(base_url="http://api.openai.com/v1", model="m").api_key is None


def test_a_key_over_plain_http_to_another_machine_warns(monkeypatch, capsys):
    _clear_env(monkeypatch)
    LLMClient(base_url="http://192.168.1.50:8000/v1", api_key="k", model="m")
    LLMClient(base_url="http://localhost:11434/v1", api_key="k", model="m")
    err = capsys.readouterr().err
    assert err.count("unencrypted") == 1 and "192.168.1.50" in err



def test_client_for_role_falls_back_to_the_callers_default_endpoint(monkeypatch):
    # the judge works with nothing configured (local Ollama's qwen3-vl:8b-instruct); config always wins
    _clear_env(monkeypatch)
    monkeypatch.delenv("CHIMERA_JUDGE_BASE_URL", raising=False)
    monkeypatch.delenv("CHIMERA_JUDGE_MODEL", raising=False)
    kw = dict(default_base="http://127.0.0.1:11434/v1", default_model="qwen3-vl:8b-instruct")
    c = client_for_role("judge", **kw)
    assert (c.base_url, c.model) == ("http://127.0.0.1:11434/v1", "qwen3-vl:8b-instruct")
    c = client_for_role("judge", shared_cli_base="https://api.openai.com/v1", shared_cli_model="gpt-4o", **kw)
    assert (c.base_url, c.model) == ("https://api.openai.com/v1", "gpt-4o")



# --- local models come in GPU tiers (2026-10: chosen on a 32 GB card; forks have less) -----------------------
from scripts.agent.llm import LOCAL_TIERS, local_tier, local_model_checks  # noqa: E402


@pytest.mark.parametrize("gb, tier", [(31.8, "large"), (28.0, "large"), (27.9, "medium"), (23.99, "medium"),
                                      (11.99, "medium"), (11.5, "medium"), (11.0, "small"), (10.9, "small"),
                                      (4.0, "small"), (None, "medium")])
def test_local_tier_follows_the_gpu_size(monkeypatch, gb, tier):
    monkeypatch.delenv("CHIMERA_LLM_TIER", raising=False)
    assert local_tier(gb) == tier


def test_local_tier_override_wins_and_rejects_typos(monkeypatch):
    monkeypatch.setenv("CHIMERA_LLM_TIER", "small")
    assert local_tier(31.8) == "small"
    assert local_tier(31.8, "medium") == "medium"            # the CLI flag beats the env
    assert local_tier(8.0, "auto") == "small"                # auto still means "pick from the GPU"
    monkeypatch.setenv("CHIMERA_LLM_TIER", "huge")
    with pytest.raises(LLMConfigError, match="unknown LLM tier 'huge'"):
        local_tier(31.8)


def test_every_tier_names_all_three_roles():
    for spec in LOCAL_TIERS.values():
        assert {"judge", "codegen", "rewriter"} <= set(spec)


def test_a_default_model_is_flagged_and_gets_the_default_effort_but_a_chosen_one_does_not(monkeypatch):
    _clear_env(monkeypatch)
    kw = dict(default_base="http://127.0.0.1:11434/v1", default_model="qwen3.8:27b", default_reasoning="none")
    c = client_for_role("judge", **kw)
    assert c.from_default and c.reasoning_effort == "none"
    c = client_for_role("judge", cli_model="qwen3-vl:8b-instruct", **kw)
    assert not c.from_default and c.reasoning_effort is None


def test_doctor_reports_the_tier_and_missing_pulls(monkeypatch):
    from scripts.brandkit import gpu as G
    monkeypatch.delenv("CHIMERA_LLM_TIER", raising=False)
    monkeypatch.setattr(G, "total_memory_gb", lambda client: 16.0)

    def opener(have):
        def open_(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            payload = {"version": "0.40.4"} if url.endswith("/api/version") else {"models": [{"name": n} for n in have]}
            return _Resp(payload)
        return open_
    lines = local_model_checks(object(), "http://127.0.0.1:11434", _opener=opener(["qwen3-vl:8b-instruct"]))
    assert lines[0][0] == "info" and "medium tier (16 GB GPU)" in lines[0][1]
    assert lines[1][0] == "warn" and "ollama pull qwen3.8:27b" in lines[1][1]
    lines = local_model_checks(object(), "http://127.0.0.1:11434",
                               _opener=opener(["qwen3-vl:8b-instruct", "qwen3.8:27b"]))
    assert lines[1][0] == "ok"
    monkeypatch.setenv("CHIMERA_LLM_TIER", "giant")
    assert local_model_checks(object())[0][0] == "warn"



def test_codegen_retrying_a_rejected_first_script_says_why():
    # with no previous script to revise, the retry prompt dropped the reason the first one was rejected
    from scripts.agent.llm import LLMCadGenerator
    seen = []

    class _C:
        def chat(self, messages, **kw):
            seen.append(messages[-1]["content"])
            return "```python\nbox = 1\n```"
    LLMCadGenerator(_C()).generate_script("a mug", fix_feedback="The previous script failed: disallowed 'socket'")
    assert seen[0].startswith("Create a parametric FreeCAD script for: a mug.") and "disallowed 'socket'" in seen[0]



# --- 2026-10 test review --------------------------------------------------------------------------------
from tests.test_gpu import _OLLAMA, _ollama, _server  # noqa: E402


def test_a_resident_model_never_asks_for_room():
    tags = {**_OLLAMA, ("GET", "/api/tags"): {"models": [{"name": "qwen3-vl:8b-instruct", "size": 6 * 2**30}]}}
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="qwen3-vl:8b-instruct")
    asked = []
    c.make_room = lambda need, floor=None: asked.append(need) or False     # a full card would refuse a NEW load
    c._ensure_room(_opener=_server(tags, []))                   # already loaded: nothing to make room for
    assert asked == []


def test_a_length_cutoff_without_a_reasoning_field_retries_with_thinking_off():
    bodies, seq = [], iter([{"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
                            {"choices": [{"message": {"content": "ok"}}]}])

    class _R:
        def __init__(self, p): self.b = json.dumps(p).encode()
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def open_(req, timeout=None):
        bodies.append(json.loads(req.data))
        return _R(next(seq))
    c = LLMClient(base_url="http://x/v1", model="m")
    assert c.chat([{"role": "user", "content": "x"}], _opener=open_) == "ok"
    assert bodies[1]["reasoning_effort"] == "none"


def test_resident_never_probes_a_remote_server():
    log = []
    assert LLMClient(base_url="https://api.example.com/v1", model="m").resident(_opener=_server(_OLLAMA, log)) is False
    assert log == []


def test_release_says_false_when_the_model_will_not_leave(monkeypatch):
    import scripts.agent.llm as L
    monkeypatch.setattr(L, "_UNLOAD_WAIT", 0.3)                  # release() takes no clock seam
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="qwen3-vl:8b-instruct")
    assert c.release(_opener=_ollama(_OLLAMA[("GET", "/api/ps")]["models"], [], forgets=False)) is False


def test_a_withheld_key_is_mentioned(monkeypatch, capsys):
    # a v0.5 setup (OpenRouter + OPENAI_API_KEY) got HTTP 401 on every iteration, after the render, silently
    from scripts.agent.llm import client_for_role
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    c = client_for_role("judge", cli_base="https://openrouter.ai/api/v1", cli_model="m")
    err = capsys.readouterr().err
    assert c.api_key == "" and "openrouter.ai" in err and "OPENAI_API_KEY isn't sent there" in err
    client_for_role("judge", cli_base="https://api.openai.com/v1", cli_model="m")      # the key goes: no note
    client_for_role("judge", cli_base="http://127.0.0.1:11434/v1", cli_model="m")     # local Ollama: no note
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("payload", [{"choices": [{"message": None}]}, {"choices": [{"message": "Overall: PASS"}]},
                                     {"choices": [{"message": {"content": 42}}]}])
def test_an_odd_response_shape_is_an_llm_error_not_a_crash(payload):
    # message: null and the like raised AttributeError, which got past the loops' LLMError handling (2026-10-25)
    with pytest.raises(LLMError, match="unexpected"):
        LLMClient(base_url="http://x/v1", model="m").chat([{"role": "user", "content": "x"}], _opener=_opener(payload))


def test_content_given_as_parts_is_joined():
    # some OpenAI-compatible servers return content as a list of parts; .strip() on it raised AttributeError
    parts = {"choices": [{"message": {"content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "Overall: "},
                                                  {"type": "text", "text": "PASS"}, "\nscore: 0.9"]}}]}
    assert LLMClient(base_url="http://x/v1", model="m").chat([{"role": "user", "content": "x"}],
                                                             _opener=_opener(parts)) == "Overall: PASS\nscore: 0.9"


@pytest.mark.parametrize("fence", ["```py", "```Python3", "```", "```python "])
def test_extract_code_drops_any_language_tag(fence):
    # a ```py fence left "py" as the script's first line
    assert _extract_code(f"Here:\n{fence}\nimport Part\nx = 1\n```") == "import Part\nx = 1"


def _judge_client(payloads, bodies):
    """An LLMClient whose requests go to a fake server answering `payloads` in turn (LLMJudge takes no opener)."""
    opener = _seq_opener(payloads, bodies)

    class _C(LLMClient):
        def chat(self, messages, **kw):
            return super().chat(messages, _opener=opener, **kw)
    return _C(base_url="http://x/v1", model="m")


def test_a_judge_reply_cut_off_at_max_tokens_is_an_error(tmp_path):
    # finish_reason 'length' with content was accepted, and the fragment's "should PASS" read as the verdict
    img = tmp_path / "i.png"; img.write_bytes(b"\x89PNG")
    cut = {"choices": [{"finish_reason": "length", "message": {
        "content": "1. MET - the hook is sturdy\nSo overall this should PASS. Let me double check"}}]}
    with pytest.raises(LLMError, match="cut off"):
        LLMJudge(_judge_client([cut], [])).judge(str(img), _Rub())


@pytest.mark.parametrize("cut", [
    {"content": "<think>The hook looks fine... So overall this should PASS. Let me"},       # inline, mid-thought
    {"content": "1. MET - sturdy", "reasoning": "let me think... " * 50}])                 # thinking took the budget
def test_a_judge_cut_off_while_thinking_retries_with_thinking_off(tmp_path, cut):
    img = tmp_path / "i.png"; img.write_bytes(b"\x89PNG")
    bodies = []
    c = _judge_client([{"choices": [{"finish_reason": "length", "message": cut}]},
                       _msg("1. NOT-MET - the arm is 2 mm thick\nOverall: FAIL\nscore: 0.3")], bodies)
    v = LLMJudge(c).judge(str(img), _Rub())
    assert not v.passed and v.score == 0.3 and bodies[1]["reasoning_effort"] == "none"


def test_code_gen_still_takes_a_reply_that_hit_max_tokens():
    # only the judge refuses a fragment; a cut-off script fails in FreeCAD and code-gen is told why
    cut = {"choices": [{"finish_reason": "length", "message": {"content": "```python\nbox = Part.makeBox(1, 1"}}]}
    assert LLMClient(base_url="http://x/v1", model="m").chat([{"role": "user", "content": "x"}],
                                                             _opener=_opener(cut)).startswith("```python")


def test_the_code_gen_prompt_states_what_the_cad_loop_checks():
    # live 2026-10-16: a "hex socket organizer" brief cut its sockets into the tray's empty cavity (nothing
    # removed, 0 of 4 iterations), then added rims floating in the cavity (7 pieces); with the one-solid rule
    # and the cut rule stated, the first iteration came out right
    from scripts.agent.llm import _CAD_SYSTEM
    assert "ONE connected solid" in _CAD_SYSTEM and "never into an existing cavity" in _CAD_SYSTEM
    assert "App.Vector" in _CAD_SYSTEM and "a Matrix has no `.rotate`" in _CAD_SYSTEM

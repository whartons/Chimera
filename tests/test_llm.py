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
            capture["headers"] = {k.lower(): v for k, v in req.headers.items()}
        return _Resp(payload)
    return open_


def _msg(content):
    return {"choices": [{"message": {"content": content}}]}


class _Rub:
    def as_prompt(self):
        return "RUBRIC-PROMPT"


def _clear_env(mp):
    for k in ("CHIMERA_LLM_BASE_URL", "CHIMERA_LLM_MODEL", "CHIMERA_LLM_API_KEY",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
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
    monkeypatch.setenv("OPENAI_API_KEY", "envkey")
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

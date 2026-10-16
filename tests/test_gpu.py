"""GPU hand-off between ComfyUI and a local Ollama (network-free: a fake opener plays both servers)."""
import json
import sys
import urllib.error

from scripts.brandkit import gpu
from scripts.agent.llm import LLMClient

_real_smi = gpu._nvidia_smi_gb   # captured at import, before the autouse fixture swaps it out


class _Resp:
    def __init__(self, payload):
        self._b = b"" if payload is None else json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _server(routes, log):
    """A fake urlopen. routes: {(METHOD, path): payload}; an unrouted call is 'connection refused'."""
    def open_(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        method = req.get_method() if hasattr(req, "get_method") else "GET"
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        body = json.loads(req.data) if getattr(req, "data", None) else None
        log.append((method, path, body))
        if (method, path) not in routes:
            raise urllib.error.URLError("connection refused")
        return _Resp(routes[(method, path)])
    return open_


_OLLAMA = {("GET", "/api/version"): {"version": "0.40.4"},
           ("GET", "/api/ps"): {"models": [{"name": "qwen3-vl:8b-instruct", "size_vram": 6_100_000_000},
                                            {"name": "qwen3.6-27b", "size_vram": 20_000_000_000}]},
           ("POST", "/api/generate"): {}}


def test_ollama_root_strips_v1_and_honours_ollama_host(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert gpu.ollama_root("http://localhost:11434/v1/") == "http://localhost:11434"
    assert gpu.ollama_root() == gpu.DEFAULT_OLLAMA
    # read the way Ollama's client reads it: the bind-all address means this machine, and no scheme means
    # port 11434 (OLLAMA_HOST=0.0.0.0 used to become http://0.0.0.0 on port 80, unreachable on Windows)
    for host, root in (("0.0.0.0:11500", "http://127.0.0.1:11500"), ("0.0.0.0", "http://127.0.0.1:11434"),
                       ("localhost", "http://localhost:11434"), ("http://localhost", "http://localhost"),
                       ("[::]:11434", "http://[::1]:11434"), ("https://ollama.example.com/", "https://ollama.example.com"),
                       ("http://box:11434/ollama/", "http://box:11434/ollama")):
        monkeypatch.setenv("OLLAMA_HOST", host)
        assert gpu.ollama_root() == root, host
    assert gpu.is_local("http://0.0.0.0:11434") and gpu.is_local("http://[::]:1")
    assert not gpu.is_local("http://192.168.1.5:11434")


def test_loaded_models_parses_ps_and_tolerates_a_stopped_ollama():
    log = []
    assert gpu.loaded_models("http://o", _opener=_server(_OLLAMA, log)) == [
        ("qwen3-vl:8b-instruct", 6_100_000_000), ("qwen3.6-27b", 20_000_000_000)]
    assert gpu.loaded_models("http://o", _opener=_server({}, [])) == []


def test_unload_all_unloads_each_resident_model_with_keep_alive_zero():
    log = []
    done = gpu.unload_all("http://o", _opener=_server(_OLLAMA, log))
    assert [n for n, _ in done] == ["qwen3-vl:8b-instruct", "qwen3.6-27b"]
    posts = [b for m, p, b in log if m == "POST"]
    assert posts == [{"model": "qwen3-vl:8b-instruct", "keep_alive": 0},
                     {"model": "qwen3.6-27b", "keep_alive": 0}]


def _ollama(models, log, forgets=True):
    """A fake Ollama whose /api/ps stops listing a model once it is unloaded (keep_alive 0), unless not `forgets`."""
    ps = [dict(m) for m in models]

    def open_(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        method = req.get_method() if hasattr(req, "get_method") else "GET"
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        body = json.loads(req.data) if getattr(req, "data", None) else None
        log.append((method, path, body))
        if path == "/api/version":
            return _Resp({"version": "0.40.4"})
        if path == "/api/ps":
            return _Resp({"models": list(ps)})
        if path == "/api/generate" and body and body.get("keep_alive") == 0:
            if forgets:
                ps[:] = [m for m in ps if m["name"] != body["model"]]
            return _Resp({})
        raise urllib.error.URLError("connection refused")
    return open_


def test_release_unloads_only_its_own_resident_model_on_ollama(monkeypatch):
    monkeypatch.delenv("CHIMERA_KEEP_LLM_LOADED", raising=False)
    log = []
    c = LLMClient(base_url="http://o/v1", model="qwen3-vl:8b-instruct")
    assert c.release(_opener=_ollama(_OLLAMA[("GET", "/api/ps")]["models"], log)) is True
    assert [b for m, p, b in log if m == "POST"] == [{"model": "qwen3-vl:8b-instruct", "keep_alive": 0}]
    assert log[-1][1] == "/api/ps"             # and it checked that the model really left


def test_unload_waits_for_ollama_to_let_go_and_says_when_it_does_not():
    # keep_alive 0 is answered before Ollama's runner frees the memory; a render must not start beside it
    now, sleep = _clock()
    models = [{"name": "judge:8b", "size_vram": 6 * 2**30}]
    assert gpu.unload("http://o", "judge:8b", wait=10, _opener=_ollama(models, []), _sleep=sleep, _clock=now)
    stuck = _ollama(models, [], forgets=False)
    assert gpu.unload("http://o", "judge:8b", wait=10, _opener=stuck, _sleep=sleep, _clock=now) is False
    assert gpu.unload("http://o", "judge:8b", _opener=stuck) is True        # no wait: Ollama accepted it


def test_release_never_loads_a_model_that_is_not_resident(monkeypatch):
    # Ollama's keep_alive-0 call can load a missing model first; only unload what /api/ps lists.
    monkeypatch.delenv("CHIMERA_KEEP_LLM_LOADED", raising=False)
    log = []
    c = LLMClient(base_url="http://o/v1", model="some-other-model")
    assert c.release(_opener=_server(_OLLAMA, log)) is False
    assert not [1 for m, p, b in log if m == "POST"]


def test_release_is_a_noop_for_non_ollama_endpoints_and_caches_detection(monkeypatch):
    monkeypatch.delenv("CHIMERA_KEEP_LLM_LOADED", raising=False)
    log = []
    c = LLMClient(base_url="https://api.example.com/v1", model="m")
    opener = _server({}, log)                     # no /api/version -> not Ollama
    assert c.release(_opener=opener) is False
    assert c.release(_opener=opener) is False
    assert [p for m, p, b in log] == ["/api/version"]   # probed once, then cached


def test_release_respects_the_keep_loaded_opt_out(monkeypatch):
    monkeypatch.setenv("CHIMERA_KEEP_LLM_LOADED", "1")
    log = []
    c = LLMClient(base_url="http://o/v1", model="qwen3-vl:8b-instruct")
    assert c.release(_opener=_server(_OLLAMA, log)) is False
    assert log == []


class _Comfy:
    def __init__(self, log, up=True):
        self.log, self.up = log, up

    def system_stats(self):
        if not self.up:
            raise urllib.error.URLError("refused")
        return {"devices": [{"vram_free": 4 * 2**30, "vram_total": 32 * 2**30}]}

    def free(self):
        if not self.up:
            raise urllib.error.URLError("refused")
        self.log.append(("COMFY", "/free", None))


def test_free_all_unloads_ollama_before_asking_comfyui_to_free():
    # 2026-10-14: ComfyUI 0.40 ran out of CUDA memory INSIDE its own /free while Ollama held ~26 GB,
    # and hung. Ollama must let go first.
    log = []
    report = gpu.free_all(_Comfy(log), "http://o", _opener=_server(_OLLAMA, log))
    order = [p for m, p, b in log if p in ("/api/generate", "/free")]
    assert order == ["/api/generate", "/api/generate", "/free"]
    assert report["comfy"] == "freed" and [n for n, _ in report["ollama"]] == ["qwen3-vl:8b-instruct", "qwen3.6-27b"]


def test_free_all_skips_apps_that_are_not_running():
    report = gpu.free_all(_Comfy([], up=False), "http://o", _opener=_server({}, []))
    assert report == {"comfy": "not running", "ollama": None}


def test_gpu_checks_warn_when_ollama_holds_vram():
    out = gpu.gpu_checks(_Comfy([]), "http://o", _opener=_server(_OLLAMA, []))
    assert any(lvl == "info" and "4.0 of 32.0 GB" in msg for lvl, msg in out)
    warn = [msg for lvl, msg in out if lvl == "warn"]
    assert warn and "24.3 GB" in warn[0] and "generate.py free" in warn[0]


def test_gpu_checks_only_list_a_small_resident_judge():
    judge_only = {**_OLLAMA, ("GET", "/api/ps"): {"models": [{"name": "qwen3-vl:8b-instruct",
                                                            "size_vram": 6_100_000_000}]}}
    out = gpu.gpu_checks(_Comfy([]), "http://o", _opener=_server(judge_only, []))
    assert not [1 for lvl, _ in out if lvl == "warn"]
    assert any(lvl == "info" and "qwen3-vl:8b-instruct" in msg for lvl, msg in out)


def test_gpu_checks_quiet_when_ollama_idle_or_stopped():
    idle = {**_OLLAMA, ("GET", "/api/ps"): {"models": []}}
    assert not [1 for lvl, _ in gpu.gpu_checks(_Comfy([]), "http://o", _opener=_server(idle, [])) if lvl == "warn"]
    stopped = gpu.gpu_checks(_Comfy([]), "http://o", _opener=_server({}, []))
    assert any("Ollama not running" in msg for _, msg in stopped)


def test_unload_says_false_instead_of_raising():
    # a refused request (Ollama stopped or restarting) is a normal state for a best-effort hand-off
    assert gpu.unload("http://o", "qwen3-vl:8b-instruct", _opener=_server({}, [])) is False


def test_print_free_reports_what_each_app_did(capsys):
    gpu.print_free({"ollama": [("qwen3.6-27b", 20 * 2**30)], "comfy": "freed"})
    out = capsys.readouterr().out
    assert "Ollama: unloaded qwen3.6-27b (20.0 GB of GPU memory)" in out
    assert "ComfyUI: asked to unload" in out
    gpu.print_free({"ollama": [], "comfy": "not running"})
    out = capsys.readouterr().out
    assert "Ollama: no models were loaded" in out and "ComfyUI: not running" in out
    gpu.print_free({"ollama": None, "comfy": "freed"})
    assert "Ollama: not running" in capsys.readouterr().out


def test_free_subcommand_runs_free_all_with_the_given_urls(monkeypatch, capsys):
    from scripts import generate
    seen = {}

    def fake_free_all(client, ollama_url=None):
        seen.update(client=client, ollama_url=ollama_url)
        return {"ollama": None, "comfy": "freed"}
    monkeypatch.setattr(gpu, "free_all", fake_free_all)
    monkeypatch.setattr(generate, "ComfyClient", lambda url: ("comfy", url))
    monkeypatch.setattr(sys, "argv", ["generate.py", "free", "--comfy-url", "http://c:1",
                                      "--ollama-url", "http://o:2/v1"])
    generate.main()
    assert seen == {"client": ("comfy", "http://c:1"), "ollama_url": "http://o:2/v1"}
    assert "ComfyUI: asked to unload" in capsys.readouterr().out



# --- the reverse hand-off: ComfyUI makes room before a local Ollama model loads (2026-10-15) --------
class _Card:
    """A ComfyUI that holds most of the card until /free, then gives it back after a poll or two."""
    def __init__(self, free_gb, after_free_gb, polls_to_free=1, up=True):
        self.free_gb, self.after, self.polls, self.up, self.freed = free_gb, after_free_gb, polls_to_free, up, 0

    def system_stats(self):
        if not self.up:
            raise urllib.error.URLError("refused")
        if self.freed and self.polls <= 0:
            self.free_gb = self.after
        elif self.freed:
            self.polls -= 1
        return {"devices": [{"type": "cuda", "vram_total": 32 * 2**30, "vram_free": (self.free_gb + 0.5) * 2**30,
                             "torch_vram_free": 0.5 * 2**30}]}

    def free(self):
        self.freed += 1


def _clock():
    t = [0.0]

    def now():
        return t[0]

    def sleep(s):
        t[0] += s
    return now, sleep


def test_make_room_frees_comfyui_only_when_the_model_does_not_fit():
    now, sleep = _clock()
    roomy = _Card(free_gb=20, after_free_gb=20)
    assert gpu.make_room(roomy, 9 * 2**30, _sleep=sleep, _clock=now) is True and roomy.freed == 0
    full = _Card(free_gb=0.1, after_free_gb=29, polls_to_free=2)     # the 2026-10-15 state
    assert gpu.make_room(full, 9 * 2**30, _sleep=sleep, _clock=now) is True and full.freed == 1


def test_make_room_counts_comfyuis_own_cache_as_taken():
    # vram_free includes memory ComfyUI's torch has reserved but not used: another process can't have it
    now, sleep = _clock()
    card = _Card(free_gb=0.1, after_free_gb=0.1)
    card.system_stats = lambda: {"devices": [{"type": "cuda", "vram_total": 32 * 2**30, "vram_free": 20 * 2**30,
                                              "torch_vram_free": 19.9 * 2**30}]}
    assert gpu.make_room(card, 9 * 2**30, wait=5, _sleep=sleep, _clock=now) is False and card.freed == 1


def test_make_room_gives_up_after_the_wait_and_tolerates_a_stopped_comfyui():
    now, sleep = _clock()
    stuck = _Card(free_gb=1, after_free_gb=1)
    assert gpu.make_room(stuck, 9 * 2**30, wait=5, _sleep=sleep, _clock=now) is False
    assert gpu.make_room(_Card(1, 1, up=False), 9 * 2**30, _sleep=sleep, _clock=now) is None


def test_vram_need_estimates_from_the_model_file_size():
    tags = {("GET", "/api/tags"): {"models": [{"name": "qwen3-vl:8b-instruct", "size": 6 * 2**30}]}}
    need = gpu.vram_need("http://o", "qwen3-vl:8b-instruct", _opener=_server(tags, []))
    assert 8 * 2**30 < need < 10 * 2**30
    assert gpu.vram_need("http://o", "missing:tag", _opener=_server(tags, [])) is None
    assert gpu.vram_need("http://o", "x", _opener=_server({}, [])) is None


_TAGS = {**_OLLAMA, ("GET", "/api/tags"): {"models": [{"name": "judge:8b", "size": 6 * 2**30}]}}


def test_a_local_ollama_model_asks_for_room_before_it_loads():
    asked = []
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c.make_room = lambda need, floor=None: asked.append(need)
    c._ensure_room(_opener=_server(_TAGS, []))
    assert len(asked) == 1 and asked[0] > 6 * 2**30


def test_no_room_is_asked_for_a_resident_model_a_remote_server_or_when_unset():
    asked = []
    resident = LLMClient(base_url="http://127.0.0.1:11434/v1", model="qwen3-vl:8b-instruct")
    resident.make_room = lambda need, floor=None: asked.append(need)
    resident._ensure_room(_opener=_server(_TAGS, []))
    remote = LLMClient(base_url="http://192.168.1.50:11434/v1", model="judge:8b")
    remote.make_room = lambda need, floor=None: asked.append(need)
    remote._ensure_room(_opener=_server(_TAGS, []))
    log = []
    LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")._ensure_room(_opener=_server(_TAGS, log))
    assert asked == [] and log == []


def test_chat_makes_room_before_the_request():
    order = []
    routes = {**_TAGS, ("POST", "/v1/chat/completions"): {"choices": [{"message": {"content": "ok"}}]}}
    opener = _server(routes, order)
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c.make_room = lambda need, floor=None: order.append(("ROOM", need, None))
    assert c.chat([{"role": "user", "content": "x"}], _opener=opener) == "ok"
    assert [e[0] for e in order].index("ROOM") < [e[1] for e in order].index("/v1/chat/completions")



def test_a_local_model_is_not_loaded_onto_a_card_that_never_frees():
    # loading anyway is what froze the PC: Ollama can't see ComfyUI's memory and overcommits the card
    import pytest
    from scripts.agent.llm import LLMError
    order = []
    routes = {**_TAGS, ("POST", "/v1/chat/completions"): {"choices": [{"message": {"content": "ok"}}]}}
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c.make_room = lambda need, floor=None: False
    with pytest.raises(LLMError, match="no room"):
        c.chat([{"role": "user", "content": "x"}], _opener=_server(routes, order))
    assert "/v1/chat/completions" not in [p for m, p, b in order]


def test_make_room_says_why_the_next_render_reloads(capsys):
    now, sleep = _clock()
    gpu.make_room(_Card(free_gb=0.1, after_free_gb=29), 9 * 2**30, _sleep=sleep, _clock=now)
    assert "asking ComfyUI to unload" in capsys.readouterr().err



def test_unload_others_keeps_the_runs_own_models():
    log = []
    done = gpu.unload_others("http://o", keep={"qwen3-vl:8b-instruct"},
                             _opener=_ollama(_OLLAMA[("GET", "/api/ps")]["models"], log))
    assert done == [("qwen3.6-27b", 20_000_000_000)]
    assert [b for m, p, b in log if m == "POST"] == [{"model": "qwen3.6-27b", "keep_alive": 0}]



_BIG_CTX_SHOW = {"model_info": {"general.architecture": "qwen35", "qwen35.block_count": 64,
                                "qwen35.attention.head_count": 24, "qwen35.attention.head_count_kv": 4,
                                "qwen35.attention.key_length": 256, "qwen35.attention.value_length": 256,
                                "qwen35.context_length": 262144},
                 "parameters": "num_ctx                        196608\nnum_predict                    4096"}
_JUDGE_SHOW = {"model_info": {"general.architecture": "qwen3vl", "qwen3vl.block_count": 36,
                              "qwen3vl.attention.head_count": 32, "qwen3vl.attention.head_count_kv": 8,
                              "qwen3vl.attention.key_length": 128, "qwen3vl.attention.value_length": 128,
                              "qwen3vl.context_length": 262144},
               "parameters": "temperature 1"}


def test_the_context_cache_is_sized_like_ollama_does(monkeypatch):
    # real metadata (2026-10-15): Ollama logged a 1296 MiB q4_0 cache for the judge at a 32k context. The big
    # fixture is a dense model (every layer caches) pinned to a 192k context by its Modelfile.
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "32768")
    assert abs(gpu._kv_cache_bytes(_JUDGE_SHOW) / 2**20 - 1296) < 1
    assert 13 < gpu._kv_cache_bytes(_BIG_CTX_SHOW) / 2**30 < 14     # num_ctx outranks OLLAMA_CONTEXT_LENGTH
    monkeypatch.delenv("OLLAMA_KV_CACHE_TYPE")                      # f16 cache: about 3.6x the bytes
    assert gpu._kv_cache_bytes(_JUDGE_SHOW) / 2**20 > 4000
    assert gpu._kv_cache_bytes({"model_info": {}}) is None


def test_vram_need_counts_the_context_cache(monkeypatch):
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    size = int(18.66 * 2**30)
    routes = {("GET", "/api/tags"): {"models": [{"name": "coder:27b-192k", "size": size}]},
              ("POST", "/api/show"): _BIG_CTX_SHOW}
    need = gpu.vram_need("http://o", "coder:27b-192k", _opener=_server(routes, []))
    assert need > 32 * 2**30          # more than the card: make_room must empty ComfyUI, not just trim it
    no_show = {("GET", "/api/tags"): routes[("GET", "/api/tags")]}
    assert gpu.vram_need("http://o", "coder:27b-192k", _opener=_server(no_show, [])) == int(size * 1.2) + 2 * 2**30


def test_a_model_bigger_than_the_card_empties_comfyui_and_then_loads():
    now, sleep = _clock()

    class _Full(_Card):
        def system_stats(self):
            s = super().system_stats()
            s["devices"][0]["vram_total"] = 31.8 * 2**30
            return s
    card = _Full(free_gb=27.5, after_free_gb=30.0)                  # ComfyUI holds 4 GB
    assert gpu.make_room(card, 35 * 2**30, _sleep=sleep, _clock=now) is True and card.freed == 1



def test_total_memory_prefers_comfyui_then_nvidia_smi(monkeypatch):
    class _C:
        def __init__(self, kind="cuda", base=None):
            self.kind = kind
            if base:
                self.base = base

        def system_stats(self):
            return {"devices": [{"type": self.kind, "vram_total": 31.8 * 2**30}]}
    assert gpu.total_memory_gb(_C()) == 31.8
    assert gpu.total_memory_gb(_C(base="http://127.0.0.1:8000")) == 31.8
    monkeypatch.setattr(gpu, "_nvidia_smi_gb", lambda: 12.0)
    assert gpu.total_memory_gb(object()) == 12.0              # no ComfyUI answer -> nvidia-smi
    assert gpu.total_memory_gb() == 12.0
    # an Apple / CPU ComfyUI reports system RAM, and a remote one another machine's card
    assert gpu.total_memory_gb(_C(kind="mps")) == 12.0
    assert gpu.total_memory_gb(_C(base="http://192.168.1.9:8188")) == 12.0


def test_nvidia_smi_reading_is_parsed_and_time_limited(monkeypatch):
    import subprocess as _sp
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return _sp.CompletedProcess(argv, 0, stdout="32607\n8192\n", stderr="")
    monkeypatch.setattr(gpu.subprocess, "run", fake_run)
    monkeypatch.setattr(gpu, "_nvidia_smi_gb", _real_smi)   # the real reader, on the faked subprocess
    assert round(gpu._nvidia_smi_gb(), 1) == 31.8 and seen["timeout"] == 5

    monkeypatch.setattr(gpu.subprocess, "run",           # a driver error prints words, not numbers
                        lambda argv, **kw: _sp.CompletedProcess(argv, 9, stdout="No devices were found\n", stderr=""))
    assert gpu._nvidia_smi_gb() is None

    def boom(argv, **kw):
        raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr(gpu.subprocess, "run", boom)
    assert gpu._nvidia_smi_gb() is None


def test_pulled_models_lists_tags_and_tolerates_a_stopped_ollama():
    tags = {("GET", "/api/tags"): {"models": [{"name": "qwen3.8:27b"}, {"model": "qwen3-vl:8b-instruct"}]}}
    assert gpu.pulled_models("http://o", _opener=_server(tags, [])) == ["qwen3.8:27b", "qwen3-vl:8b-instruct"]
    assert gpu.pulled_models("http://o", _opener=_server({}, [])) == []



# --- the 2026-10 review of the hand-off: fail safe, real CUDA cards only, Ollama's own name and host rules ---
def test_make_room_only_reads_a_local_cuda_card():
    # mps and the CPU report system RAM, DirectML a 1 GB placeholder: every local judge refused on a Mac
    now, sleep = _clock()
    for dev in ({"type": "mps", "vram_total": 64 * 2**30, "vram_free": 0, "torch_vram_free": 0},
                {"type": "privateuseone", "vram_total": 2**30, "vram_free": 2**30, "torch_vram_free": 0}):
        card = _Card(0, 0)
        card.system_stats = lambda dev=dev: {"devices": [dev]}
        assert gpu.make_room(card, 9 * 2**30, _sleep=sleep, _clock=now) is None and card.freed == 0
    remote = _Card(0.1, 29)
    remote.base = "http://192.168.1.9:8188"        # another machine's card: freeing it frees nothing here
    assert gpu.make_room(remote, 9 * 2**30, _sleep=sleep, _clock=now) is None and remote.freed == 0


def test_make_room_refuses_when_comfyui_stops_answering_after_showing_a_full_card():
    # any later error used to read as "ComfyUI isn't running", and the model loaded onto the full card
    now, sleep = _clock()

    class _Wedged(_Card):
        def free(self):
            raise urllib.error.URLError("timed out")
    assert gpu.make_room(_Wedged(0.1, 29), 9 * 2**30, _sleep=sleep, _clock=now) is False

    class _Gone(_Card):
        def system_stats(self):
            if self.freed:
                raise TimeoutError("timed out")
            return super().system_stats()
    assert gpu.make_room(_Gone(0.1, 29), 9 * 2**30, wait=5, _sleep=sleep, _clock=now) is False


def test_a_model_bigger_than_the_card_always_empties_comfyui_first():
    # capped to the card, the need "fit" beside 1.5 GB of ComfyUI models that Ollama can't see
    now, sleep = _clock()

    class _Small(_Card):
        def system_stats(self):
            s = super().system_stats()
            s["devices"][0]["vram_total"] = 16 * 2**30
            return s
    card = _Small(free_gb=14.5, after_free_gb=15.5)
    assert gpu.make_room(card, 22 * 2**30, _sleep=sleep, _clock=now) is True and card.freed == 1


def test_nvidia_smi_errors_are_not_read_as_a_size(monkeypatch):
    # a driver mismatch prints 'NVML library version: 560.35', which read as a 0.5 GiB card (the small tier)
    import subprocess as _sp
    monkeypatch.setattr(gpu, "_nvidia_smi_gb", _real_smi)
    monkeypatch.setattr(gpu.subprocess, "run", lambda argv, **kw: _sp.CompletedProcess(
        argv, 18, stdout="Failed to initialize NVML\nNVML library version: 560.35\n", stderr=""))
    assert gpu._nvidia_smi_gb() is None
    monkeypatch.setattr(gpu.subprocess, "run", lambda argv, **kw: _sp.CompletedProcess(argv, 0, stdout="560.35\n",
                                                                                       stderr=""))
    assert gpu._nvidia_smi_gb() is None             # sizes are whole MiB


def test_a_bad_port_in_ollama_host_falls_back_to_ollamas_default(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "localhost:port")
    assert gpu.ollama_root() == "http://localhost:11434"


def test_model_names_compare_the_way_ollama_resolves_them():
    # a model written another way ('Judge:8B') skipped the room check
    assert gpu.same_model("Judge:8B", "judge:8b") and gpu.same_model("registry.ollama.ai/library/judge:8b", "judge:8b")
    assert gpu.same_model("judge", "judge:latest") and not gpu.same_model("judge:8b", "judge:4b")
    tags = {("GET", "/api/tags"): {"models": [{"name": "registry.ollama.ai/library/judge:8b", "size": 6 * 2**30}]}}
    assert gpu.vram_need("http://o", "Judge:8B", _opener=_server(tags, [])) is not None


def test_the_context_cache_counts_parallel_slots_and_needs_flash_attention_to_shrink(monkeypatch):
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    one = gpu._kv_cache_bytes(_JUDGE_SHOW)
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "2")
    assert gpu._kv_cache_bytes(_JUDGE_SHOW) == 2 * one
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "lots")
    assert gpu._kv_cache_bytes(_JUDGE_SHOW) == one
    monkeypatch.setenv("OLLAMA_FLASH_ATTENTION", "0")              # a quantized cache needs flash attention
    assert gpu._kv_cache_bytes(_JUDGE_SHOW) > 3 * one


def test_room_counts_the_models_ollama_already_holds_on_windows(monkeypatch):
    # on Windows ComfyUI can't see Ollama's resident models either: a second model needs room beside them
    monkeypatch.setattr(sys, "platform", "win32")
    asked = []
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c.make_room = lambda need, floor=None: asked.append(need)
    c._ensure_room(_opener=_server(_TAGS, []))
    assert asked[0] > 6_100_000_000 + 20_000_000_000 + 6 * 2**30   # the two resident models + its own need


def test_elsewhere_the_room_is_just_the_models_own_need(monkeypatch):
    # Linux and macOS drivers report device-wide free memory, resident models included: adding them again made a
    # second local model wait 30 s and fall back (2026-10 review)
    monkeypatch.setattr(sys, "platform", "linux")
    asked = []
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c.make_room = lambda need, floor=None: asked.append(need)
    c._ensure_room(_opener=_server(_TAGS, []))
    assert 0 < asked[0] < 6_100_000_000 + 20_000_000_000


def test_no_room_check_when_ollama_is_down_or_lacks_the_model():
    asked = []
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c.make_room = lambda need, floor=None: asked.append(need)
    c._ensure_room(_opener=_server({}, []))                       # Ollama not answering
    c._ensure_room(_opener=_server(_OLLAMA, []))                  # not pulled: the request fails without loading
    assert asked == []


def test_a_failed_probe_of_a_local_ollama_is_retried():
    # one failed probe (Ollama restarting) used to switch the GPU checks off for the whole run
    models = _OLLAMA[("GET", "/api/ps")]["models"]
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="qwen3-vl:8b-instruct")
    assert c.release(_opener=_server({}, [])) is False
    assert c.release(_opener=_ollama(models, [])) is True
    assert c.resident(_opener=_ollama([], [])) is False and c.resident(_opener=_ollama(models, [])) is True
    assert LLMClient(base_url="https://api.example.com/v1", model="m").resident() is False



# --- 2026-10 test review: behaviours a deleted line didn't fail ----------------------------------------
def test_a_failed_nvidia_smi_is_not_a_size(monkeypatch):
    # return code 18 with a version line: the old test passed only because "560.35" fails int()
    monkeypatch.setattr(gpu, "_nvidia_smi_gb", _real_smi)
    monkeypatch.setattr(gpu.subprocess, "run", lambda argv, **kw: gpu.subprocess.CompletedProcess(
        argv, 18, stdout="Failed to initialize NVML: Driver/library version mismatch\nNVML library version: 560\n",
        stderr=""))
    assert gpu._nvidia_smi_gb() is None


def test_the_cache_follows_ollama_context_length_capped_at_the_trained_context(monkeypatch):
    # an undersized estimate is the PC-freeze path
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "32768")
    base = gpu._kv_cache_bytes(_JUDGE_SHOW)                      # a 32k context
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "131072")
    assert gpu._kv_cache_bytes(_JUDGE_SHOW) == 4 * base
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH")
    huge = {**_JUDGE_SHOW, "parameters": "num_ctx 1048576"}      # more than the model's 262144
    assert gpu._kv_cache_bytes(huge) == 8 * base


def test_an_unpinned_context_is_sized_at_the_models_full_length(monkeypatch):
    # Ollama 0.40 sizes an unpinned context to the VRAM it sees: the 8B judge took 32k beside a loaded ComfyUI
    # but its full 256k on a free card (16.3 GB resident against a 9.1 GB estimate, 2026-10-16)
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "32768")
    base = gpu._kv_cache_bytes(_JUDGE_SHOW)
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH")
    assert gpu._kv_cache_bytes(_JUDGE_SHOW) == 8 * base
    no_length = {"model_info": {k: v for k, v in _JUDGE_SHOW["model_info"].items() if "context_length" not in k}}
    assert gpu._kv_cache_bytes(no_length) == base               # a model that doesn't say: the 32k fallback


def test_a_hybrid_model_caches_only_its_attention_layers(monkeypatch):
    # Qwen 3.8 27B (qwen35): 65 blocks, but only every 4th is full attention; counting all 65 over-reserved
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    show = {"model_info": {"general.architecture": "qwen35", "qwen35.block_count": 65,
                           "qwen35.attention.head_count": 24, "qwen35.attention.head_count_kv": 4,
                           "qwen35.attention.key_length": 256, "qwen35.attention.value_length": 256,
                           "qwen35.full_attention_interval": 4, "qwen35.context_length": 262144}}
    assert gpu._kv_cache_bytes(show) == int(17 * 4 * 512 * 262144 * 0.5625)


def test_a_missing_value_length_takes_the_key_length(monkeypatch):
    # qwen3-vl 4B lists key_length 128 but no value_length; embedding / heads (80) under-sized its cache
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    info = {k: v for k, v in _JUDGE_SHOW["model_info"].items() if "value_length" not in k}
    assert gpu._kv_cache_bytes({"model_info": info}) == gpu._kv_cache_bytes(_JUDGE_SHOW)


def test_unload_others_waits_for_each_model_to_leave():
    now, sleep = _clock()
    stuck = _ollama([{"name": "other:latest", "size_vram": 18 * 2**30}], [], forgets=False)
    assert gpu.unload_others("http://o", keep=(), _opener=stuck, _sleep=sleep, _clock=now) == []


def test_keep_loaded_accepts_the_documented_spellings(monkeypatch):
    for v in ("true", "YES", " on "):
        monkeypatch.setenv("CHIMERA_KEEP_LLM_LOADED", v)
        assert gpu.keep_llms_loaded(), v


def test_any_loopback_address_is_local():
    assert gpu.is_local("http://127.0.0.2:11434")


def test_model_names_match_however_ollama_spells_them():
    assert gpu.same_model("library/qwen3-vl:8b-instruct", "qwen3-vl:8b-instruct")
    assert gpu.same_model("registry.ollama.ai/library/QWEN3.8:27b", "qwen3.8:27b")
    assert gpu.same_model("mymodel", "mymodel:latest")


# --- a full-context estimate bigger than the card must not refuse every load (2026-10 final review) ------------
class _Desk(_Card):
    """A 24 GB card where the desktop and a browser hold 3.5 GB that ComfyUI's unload can't give back; ComfyUI
    itself holds 12 GB until /free."""
    def system_stats(self):
        s = super().system_stats()
        d = s["devices"][0]
        d["vram_total"] = 24 * 2**30
        d["torch_vram_total"] = (0.4 if self.freed else 12) * 2**30
        return s


def test_once_comfyui_has_emptied_the_floor_is_enough():
    # Ollama's default f16 cache at the 8B judge's full 256k context is ~44 GB: capped at the card, the old check
    # waited for 21 GB free that a desktop holding 3.5 GB never gave, and refused every judge load
    now, sleep = _clock()
    card = _Desk(free_gb=8.5, after_free_gb=20.1)
    assert gpu.make_room(card, 44 * 2**30, floor_bytes=12 * 2**30, _sleep=sleep, _clock=now) is True and card.freed == 1
    assert gpu.make_room(_Desk(8.5, 20.1), 44 * 2**30, wait=5, _sleep=sleep, _clock=now) is False      # no floor given

    class _Holding(_Desk):   # ComfyUI never lets go (a job running): the floor alone isn't enough
        def system_stats(self):
            s = super().system_stats()
            s["devices"][0]["torch_vram_total"] = 12 * 2**30
            return s
    assert gpu.make_room(_Holding(8.5, 20.1), 44 * 2**30, floor_bytes=12 * 2**30, wait=5, _sleep=sleep,
                         _clock=now) is False
    assert gpu.make_room(_Desk(8.5, 10.0), 44 * 2**30, floor_bytes=12 * 2**30, wait=5, _sleep=sleep,
                         _clock=now) is False                                                     # the floor doesn't fit


def test_the_floor_is_the_32k_figure_unless_a_context_is_pinned(monkeypatch):
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    tags = {("GET", "/api/tags"): {"models": [{"name": "judge:8b", "size": 6 * 2**30}]}}
    floor, full = gpu.vram_need_range("http://o", "judge:8b",
                                      _opener=_server({**tags, ("POST", "/api/show"): _JUDGE_SHOW}, []))
    assert full - floor == 7 * gpu._kv_cache_bytes(_JUDGE_SHOW, unpinned_ctx=32768)   # 256k is 8x the 32k cache
    pinned = {**_JUDGE_SHOW, "parameters": "num_ctx 65536"}
    floor, full = gpu.vram_need_range("http://o", "judge:8b", _opener=_server({**tags, ("POST", "/api/show"): pinned}, []))
    assert floor == full
    assert gpu.vram_need_range("http://o", "judge:8b", _opener=_server(tags, [])) == (int(6 * 2**30 * 1.2) + 2 * 2**30,) * 2


def test_the_room_check_gets_both_figures_and_names_the_floor_when_it_refuses(monkeypatch):
    import pytest
    from scripts.agent.llm import LLMError
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    routes = {**_TAGS, ("POST", "/api/show"): _JUDGE_SHOW}
    asked = []
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c.make_room = lambda full, floor=None: asked.append((full, floor))
    c._ensure_room(_opener=_server(routes, []))
    [(full, floor)] = asked
    assert floor < full and c._planned is not None
    c.make_room = lambda full, floor=None: False
    with pytest.raises(LLMError, match="at a 32k context"):
        c._ensure_room(_opener=_server(routes, []))


def test_a_load_bigger_than_planned_is_reported(capsys):
    # the estimate reads Ollama's settings from Chimera's environment: a server started with others can load more
    c = LLMClient(base_url="http://127.0.0.1:11434/v1", model="judge:8b")
    c._ollama, c._planned = True, 5 * 2**30
    big = {("GET", "/api/ps"): {"models": [{"name": "judge:8b", "size_vram": 9 * 2**30}]}}
    c._check_planned(_opener=_server(big, []))
    assert "more than the 5.0 GB the GPU check planned for" in capsys.readouterr().err and c._planned is None
    c._planned = 10 * 2**30
    c._check_planned(_opener=_server(big, []))
    assert capsys.readouterr().err == ""


def test_a_model_without_head_count_kv_caches_one_head_per_attention_head(monkeypatch):
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    info = {k: v for k, v in _JUDGE_SHOW["model_info"].items() if "head_count_kv" not in k}
    assert gpu._kv_cache_bytes({"model_info": info}) == 4 * gpu._kv_cache_bytes(_JUDGE_SHOW)   # 32 heads, 8 KV heads


def test_per_layer_head_counts_without_kv_heads_or_key_length(monkeypatch):
    # list-valued head_count, no head_count_kv (one KV head per head) and no key_length (embedding / heads)
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    show = {"model_info": {"general.architecture": "x", "x.block_count": 2, "x.attention.head_count": [8, 8],
                           "x.embedding_length": 1024, "x.context_length": 4096}}
    assert gpu._kv_cache_bytes(show) == int(16 * 256 * 4096 * 0.5625)

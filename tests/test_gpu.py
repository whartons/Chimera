"""GPU hand-off between ComfyUI and a local Ollama (network-free: a fake opener plays both servers)."""
import json
import sys
import urllib.error

from scripts.brandkit import gpu
from scripts.agent.llm import LLMClient


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
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11500")
    assert gpu.ollama_root() == "http://0.0.0.0:11500"


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


def test_release_unloads_only_its_own_resident_model_on_ollama(monkeypatch):
    monkeypatch.delenv("CHIMERA_KEEP_LLM_LOADED", raising=False)
    log = []
    c = LLMClient(base_url="http://o/v1", model="qwen3-vl:8b-instruct")
    assert c.release(_opener=_server(_OLLAMA, log)) is True
    assert [b for m, p, b in log if m == "POST"] == [{"model": "qwen3-vl:8b-instruct", "keep_alive": 0}]


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

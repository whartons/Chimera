import sys, pathlib
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _no_live_ollama(monkeypatch):
    """Tests never reach a real Ollama. The loops' default judge is a local Ollama client, so a run's
    end-of-run release() probed 127.0.0.1:11434 for real: about 2 s per test on Windows with Ollama down,
    and with it up a test could unload a real model. A gpu call on the real opener now fails fast as
    "not running" (a refused connection: a timeout reads as an Ollama that may hold memory); tests that pass a
    fake opener are unaffected."""
    import errno
    from scripts.brandkit import gpu
    real = gpu._call

    def guarded(url, body=None, timeout=5, _opener=urllib.request.urlopen):
        if _opener is urllib.request.urlopen:
            raise urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "tests don't reach a live Ollama"))
        return real(url, body, timeout, _opener)
    monkeypatch.setattr(gpu, "_call", guarded)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test opens a network connection. The opener guards here miss a test that patches urlopen globally
    (a GPU check then reached the real Ollama) and a path without a seam (one test sent a GET to the
    developer's ComfyUI, 2026-10 review), so connections are refused the way a CI box with nothing running
    refuses them."""
    import errno
    import socket

    def refuse(self, address, *a, **k):
        raise ConnectionRefusedError(errno.ECONNREFUSED, f"tests don't open network connections ({address!r})")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, address: errno.ECONNREFUSED)


@pytest.fixture(autouse=True)
def _no_real_git(monkeypatch):
    """Sidecars record the pipeline's commit (provenance.git_provenance), and the tests that render end to
    end ran git twice each: 0.6-4 s apiece under load. git commands get a fixed clean answer; a test that
    fakes subprocess.run itself replaces this, and other commands run for real."""
    import subprocess
    real = subprocess.run

    def run(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, stdout="abc1234\n" if "rev-parse" in cmd else "", stderr="")
        return real(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", run)


@pytest.fixture(autouse=True)
def _no_ollama_env(monkeypatch):
    """Ollama's own settings in the developer's shell (OLLAMA_NUM_PARALLEL, OLLAMA_KV_CACHE_TYPE, ...) change
    how the GPU checks size a model, and Chimera's change which models a loop picks and which keys it sends
    (VS Code loads .env into test runs); tests set what they need."""
    for k in ("OLLAMA_HOST", "OLLAMA_NUM_PARALLEL", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_FLASH_ATTENTION",
              "OLLAMA_CONTEXT_LENGTH", "CHIMERA_KEEP_LLM_LOADED", "CHIMERA_LLM_TIER",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              *(f"CHIMERA_{role}_{k}" for role in ("LLM", "JUDGE", "CODEGEN", "REWRITER")
                for k in ("BASE_URL", "MODEL", "API_KEY", "REASONING_EFFORT"))):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _no_endpoint_preflight(request, monkeypatch):
    """auto_generate checks before rendering that a local Ollama serves each role, and in tests no Ollama
    answers (above), so a test running main() would stop there. Tests of the check itself are marked
    `preflight`."""
    if request.node.get_closest_marker("preflight"):
        return
    from scripts.agent import auto_generate
    monkeypatch.setattr(auto_generate, "_endpoint_problems", lambda roles: [])


@pytest.fixture(autouse=True)
def _no_real_nvidia_smi(monkeypatch):
    """The local-model tier reads the GPU size; tests never run the real nvidia-smi (CI has none, and a dev
    box's card would make results machine-dependent). Tests that need a size patch it in."""
    from scripts.brandkit import gpu
    monkeypatch.setattr(gpu, "_nvidia_smi_gb", lambda: None)


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    """Tests never reach a real LLM server either. With nothing configured the loops now default to a local
    Ollama model, so a test that runs a loop for real would generate CAD code against the developer's Ollama
    (one hung the suite for minutes). A request on the real opener fails fast; fake openers are unaffected."""
    from scripts.agent import llm
    real = llm.LLMClient._chat_once

    def guarded(self, messages, max_tokens, temperature, reasoning_effort, _opener, **kw):
        if _opener is urllib.request.urlopen:
            raise llm.LLMError("tests don't reach a live LLM")
        return real(self, messages, max_tokens, temperature, reasoning_effort, _opener, **kw)
    monkeypatch.setattr(llm.LLMClient, "_chat_once", guarded)

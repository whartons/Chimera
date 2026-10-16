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
    "not running"; tests that pass a fake opener are unaffected."""
    from scripts.brandkit import gpu
    real = gpu._call

    def guarded(url, body=None, timeout=5, _opener=urllib.request.urlopen):
        if _opener is urllib.request.urlopen:
            raise urllib.error.URLError("tests don't reach a live Ollama")
        return real(url, body, timeout, _opener)
    monkeypatch.setattr(gpu, "_call", guarded)


@pytest.fixture(autouse=True)
def _no_ollama_env(monkeypatch):
    """Ollama's own settings in the developer's shell (OLLAMA_NUM_PARALLEL, OLLAMA_KV_CACHE_TYPE, ...) change
    how the GPU checks size a model, and Chimera's change which models a loop picks; tests set what they need."""
    for k in ("OLLAMA_HOST", "OLLAMA_NUM_PARALLEL", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_FLASH_ATTENTION",
              "OLLAMA_CONTEXT_LENGTH", "CHIMERA_KEEP_LLM_LOADED", "CHIMERA_LLM_TIER"):
        monkeypatch.delenv(k, raising=False)


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

    def guarded(self, messages, max_tokens, temperature, reasoning_effort, _opener):
        if _opener is urllib.request.urlopen:
            raise llm.LLMError("tests don't reach a live LLM")
        return real(self, messages, max_tokens, temperature, reasoning_effort, _opener)
    monkeypatch.setattr(llm.LLMClient, "_chat_once", guarded)

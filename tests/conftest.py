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

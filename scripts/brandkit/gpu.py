"""GPU-memory hand-off between the apps Chimera drives on one card: ComfyUI (renders) and a local
Ollama (the agent's judge / codegen / rewriter models).

Ollama keeps a model resident for ~5 minutes after its last request. On a 32 GB card a 27B model
(plus its context cache) then starves ComfyUI, and ComfyUI 0.40 can even run out of CUDA memory
inside its own /free and hang (the 2026-10-14 smoke). These helpers unload Ollama models on demand
and report who holds the GPU. Stdlib only; every call is best-effort and never raises, because a
stopped Ollama (or ComfyUI) is a normal state."""
from __future__ import annotations
import json
import os
import urllib.request

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
_GB = 2 ** 30
_WARN_GB = 8.0   # a resident 8B judge (~6 GB) is fine next to ComfyUI; a 27B model is not


def ollama_root(base_url=None):
    """The Ollama server root: an OpenAI-compatible base URL with its "/v1" stripped, else
    $OLLAMA_HOST (Ollama's own setting), else the default local address."""
    if base_url:
        url = base_url.rstrip("/")
        return url[:-3] if url.endswith("/v1") else url
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if host:
        return (host if host.startswith(("http://", "https://")) else "http://" + host).rstrip("/")
    return DEFAULT_OLLAMA


def _call(url, body=None, timeout=5, _opener=urllib.request.urlopen):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with _opener(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def is_ollama(root, _opener=urllib.request.urlopen):
    """True when `root` answers Ollama's /api/version (so hosted APIs are never sent Ollama calls)."""
    try:
        return "version" in _call(root + "/api/version", timeout=3, _opener=_opener)
    except Exception:
        return False


def loaded_models(root, _opener=urllib.request.urlopen):
    """[(name, vram_bytes)] currently resident in Ollama; [] when it isn't running."""
    try:
        models = _call(root + "/api/ps", _opener=_opener).get("models") or []
    except Exception:
        return []
    out = []
    for m in models:
        name = m.get("name") or m.get("model")
        if name:
            out.append((name, int(m.get("size_vram") or 0)))
    return out


def unload(root, model, _opener=urllib.request.urlopen):
    """Drop `model` from memory now (keep_alive 0). Call only for a RESIDENT model: Ollama may load a
    missing one first. Returns True on success."""
    try:
        _call(root + "/api/generate", {"model": model, "keep_alive": 0}, timeout=60, _opener=_opener)
        return True
    except Exception:
        return False


def unload_all(root, _opener=urllib.request.urlopen):
    """Unload every resident Ollama model; return the [(name, vram_bytes)] that were unloaded."""
    return [(name, vram) for name, vram in loaded_models(root, _opener=_opener)
            if unload(root, name, _opener=_opener)]


def free_all(comfy_client, ollama_url=None, _opener=urllib.request.urlopen):
    """`chimera free`: unload Ollama's models FIRST, then ask ComfyUI to unload its models and free
    VRAM. (Reversed, ComfyUI 0.40 can run out of CUDA memory inside /free while Ollama holds the GPU.)
    Returns {"ollama": [(name, vram_bytes)] or None if not running, "comfy": "freed"|"not running"}."""
    root = ollama_root(ollama_url)
    report = {"ollama": unload_all(root, _opener=_opener) if is_ollama(root, _opener=_opener) else None}
    try:
        comfy_client.free()
        report["comfy"] = "freed"
    except Exception:
        report["comfy"] = "not running"
    return report


def print_free(report):
    """Render a free_all report (ASCII only, Windows-console safe)."""
    if report["ollama"] is None:
        print("Ollama: not running - nothing to unload")
    elif not report["ollama"]:
        print("Ollama: no models were loaded")
    else:
        for name, vram in report["ollama"]:
            print(f"Ollama: unloaded {name} ({vram / _GB:.1f} GB of GPU memory)")
    if report["comfy"] == "freed":
        print("ComfyUI: asked to unload its models and free VRAM (it does so as soon as it is idle)")
    else:
        print("ComfyUI: not running - nothing to free")


def gpu_checks(comfy_client, ollama_url=None, _opener=urllib.request.urlopen):
    """Doctor lines about GPU memory: what ComfyUI sees free, and what Ollama holds. Never fails."""
    out = []
    try:
        dev = (comfy_client.system_stats().get("devices") or [{}])[0]
        free_gb, total_gb = dev.get("vram_free", 0) / _GB, dev.get("vram_total", 0) / _GB
        if total_gb:
            out.append(("info", f"GPU memory: {free_gb:.1f} of {total_gb:.1f} GB free (as seen by ComfyUI)"))
    except Exception:
        pass   # ComfyUI reachability is reported by the main doctor checks
    root = ollama_root(ollama_url)
    if not is_ollama(root, _opener=_opener):
        out.append(("info", "Ollama not running (needed only for --backend api / --pipeline cad)"))
        return out
    resident = loaded_models(root, _opener=_opener)
    held = sum(v for _, v in resident) / _GB
    if not resident:
        out.append(("ok", "Ollama holds no GPU memory"))
    elif held >= _WARN_GB:
        names = ", ".join(n for n, _ in resident)
        out.append(("warn", f"Ollama is holding {held:.1f} GB of GPU memory ({names}) - heavy ComfyUI jobs "
                            "(FLUX.2, video) may fail; run `python scripts/generate.py free` first"))
    else:
        out.append(("info", "Ollama has resident: " + ", ".join(f"{n} ({v / _GB:.1f} GB)" for n, v in resident)))
    return out

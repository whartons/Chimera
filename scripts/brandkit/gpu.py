"""GPU-memory hand-off between the apps Chimera drives on one card: ComfyUI (renders) and a local
Ollama (the agent's judge / codegen / rewriter models).

Ollama keeps a model resident for ~5 minutes after its last request. On a 32 GB card a 27B model
(plus its context cache) then starves ComfyUI, and ComfyUI 0.40 can even run out of CUDA memory
inside its own /free and hang (the 2026-10-14 smoke). The reverse happens too: ComfyUI keeps its
models resident after a render, so an Ollama model loading next has no room (make_room). These
helpers unload either side on demand and report who holds the GPU. Stdlib only; every call is
best-effort and never raises, because a stopped Ollama (or ComfyUI) is a normal state."""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.parse
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


def keep_llms_loaded():
    """CHIMERA_KEEP_LLM_LOADED=1: leave Ollama's models resident (only on a card with room for both apps)."""
    return os.environ.get("CHIMERA_KEEP_LLM_LOADED", "").strip().lower() in ("1", "true", "yes", "on")


def is_local(url):
    """True for a loopback URL: an app sharing this machine's GPU."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    return host == "localhost" or host.startswith("127.") or host == "::1"


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


def vram_need(root, model, _opener=urllib.request.urlopen):
    """Bytes of GPU memory `model` needs to load in Ollama, estimated from its file size plus room for the
    context cache and the CUDA context; None when Ollama doesn't list it."""
    try:
        models = _call(root + "/api/tags", _opener=_opener).get("models") or []
    except Exception:
        return None
    for m in models:
        if (m.get("name") or m.get("model")) == model and m.get("size"):
            return int(int(m["size"]) * 1.2) + 2 * _GB
    return None


def make_room(comfy_client, need_bytes, *, wait=30.0, poll=1.0, _sleep=time.sleep, _clock=time.monotonic):
    """Before a local Ollama model loads: when ComfyUI reports less than `need_bytes` of the card free
    (outside its own cache), ask it to unload its models (POST /free) and wait, up to `wait` seconds, for
    the memory to come back. True once there is room, False if it never came, None if ComfyUI isn't
    reachable.

    Ollama can't do this itself on Windows: it doesn't see ComfyUI's allocations (it reported 30 GB free
    while ComfyUI held 15), so it loads onto a full card, and the driver pages GPU memory to system RAM.
    On 2026-10-15 ComfyUI held all but 0.1 GB after a day of renders; the judge loaded anyway, crawled
    past its 180 s timeout, nvidia-smi hung, and the PC froze. ComfyUI does see its own holdings."""
    def free_outside_comfy():
        dev = (comfy_client.system_stats().get("devices") or [{}])[0]
        return (dev.get("vram_free") or 0) - (dev.get("torch_vram_free") or 0)
    try:
        free = free_outside_comfy()
        if free >= need_bytes:
            return True
        print(f"[gpu] ComfyUI leaves {free / _GB:.1f} GB of the card free and the local LLM needs about "
              f"{need_bytes / _GB:.1f} GB: asking ComfyUI to unload its models first", file=sys.stderr)
        comfy_client.free()
        deadline = _clock() + wait
        while _clock() < deadline:
            _sleep(poll)
            if free_outside_comfy() >= need_bytes:
                return True
        return False
    except Exception:
        return None


def unload_others(root, keep=(), _opener=urllib.request.urlopen):
    """Unload the resident Ollama models not named in `keep` (names as Ollama lists them); return the
    [(name, vram_bytes)] unloaded. The loops call it before their first render: ComfyUI can't see an Ollama
    model's memory, so rendering beside, say, an 18 GB model left loaded by another tool overcommits the card."""
    return [(name, vram) for name, vram in loaded_models(root, _opener=_opener)
            if name not in keep and unload(root, name, _opener=_opener)]


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

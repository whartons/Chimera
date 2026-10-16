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
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

DEFAULT_OLLAMA = "http://127.0.0.1:11434"
_GB = 2 ** 30
_WARN_GB = 8.0   # a resident 8B judge (~6 GB) is fine next to ComfyUI; a 27B model is not


_ANY_ADDRESS = {"0.0.0.0": "127.0.0.1", "::": "::1"}   # a server's bind-all address, as a client reaches it


def _host_url(value):
    """$OLLAMA_HOST as a URL to connect to, read the way Ollama's own client reads it: without a scheme it is
    http on port 11434 unless one is given, and the bind-all address 0.0.0.0 (or ::) means this machine.
    OLLAMA_HOST=0.0.0.0 used to become http://0.0.0.0 (port 80), and Windows can't connect to 0.0.0.0."""
    scheme, sep, rest = value.strip().partition("://")
    if not sep:
        scheme, rest = "http", value.strip()
    hostport, _, path = rest.partition("/")
    u = urllib.parse.urlsplit(f"//{hostport}")
    host = u.hostname or "127.0.0.1"
    try:
        port = u.port
    except ValueError:
        port = None
    if port is None and not sep:
        port = 11434
    host = _ANY_ADDRESS.get(host, host)
    netloc = (f"[{host}]" if ":" in host else host) + (f":{port}" if port is not None else "")
    return f"{scheme}://{netloc}" + (f"/{path}".rstrip("/") if path else "")


def ollama_root(base_url=None):
    """The Ollama server root: an OpenAI-compatible base URL with its "/v1" stripped, else
    $OLLAMA_HOST (Ollama's own setting), else the default local address."""
    if base_url:
        url = base_url.rstrip("/")
        return url[:-3] if url.endswith("/v1") else url
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if host:
        return _host_url(host)
    return DEFAULT_OLLAMA


def model_key(name):
    """An Ollama model name compared the way Ollama resolves it: case-insensitive, without the default
    registry prefix, ':latest' when untagged. A name written another way used to skip the GPU checks."""
    n = str(name or "").strip().lower()
    for prefix in ("registry.ollama.ai/library/", "registry.ollama.ai/", "library/"):
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    return n if ":" in n.rsplit("/", 1)[-1] else n + ":latest"


def same_model(a, b):
    return model_key(a) == model_key(b)


def _nvidia_smi_gb():
    """The largest NVIDIA GPU's total memory in GiB from nvidia-smi, or None. Time-limited: nvidia-smi hangs
    when the driver is wedged (seen 2026-10-15). A failed run prints errors, not sizes ('NVML library
    version: 560.35' once read as a 0.5 GiB GPU)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    mib = []
    for v in (out.stdout or "").split():
        try:
            mib.append(int(v))
        except ValueError:
            pass
    return max(mib) / 1024 if mib else None


def _cuda_device(comfy_client):
    """ComfyUI's first device when it is a CUDA GPU on this machine, else None. Other devices report memory
    differently (Apple's mps and the CPU give system RAM, DirectML a 1 GB placeholder), and a remote
    ComfyUI's card isn't this machine's."""
    base = getattr(comfy_client, "base", None)
    if comfy_client is None or (base is not None and not is_local(base)):
        return None
    dev = (comfy_client.system_stats().get("devices") or [{}])[0]
    return dev if dev.get("type") == "cuda" and dev.get("vram_total") else None


def total_memory_gb(comfy_client=None):
    """The GPU's total memory in GiB: what a local ComfyUI reports for its CUDA card when it answers, else
    nvidia-smi, else None."""
    try:
        dev = _cuda_device(comfy_client)
        if dev:
            return dev["vram_total"] / _GB
    except Exception:
        pass
    return _nvidia_smi_gb()


def pulled_models(root, _opener=urllib.request.urlopen):
    """The model names Ollama has on disk (from /api/tags); [] when it isn't running."""
    try:
        models = _call(root + "/api/tags", _opener=_opener).get("models") or []
    except Exception:
        return []
    return [m.get("name") or m.get("model") for m in models if m.get("name") or m.get("model")]


def keep_llms_loaded():
    """CHIMERA_KEEP_LLM_LOADED=1: leave Ollama's models resident (only on a card with room for both apps)."""
    return os.environ.get("CHIMERA_KEEP_LLM_LOADED", "").strip().lower() in ("1", "true", "yes", "on")


def is_local(url):
    """True for a loopback URL (or the bind-all 0.0.0.0 / ::, which reach this machine): an app sharing this
    machine's GPU. This machine's LAN address or host name doesn't count, so give local apps as
    localhost / 127.0.0.1 for the GPU hand-off to apply."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    return host in ("localhost", "::1", *_ANY_ADDRESS) or host.startswith("127.")


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


def is_resident(root, model, _opener=urllib.request.urlopen):
    """True when Ollama at `root` lists `model` as loaded."""
    return any(same_model(n, model) for n, _ in loaded_models(root, _opener=_opener))


def unload(root, model, *, wait=0.0, poll=0.25, _opener=urllib.request.urlopen, _sleep=time.sleep,
           _clock=time.monotonic):
    """Drop `model` from memory now (keep_alive 0). Call only for a RESIDENT model: Ollama may load a
    missing one first. With `wait`, also wait up to that many seconds for /api/ps to stop listing it, since
    Ollama answers before its runner has let go of the memory. Returns True on success."""
    try:
        _call(root + "/api/generate", {"model": model, "keep_alive": 0}, timeout=60, _opener=_opener)
    except Exception:
        return False
    deadline = _clock() + wait
    while wait > 0 and is_resident(root, model, _opener=_opener):
        if _clock() >= deadline:
            return False
        _sleep(poll)
    return True


_KV_BYTES = {"q4_0": 0.5625, "q8_0": 1.0625}   # per cached element (block scale included); else f16 = 2
_DEFAULT_CTX = 32768                             # Ollama 0.40's context on a 24 GB+ card when num_ctx is unset
_OFF = ("0", "false", "no", "off")


def _kv_cache_bytes(show):
    """The context cache Ollama allocates for a model, from /api/show: layers x KV heads x (key + value
    dims) x context x bytes per element, for each of OLLAMA_NUM_PARALLEL slots. A quantized cache type
    needs flash attention, so with OLLAMA_FLASH_ATTENTION off the cache stays f16. None when the
    architecture keys are missing."""
    info = show.get("model_info") or {}
    arch = info.get("general.architecture")
    layers, kv_heads = info.get(f"{arch}.block_count"), info.get(f"{arch}.attention.head_count_kv")
    if not layers or not kv_heads:
        return None
    heads = info.get(f"{arch}.attention.head_count") or 1
    dims = (info.get(f"{arch}.attention.key_length") or info.get(f"{arch}.embedding_length", 0) // heads) + \
        (info.get(f"{arch}.attention.value_length") or info.get(f"{arch}.embedding_length", 0) // heads)
    per_token = (sum(kv_heads) if isinstance(kv_heads, list) else kv_heads * layers) * dims
    m = re.search(r"\bnum_ctx\s+(\d+)", show.get("parameters") or "")
    ctx = int(m.group(1)) if m else (int(os.environ.get("OLLAMA_CONTEXT_LENGTH") or 0) or _DEFAULT_CTX)
    ctx = min(ctx, info.get(f"{arch}.context_length") or ctx)
    fa_off = os.environ.get("OLLAMA_FLASH_ATTENTION", "").strip().lower() in _OFF
    per_elem = 2.0 if fa_off else _KV_BYTES.get(os.environ.get("OLLAMA_KV_CACHE_TYPE", "").strip().lower(), 2.0)
    try:
        slots = max(1, int(os.environ.get("OLLAMA_NUM_PARALLEL") or 1))
    except ValueError:
        slots = 1
    return int(per_token * ctx * per_elem * slots)


def vram_need(root, model, _opener=urllib.request.urlopen):
    """Bytes of GPU memory `model` takes once loaded in Ollama: its weights plus its context cache (from
    /api/show; a 192k-token context added 13.5 GB to an 18.7 GB model) plus compute buffers. Falls back to
    the file size x 1.2 + 2 GB when the cache can't be sized; None when Ollama doesn't list the model."""
    try:
        models = _call(root + "/api/tags", _opener=_opener).get("models") or []
    except Exception:
        return None
    size = next((int(m["size"]) for m in models
                 if same_model(m.get("name") or m.get("model"), model) and m.get("size")), None)
    if size is None:
        return None
    try:
        kv = _kv_cache_bytes(_call(root + "/api/show", {"model": model}, timeout=20, _opener=_opener))
    except Exception:
        kv = None
    if kv is None:
        return int(size * 1.2) + 2 * _GB
    return int(size * 1.1) + kv + int(1.5 * _GB)


def make_room(comfy_client, need_bytes, *, wait=30.0, poll=1.0, _sleep=time.sleep, _clock=time.monotonic):
    """Before a local Ollama model loads: when ComfyUI reports less than `need_bytes` of the card free
    (outside its own cache), ask it to unload its models (POST /free) and wait, up to `wait` seconds, for
    the memory to come back. True once there is room; False if it never came, or if ComfyUI stopped
    answering after showing a full card (the check must not fail open); None when it can't tell: ComfyUI
    isn't reachable, or its device isn't a CUDA GPU (see _cuda_device).

    Ollama can't do this itself on Windows: it doesn't see ComfyUI's allocations (it reported 30 GB free
    while ComfyUI held 15), so it loads onto a full card, and the driver pages GPU memory to system RAM.
    On 2026-10-15 ComfyUI held all but 0.1 GB after a day of renders; the judge loaded anyway, crawled
    past its 180 s timeout, nvidia-smi hung, and the PC froze. ComfyUI does see its own holdings.

    A model bigger than the card needs ComfyUI emptied rather than trimmed, so it always asks ComfyUI to
    unload, and the target is capped at the card minus 3 GB for the desktop. Past that, Ollama's own fitting
    puts the overflow on the CPU, which is safe once nothing it can't see holds the card."""
    def card():
        dev = _cuda_device(comfy_client)
        if dev is None:
            return None
        return (dev.get("vram_free") or 0) - (dev.get("torch_vram_free") or 0), dev["vram_total"]
    try:
        seen = card()
    except Exception:
        return None
    if seen is None:
        return None
    free, total = seen
    capped = need_bytes > total - 3 * _GB
    need_bytes = min(need_bytes, total - 3 * _GB)
    if free >= need_bytes and not capped:
        return True
    why = ("is bigger than the card's free memory" if capped else f"needs about {need_bytes / _GB:.1f} GB")
    print(f"[gpu] ComfyUI leaves {free / _GB:.1f} GB of the card free and the local LLM {why}: asking ComfyUI "
          "to unload its models first", file=sys.stderr)
    try:
        comfy_client.free()
    except Exception:
        return False
    deadline = _clock() + wait
    while _clock() < deadline:
        _sleep(poll)
        try:
            if card()[0] >= need_bytes:
                return True
        except Exception:
            pass   # a busy or wedged ComfyUI: keep waiting until the deadline, then refuse
    return False


def unload_others(root, keep=(), *, wait=10.0, _opener=urllib.request.urlopen, _sleep=time.sleep,
                  _clock=time.monotonic):
    """Unload the resident Ollama models not named in `keep` (names as Ollama lists them), each waited out
    like LLMClient.release; return the [(name, vram_bytes)] unloaded. The loops call it before their first
    render: ComfyUI can't see an Ollama model's memory, so rendering beside, say, an 18 GB model left loaded by
    another tool overcommits the card."""
    return [(name, vram) for name, vram in loaded_models(root, _opener=_opener)
            if not any(same_model(name, k) for k in keep)
            and unload(root, name, wait=wait, _opener=_opener, _sleep=_sleep, _clock=_clock)]


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
        out.append(("info", "Ollama not running (needed only for auto_generate.py's local models)"))
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

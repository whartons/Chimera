"""GPU-memory hand-off between the apps Chimera drives on one card: ComfyUI (renders) and a local
Ollama (the agent's judge / codegen / rewriter models).

Ollama keeps a model resident for ~5 minutes after its last request. On a 32 GB card a 27B model
(plus its context cache) then starves ComfyUI, and ComfyUI 0.40 can even run out of CUDA memory
inside its own /free and hang (the 2026-10-14 smoke). The reverse happens too: ComfyUI keeps its
models resident after a render, so an Ollama model loading next has no room (make_room). These
helpers unload either side on demand and report who holds the GPU. Stdlib only; every call is
best-effort and never raises, because a stopped Ollama (or ComfyUI) is a normal state. The exception is a
`strict` probe, which raises ProbeError when an app is there but doesn't answer: the guards can't read that
as "nothing loaded"."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
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


class ProbeError(RuntimeError):
    """A strict probe's app is there but didn't answer (a timeout, a reset, a garbled reply), so what it holds is
    unknown. A stopped app (connection refused) is never one."""


def _refused(exc):
    """True when a request failed because nothing listens at the address: the app isn't running, a normal state.
    Every failure used to read that way, so a busy or wedged app (a timeout, a reset) counted as holding nothing,
    and a model loaded or a render started beside memory nobody had checked (2026-10-25 review)."""
    return isinstance(getattr(exc, "reason", exc), ConnectionRefusedError)


def _probe_failed(url, exc, strict):
    """For a failed GET of `url`: raise ProbeError when `strict` and the app may be there (not refused, and not a
    404, which says the server has no such API: it isn't Ollama). Otherwise the caller reads it as absent."""
    absent = _refused(exc) or (isinstance(exc, urllib.error.HTTPError) and exc.code == 404)
    if strict and not absent:
        raise ProbeError(f"{url} didn't answer ({getattr(exc, 'reason', exc)})") from exc


def is_ollama(root, _opener=urllib.request.urlopen, *, strict=False):
    """True when `root` answers Ollama's /api/version (so hosted APIs are never sent Ollama calls). False when
    nothing listens there or another server answers; `strict` raises ProbeError when the connection times out or
    drops instead (an Ollama too busy or wedged to say, or a reply that never came)."""
    try:
        return "version" in _call(root + "/api/version", timeout=3, _opener=_opener)
    except Exception as e:
        # an answer of any kind (an HTTP error, a page that isn't JSON) is a server that isn't Ollama
        if isinstance(e, OSError) and not isinstance(e, urllib.error.HTTPError):
            _probe_failed(root + "/api/version", e, strict)
        return False


def loaded_models(root, _opener=urllib.request.urlopen, *, strict=False):
    """[(name, vram_bytes)] currently resident in Ollama; [] when it isn't running. `strict` raises ProbeError when
    Ollama doesn't answer (a timeout, a reset, a garbled reply): then nobody knows what it holds."""
    try:
        models = _call(root + "/api/ps", _opener=_opener).get("models") or []
    except Exception as e:
        _probe_failed(root + "/api/ps", e, strict)
        return []
    out = []
    for m in models:
        name = m.get("name") or m.get("model")
        if name:
            out.append((name, int(m.get("size_vram") or 0)))
    return out


def is_resident(root, model, _opener=urllib.request.urlopen, *, strict=False):
    """True when Ollama at `root` lists `model` as loaded (see loaded_models for `strict`)."""
    return any(same_model(n, model) for n, _ in loaded_models(root, _opener=_opener, strict=strict))


def unload(root, model, *, wait=0.0, poll=0.25, _opener=urllib.request.urlopen, _sleep=time.sleep,
           _clock=time.monotonic):
    """Drop `model` from memory now (keep_alive 0). Call only for a RESIDENT model: Ollama may load a
    missing one first. With `wait`, also wait up to that many seconds for /api/ps to stop listing it, since
    Ollama answers before its runner has let go of the memory. Returns True on success."""
    try:
        _call(root + "/api/generate", {"model": model, "keep_alive": 0}, timeout=60, _opener=_opener)
    except Exception:
        return False

    def listed():
        try:
            return is_resident(root, model, _opener=_opener, strict=True)
        except ProbeError:
            return True   # a timed-out /api/ps read as "gone", and the render started beside it (2026-10-25)
    deadline = _clock() + wait
    while wait > 0 and listed():
        if _clock() >= deadline:
            return False
        _sleep(poll)
    return True


_KV_BYTES = {"q4_0": 0.5625, "q8_0": 1.0625}   # per cached element (block scale included); else f16 = 2
_DEFAULT_CTX = 32768                             # the context assumed when a model doesn't report its own
_OFF = ("0", "false", "no", "off")


def _kv_cache_bytes(show, unpinned_ctx=None):
    """The context cache Ollama allocates for a model, from /api/show: attention layers x KV heads x (key +
    value dims) x context x bytes per element, for each of OLLAMA_NUM_PARALLEL slots. A quantized cache type
    needs flash attention, so with OLLAMA_FLASH_ATTENTION off the cache stays f16. None when the
    architecture keys are missing.

    The context is num_ctx when the model pins it, else OLLAMA_CONTEXT_LENGTH, else `unpinned_ctx` if given,
    else the model's trained length: with neither set, Ollama 0.40 sizes the context to the VRAM it sees, up to
    that length. It gave the 8B judge 32k beside a loaded ComfyUI (2026-10-15) but 256k on a free card
    (2026-10-16: 16.3 GB resident, not 6.6), so a 32k estimate let a medium- or small-tier judge load 7-8 GB more
    than the room asked of ComfyUI."""
    info = show.get("model_info") or {}
    arch = info.get("general.architecture")
    heads = info.get(f"{arch}.attention.head_count")
    # no head_count_kv means one KV head per attention head (llama.cpp's default)
    layers, kv_heads = info.get(f"{arch}.block_count"), info.get(f"{arch}.attention.head_count_kv") or heads
    if not layers or not kv_heads:
        return None
    if isinstance(heads, list):
        heads = max(heads) or 1
    heads = heads or 1
    key = info.get(f"{arch}.attention.key_length") or info.get(f"{arch}.embedding_length", 0) // heads
    dims = key + (info.get(f"{arch}.attention.value_length") or key)
    interval = info.get(f"{arch}.full_attention_interval")
    if isinstance(kv_heads, list):
        per_token = sum(kv_heads) * dims
    elif isinstance(interval, int) and interval > 1:   # hybrid (Qwen 3.5+): only every Nth layer keeps a cache
        per_token = -(-layers // interval) * kv_heads * dims
    else:
        per_token = kv_heads * layers * dims
    trained = info.get(f"{arch}.context_length")
    m = re.search(r"\bnum_ctx\s+(\d+)", show.get("parameters") or "")
    ctx = int(m.group(1)) if m else (int(os.environ.get("OLLAMA_CONTEXT_LENGTH") or 0) or unpinned_ctx or trained
                                     or _DEFAULT_CTX)
    ctx = min(ctx, trained or ctx)
    fa_off = os.environ.get("OLLAMA_FLASH_ATTENTION", "").strip().lower() in _OFF
    per_elem = 2.0 if fa_off else _KV_BYTES.get(os.environ.get("OLLAMA_KV_CACHE_TYPE", "").strip().lower(), 2.0)
    try:
        slots = max(1, int(os.environ.get("OLLAMA_NUM_PARALLEL") or 1))
    except ValueError:
        slots = 1
    return int(per_token * ctx * per_elem * slots)


def vram_need_range(root, model, _opener=urllib.request.urlopen, *, strict=False):
    """(floor, full) bytes of GPU memory `model` takes once loaded in Ollama: its weights plus its context cache
    (from /api/show) plus compute buffers, `full` at the context Ollama may give it (see _kv_cache_bytes) and
    `floor` at a 32k context when nothing pins one (the same figure when something does). Falls back to the
    file size x 1.2 + 2 GB for both when the cache can't be sized; None when Ollama doesn't list the model, or
    isn't running. `strict` raises ProbeError when /api/tags doesn't answer (see loaded_models)."""
    try:
        models = _call(root + "/api/tags", _opener=_opener).get("models") or []
    except Exception as e:
        _probe_failed(root + "/api/tags", e, strict)
        return None
    size = next((int(m["size"]) for m in models
                 if same_model(m.get("name") or m.get("model"), model) and m.get("size")), None)
    if size is None:
        return None
    try:
        show = _call(root + "/api/show", {"model": model}, timeout=20, _opener=_opener)
        full, floor = _kv_cache_bytes(show), _kv_cache_bytes(show, unpinned_ctx=_DEFAULT_CTX)
    except Exception:
        full = floor = None
    if full is None or floor is None:
        return (int(size * 1.2) + 2 * _GB,) * 2
    base = int(size * 1.1) + int(1.5 * _GB)
    return base + floor, base + full


def vram_need(root, model, _opener=urllib.request.urlopen):
    """Bytes of GPU memory `model` takes once loaded in Ollama at the largest context it may get (the `full`
    figure of vram_need_range); None when Ollama doesn't list the model."""
    r = vram_need_range(root, model, _opener=_opener)
    return r[1] if r else None


def make_room(comfy_client, need_bytes, *, floor_bytes=None, wait=30.0, poll=1.0, _sleep=time.sleep,
              _clock=time.monotonic):
    """Before a local Ollama model loads: when ComfyUI reports less than `need_bytes` of the card free
    (outside its own cache), ask it to unload its models (POST /free) and wait, up to `wait` seconds, for
    the memory to come back. True once there is room; False if it never came, or if ComfyUI is there but
    doesn't answer (the check must not fail open); None when there's nothing to check: ComfyUI isn't running
    (connection refused), or its device isn't a CUDA GPU (see _cuda_device).

    Ollama can't do this itself on Windows: it doesn't see ComfyUI's allocations (it reported 30 GB free
    while ComfyUI held 15), so it loads onto a full card, and the driver pages GPU memory to system RAM.
    On 2026-10-15 ComfyUI held all but 0.1 GB after a day of renders; the judge loaded anyway, crawled
    past its 180 s timeout, nvidia-smi hung, and the PC froze. ComfyUI does see its own holdings.

    A model bigger than the card needs ComfyUI emptied rather than trimmed, so it always asks ComfyUI to
    unload, the target is capped at the card minus 3 GB for the desktop, and the room counts only once ComfyUI
    holds under 1 GB. Past that, Ollama's own fitting puts the overflow on the CPU, which is safe once nothing it
    can't see holds the card.

    `floor_bytes` is the model's need at the smallest context Ollama would give it (32k when nothing pins one,
    vram_need_range): Ollama sizes an unpinned context to the room it sees, so once ComfyUI has emptied (it
    holds under 1 GB) and the floor fits, the load is safe without the full-context figure. Without that, a
    full-context estimate near the card's size (an f16 cache at 256k) refused every judge load whenever the
    desktop, a browser or OBS held more than 3 GB (2026-10 review)."""
    def card():
        dev = _cuda_device(comfy_client)
        if dev is None:
            return None
        free = (dev.get("vram_free") or 0) - (dev.get("torch_vram_free") or 0)
        return free, dev["vram_total"], dev.get("torch_vram_total")   # the last: ComfyUI's own reservation
    try:
        seen = card()
    except Exception as e:
        if _refused(e):
            return None
        # a wedged ComfyUI (a timeout, a reset) used to read as "not running", and the model loaded beside it
        print(f"[gpu] ComfyUI didn't answer ({getattr(e, 'reason', e)}), so it may still hold the card: not loading "
              "the local LLM beside it", file=sys.stderr)
        return False
    if seen is None:
        return None
    free, total, _ = seen
    capped = need_bytes > total - 3 * _GB
    target = min(need_bytes, total - 3 * _GB)
    if free >= target and not capped:
        return True
    why = ("is bigger than the card's free memory" if capped else f"needs about {target / _GB:.1f} GB")
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
            free, _, held = card()
            emptied = held is not None and held < _GB
            # capped, free memory alone isn't room: 29.5 of 32 GB free "fit" a 35 GB model while ComfyUI still held
            # 2 GB that Ollama can't see (2026-10-25 review)
            if (free >= target and (emptied or not capped)) or (floor_bytes is not None and emptied
                                                                 and free >= floor_bytes):
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


def unload_all(root, _opener=urllib.request.urlopen, *, wait=10.0):
    """Unload every resident Ollama model, each waited out like LLMClient.release; return the [(name, vram_bytes)]
    that were unloaded. Not waiting, free_all asked ComfyUI to free while Ollama's runner still held the memory
    (2026-10-25 review)."""
    return [(name, vram) for name, vram in loaded_models(root, _opener=_opener)
            if unload(root, name, wait=wait, _opener=_opener)]


def free_all(comfy_client, ollama_url=None, _opener=urllib.request.urlopen):
    """`chimera free`: unload Ollama's models FIRST, waiting until it has let them go, then ask ComfyUI to unload
    its models and free VRAM. (Reversed, ComfyUI 0.40 can run out of CUDA memory inside /free while Ollama holds
    the GPU.)
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

"""Refuse a local ComfyUI job that won't fit in this machine's memory, before it starts.

ComfyUI stages a job's model weights in system memory (pinned copies, patched copies, the text encoder, the VAEs)
and loads them onto the GPU from there. On 2026-11-11 an LTX-2.3 job (~30 GB of model files) on a 62 GB Windows box,
beside an IDE, a browser and another session's test suites, drove the commit charge to 122 GB of a 107.6 GB limit:
Windows paged until the desktop froze, twice (explorer crashed; then ComfyUI had to be stopped from a phone).
ComfyUI's own knobs didn't prevent it (dynamic VRAM ignores --reserve-vram; --cache-ram only evicts caches).

So before queueing, Chimera adds up the model files the job's graph loads (found through ComfyUI's own model
folders, /internal/folder_paths) and compares the memory that needs with what this machine has left: Windows' commit
room (commit limit minus commit charge: past it Windows grows the page file and pages), or MemAvailable on Linux,
minus a share kept for the desktop. A job that doesn't fit first gets ComfyUI to unload models left over from earlier
jobs; if it still doesn't fit, it is refused with the numbers. Only a ComfyUI on this machine is checked, and
CHIMERA_SKIP_MEMORY_CHECK=1 turns the check off. Stdlib only."""
from __future__ import annotations
import ctypes
import os
import sys
import time
from pathlib import Path

from .gpu import is_local

GB = 2**30
MODEL_EXTS = (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin", ".gguf")
# What a job takes: its model files (staged, pinned and patched copies of the weights) plus working buffers.
# Calibrated on the 2026-11-11 LTX-2.3 job: its graph's model files total 36.1 GB and the commit charge grew ~35 GB.
OVERHEAD, BASE = 1.0, 2 * GB
DESKTOP_SHARE, DESKTOP_FLOOR = 0.10, 4 * GB   # memory kept free for Windows and the apps beside ComfyUI
SKIP_ENV = "CHIMERA_SKIP_MEMORY_CHECK"


class MemoryGuardError(RuntimeError):
    """The job's models don't fit in the memory this machine has left."""


def graph_model_files(wf):
    """The model files a graph loads: every string input naming a file with a model extension (unet_name,
    ckpt_name, clip_name, vae_name, lora_name, ... as the loaders call them), subfolders kept."""
    out = set()
    for node in (wf or {}).values():
        for v in (node.get("inputs") or {}).values() if isinstance(node, dict) else ():
            if isinstance(v, str) and "\n" not in v and v.lower().endswith(MODEL_EXTS):
                out.add(v)
    return out


def _dirs(folders):
    """Every model directory in a /internal/folder_paths reply ({name: [dir, ...]}, or {name: [[dir, ...], exts]}),
    each once, in order."""
    seen = []
    for v in (folders or {}).values():
        paths = v[0] if v and isinstance(v[0], list) else v
        for d in paths or ():
            if isinstance(d, str) and d not in seen:
                seen.append(d)
    return seen


def _file_size(path):
    """The size of a regular file, or None when there's no file there."""
    try:
        p = Path(path)
        return p.stat().st_size if p.is_file() else None
    except OSError:
        return None


def model_bytes(names, folders):
    """(total size of the named model files found in ComfyUI's model folders, sorted names not found)."""
    dirs = _dirs(folders)
    total, missing = 0, []
    for name in sorted(names):
        for d in dirs:
            size = _file_size(Path(d) / name)
            if size is not None:
                total += size
                break
        else:
            missing.append(name)
    return total, missing


def _win_status():
    class MEMSTAT(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MEMSTAT()
    m.dwLength = ctypes.sizeof(MEMSTAT)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise OSError("GlobalMemoryStatusEx failed")
    # TotalPageFile / AvailPageFile are the commit limit and the commit room left, despite the names
    return m.ullTotalPhys, m.ullAvailPhys, m.ullTotalPageFile, m.ullAvailPageFile


def _read_meminfo():
    return Path("/proc/meminfo").read_text(encoding="ascii")


def host_memory(*, _platform=None, _win_status=_win_status, _meminfo=_read_meminfo):
    """This machine's memory in bytes: {"ram_total", "ram_avail", "headroom", "kind"} plus, on Windows,
    "commit_used" and "commit_limit". `headroom` is what a new job can take: Windows' commit room ("commit"),
    or Linux's MemAvailable ("available"; Linux overcommits, so its commit figures aren't a limit). None
    elsewhere or when it can't be read."""
    plat = _platform or sys.platform
    try:
        if plat == "win32":
            total, avail, limit, room = _win_status()
            return {"ram_total": total, "ram_avail": avail, "headroom": room, "kind": "commit",
                    "commit_used": limit - room, "commit_limit": limit}
        if plat.startswith("linux"):
            info = {}
            for line in _meminfo().splitlines():
                key, _, rest = line.partition(":")
                if rest.strip():
                    info[key.strip()] = int(rest.split()[0]) * 1024
            return {"ram_total": info["MemTotal"], "ram_avail": info["MemAvailable"],
                    "headroom": info["MemAvailable"], "kind": "available"}
    except (OSError, KeyError, ValueError, AttributeError):
        return None
    return None


def margin(ram_total):
    """Memory kept free for Windows and the apps beside ComfyUI: 10% of RAM, at least 4 GB."""
    return max(DESKTOP_FLOOR, DESKTOP_SHARE * ram_total)


def job_need(model_total):
    """Memory a job whose model files total `model_total` bytes is expected to take."""
    return model_total * OVERHEAD + BASE


def _left(mem):
    if mem["kind"] == "commit":
        return (f"Windows has {mem['headroom'] / GB:.1f} GB of commit room left ({mem['commit_used'] / GB:.0f} of "
                f"{mem['commit_limit'] / GB:.0f} GB is committed by what's running)")
    return f"{mem['headroom'] / GB:.1f} GB of memory is available"


def ensure_room(client, wf, *, _mem=None, _sleep=time.sleep, _env=None, settle=5.0):
    """Check that `wf`'s models fit before it is queued on `client`'s ComfyUI. Returns None (fits, or the check
    doesn't apply) or a note when it had ComfyUI unload earlier models to make room; raises MemoryGuardError
    when the job still doesn't fit."""
    _mem, _env = _mem or host_memory, os.environ if _env is None else _env
    if str(_env.get(SKIP_ENV, "")).strip().lower() in ("1", "true", "yes", "on"):
        return None
    if not is_local(getattr(client, "base", "")):
        return None   # another machine's memory isn't ours to judge
    try:
        folders = client._get("/internal/folder_paths")
    except Exception:
        return None   # an older ComfyUI without the endpoint, or a proxy: no sizes, no check
    total, missing = model_bytes(graph_model_files(wf), folders)
    if total <= 0:
        return None
    mem = _mem()
    if mem is None:
        return None
    need, keep = job_need(total), margin(mem["ram_total"])
    if need <= mem["headroom"] - keep:
        return None
    try:   # ComfyUI may still hold an earlier job's models; ask it to let go and look again
        client.free()
    except Exception:
        pass
    _sleep(settle)
    mem = _mem() or mem
    if need <= mem["headroom"] - keep:
        return f"freed ComfyUI's cached models to make room ({need / GB:.0f} GB needed)"
    unknown = f" ({len(missing)} model file(s) not found locally aren't counted)" if missing else ""
    raise MemoryGuardError(
        f"not enough memory for this job: its models come to {total / GB:.1f} GB{unknown}, so ComfyUI needs about "
        f"{need / GB:.0f} GB, but {_left(mem)} and {keep / GB:.1f} GB stays free for the desktop, even after "
        f"ComfyUI unloaded earlier models. Close heavy apps or wait for other work to finish, then run it again; "
        f"set {SKIP_ENV}=1 to run it anyway (a job past this limit can freeze Windows).")


def doctor_line(_mem=None):
    """A doctor line: how much memory ComfyUI jobs can take before the guard refuses them."""
    mem = (_mem or host_memory)()
    if mem is None:
        return ("info", "Memory guard: not available on this OS (jobs aren't checked)")
    keep = margin(mem["ram_total"])
    room = mem["headroom"] - keep
    what = "commit room" if mem["kind"] == "commit" else "available memory"
    line = (f"Memory: {max(room, 0) / GB:.1f} GB free for ComfyUI jobs ({mem['headroom'] / GB:.1f} GB of {what}, "
            f"{keep / GB:.1f} GB kept for the desktop)")
    if room < 8 * GB:
        return ("warn", line + " - close heavy apps before video or FLUX.2 jobs; the guard refuses jobs that don't fit")
    return ("info", line + "; a job whose models need more is refused before it starts")

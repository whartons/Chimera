"""The memory guard: refuse a local ComfyUI job that won't fit in this machine's memory, before it starts.

2026-11-11: an LTX-2.3 job on a 62 GB Windows box, beside an IDE, a browser and another session's test suites, drove
the commit charge to 122 GB of a 107.6 GB limit; Windows paged until the desktop froze (twice: explorer crashed, then
the user had to stop ComfyUI from a phone). The job's models came to ~30 GB; only ~20 GB of commit room was left."""
from __future__ import annotations
from pathlib import Path
import pytest
from scripts.brandkit import memguard as mg

GB = 2**30


def _wf():
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "ltx-2.3-22b.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "split_files/gemma.safetensors", "type": "ltxv"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "video_vae.safetensors"}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "distill.safetensors", "model": ["1", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "a rover. weights.safetensors in a prompt", "clip": ["2", 0]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": "rover.png"}},
    }


def test_the_graphs_model_files_are_its_loader_inputs():
    assert mg.graph_model_files(_wf()) == {"ltx-2.3-22b.safetensors", "split_files/gemma.safetensors",
                                           "video_vae.safetensors", "distill.safetensors"}


@pytest.fixture
def folders(monkeypatch):
    """Model folders like ComfyUI's /internal/folder_paths ({name: [dir, ...]}) holding `files` {relpath: GB}. The
    sizes come from a lookup, never from files on disk: a 16 GB test file is 16 GB of disk on Windows."""
    sizes = {}
    monkeypatch.setattr(mg, "_file_size", lambda p: sizes.get(Path(p).as_posix()))
    root = Path("/models-root")

    def make(files):
        a, b, v = root / "models" / "diffusion_models", root / "shared" / "text_encoders", root / "models" / "vae"
        for rel, gb in files.items():
            d = b if "gemma" in rel else a if "ltx" in rel or "distill" in rel else v
            sizes[(d / rel).as_posix()] = int(gb * GB)
        return {"diffusion_models": [str(a)], "loras": [str(a)], "text_encoders": [str(root / "x"), str(b)],
                "vae": [str(v)]}
    return make


def test_sizes_come_from_comfyuis_own_model_folders(folders):
    fs = folders({"ltx-2.3-22b.safetensors": 16, "split_files/gemma.safetensors": 11,
                                  "video_vae.safetensors": 1.5})
    total, missing = mg.model_bytes(mg.graph_model_files(_wf()), fs)
    assert total == int(28.5 * GB) and missing == ["distill.safetensors"]


def test_windows_headroom_is_the_commit_room_left():
    mem = mg.host_memory(_platform="win32", _win_status=lambda: (64 * GB, 20 * GB, 107 * GB, 20 * GB))
    assert mem == {"ram_total": 64 * GB, "ram_avail": 20 * GB, "headroom": 20 * GB, "kind": "commit",
                   "commit_used": 87 * GB, "commit_limit": 107 * GB}


def test_linux_headroom_is_available_memory():
    meminfo = "MemTotal:       65536000 kB\nMemAvailable:   20971520 kB\nCommitLimit: 1 kB\nCommitted_AS: 9 kB\n"
    mem = mg.host_memory(_platform="linux", _meminfo=lambda: meminfo)
    assert mem["headroom"] == 20 * GB and mem["kind"] == "available" and mem["ram_total"] == 62.5 * GB


def test_an_unknown_os_skips_the_check():
    assert mg.host_memory(_platform="darwin") is None


class _Client:
    def __init__(self, folders, base="http://127.0.0.1:8000"):
        self.base, self.folders, self.freed, self.queued = base, folders, 0, 0

    def _get(self, path):
        assert path == "/internal/folder_paths"
        if self.folders is None:
            raise OSError("404")
        return self.folders

    def free(self):
        self.freed += 1


def _mem(headroom_gb, ram_gb=64):
    return lambda: {"ram_total": ram_gb * GB, "ram_avail": 10 * GB, "headroom": headroom_gb * GB, "kind": "commit",
                    "commit_used": 80 * GB, "commit_limit": (80 + headroom_gb) * GB}


def test_a_job_that_fits_runs_without_freeing_anything(folders):
    c = _Client(folders({"ltx-2.3-22b.safetensors": 16, "split_files/gemma.safetensors": 11}))
    assert mg.ensure_room(c, _wf(), _mem=_mem(60), _sleep=lambda s: None, _env={}) is None and c.freed == 0


def test_the_2026_11_11_ltx_job_would_have_been_refused(folders):
    c = _Client(folders({"ltx-2.3-22b.safetensors": 16, "split_files/gemma.safetensors": 11,
                                    "video_vae.safetensors": 1.5}))
    with pytest.raises(mg.MemoryGuardError) as e:
        mg.ensure_room(c, _wf(), _mem=_mem(20, ram_gb=62), _sleep=lambda s: None, _env={})
    msg = str(e.value)
    assert c.freed == 1                                       # it first asked ComfyUI to let go of earlier models
    assert "28.5 GB" in msg and "CHIMERA_SKIP_MEMORY_CHECK" in msg and "20" in msg


def test_freeing_comfyuis_cached_models_can_make_room(folders):
    c = _Client(folders({"ltx-2.3-22b.safetensors": 16}))
    seq = iter([10, 40])
    note = mg.ensure_room(c, _wf(), _mem=lambda: _mem(next(seq))(), _sleep=lambda s: None, _env={})
    assert c.freed == 1 and note and "freed" in note


@pytest.mark.parametrize("why, client, env", [
    ("remote ComfyUI", _Client({}, base="http://192.168.1.5:8000"), {}),
    ("switched off", _Client({}), {"CHIMERA_SKIP_MEMORY_CHECK": "1"}),
    ("no folder_paths (older ComfyUI)", _Client(None), {}),
])
def test_the_check_steps_aside(why, client, env):
    assert mg.ensure_room(client, _wf(), _mem=_mem(1), _sleep=lambda s: None, _env=env) is None, why
    assert client.freed == 0


def test_a_graph_whose_files_cant_be_found_is_not_refused(folders):
    c = _Client(folders({}))
    assert mg.ensure_room(c, _wf(), _mem=_mem(1), _sleep=lambda s: None, _env={}) is None


def test_the_desktop_keeps_a_share_of_ram():
    assert mg.margin(62 * GB) == pytest.approx(6.2 * GB) and mg.margin(16 * GB) == 4 * GB


def test_room_report_for_doctor():
    lvl, msg = mg.doctor_line(_mem=_mem(20, ram_gb=62))
    assert lvl == "info" and "commit" in msg and "13.8 GB" in msg   # 20 GB headroom - 6.2 GB kept for the desktop


def test_doctor_warns_when_there_is_barely_room_for_anything():
    lvl, msg = mg.doctor_line(_mem=_mem(7, ram_gb=62))
    assert lvl == "warn" and "close" in msg.lower()


# --- wired in: generate refuses before queueing, the loops' graph runner too, doctor reports the room --------
def test_generate_refuses_a_job_that_wont_fit_before_queueing_it(monkeypatch, tmp_path, capsys):
    import sys as _sys
    from scripts import generate
    from tests.test_integration import FakeComfy, _img_args, _StubAp, _tmp_repo
    queued = []

    class Comfy(FakeComfy):
        def queue_prompt(self, wf):
            queued.append(wf)
            return "pid"

    def refuse(client, wf):
        assert any(n.get("class_type") for n in wf.values())   # the graph that would have been queued
        raise mg.MemoryGuardError("not enough memory for this job: ...")
    monkeypatch.setattr(generate, "ComfyClient", Comfy)
    monkeypatch.setattr(generate, "ensure_room", refuse)
    with pytest.raises(SystemExit) as e:
        generate.run(_img_args(seed=7), _tmp_repo(tmp_path), _StubAp())
    assert e.value.code == 1 and queued == []
    assert "render refused: not enough memory" in capsys.readouterr().err
    assert _sys is not None


def test_generate_says_when_it_freed_comfyui_to_make_room(monkeypatch, tmp_path, capsys):
    from scripts import generate
    from tests.test_integration import FakeComfy, _img_args, _StubAp, _tmp_repo
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    monkeypatch.setattr(generate, "ensure_room", lambda client, wf: "freed ComfyUI's cached models to make room")
    generate.run(_img_args(seed=7), _tmp_repo(tmp_path), _StubAp())
    assert "freed ComfyUI's cached models" in capsys.readouterr().err


def test_the_loops_graph_runner_checks_before_queueing(monkeypatch, tmp_path):
    from scripts.brandkit import outputs

    class C:
        base = "http://127.0.0.1:8000"
        def queue_prompt(self, wf):
            raise AssertionError("must not queue")
    monkeypatch.setattr(outputs, "ensure_room", lambda client, wf: (_ for _ in ()).throw(mg.MemoryGuardError("no")))
    with pytest.raises(mg.MemoryGuardError):
        outputs.run_graph_to_file(C(), {"1": {"class_type": "X", "inputs": {}}}, tmp_path)


def test_doctor_reports_the_memory_room(monkeypatch, capsys):
    import sys as _sys
    from scripts import generate
    import scripts.brandkit.doctor as d
    monkeypatch.setattr(generate, "ComfyClient", lambda url: object())
    monkeypatch.setattr(d, "run_checks", lambda client, root, brand: [("ok", "all good")])
    monkeypatch.setattr(mg, "host_memory", _mem(30, ram_gb=62))
    monkeypatch.setattr(_sys, "argv", ["generate.py", "doctor"])
    with pytest.raises(SystemExit):
        generate.main()
    assert "Memory: 23.8 GB free for ComfyUI jobs" in capsys.readouterr().out

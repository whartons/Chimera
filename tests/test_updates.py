import io, json, types
from scripts.brandkit import updates


class FakeClient:
    def __init__(self, version):
        self._v = version
    def comfyui_version(self):
        return self._v


def test_check_updates_all_current(monkeypatch):
    monkeypatch.setattr(updates, "_repo_behind", lambda root: 0)
    res = updates.check_updates(FakeClient("v0.24.1"), ".", latest_comfyui="v0.24.1")
    assert ("ok", "chimera: up to date with origin/main") in res
    assert any(lvl == "ok" and "ComfyUI: v0.24.1 (latest)" in msg for lvl, msg in res)
    assert updates.print_updates(res) == 0     # no warns


def test_check_updates_repo_behind_and_comfyui_outdated(monkeypatch, capsys):
    monkeypatch.setattr(updates, "_repo_behind", lambda root: 3)
    res = updates.check_updates(FakeClient("v0.24.0"), ".", latest_comfyui="v0.24.1")
    assert any(lvl == "warn" and "3 commit(s) behind" in msg for lvl, msg in res)
    assert any(lvl == "warn" and "running v0.24.0, latest v0.24.1" in msg for lvl, msg in res)
    assert updates.print_updates(res) == 2
    assert "-> 2 update(s) available" in capsys.readouterr().out


def test_check_updates_unreachable_and_not_a_repo(monkeypatch):
    monkeypatch.setattr(updates, "_repo_behind", lambda root: None)
    res = updates.check_updates(FakeClient(None), ".", latest_comfyui=None)
    assert any(lvl == "info" and "not a git checkout" in msg for lvl, msg in res)
    assert any(lvl == "info" and "ComfyUI: not reachable" in msg for lvl, msg in res)
    assert updates.print_updates(res) == 0


def test_check_updates_ignores_v_prefix_mismatch(monkeypatch):
    # "0.24.1" vs "v0.24.1" are the same version — must not be flagged as an update
    monkeypatch.setattr(updates, "_repo_behind", lambda root: 0)
    res = updates.check_updates(FakeClient("0.24.1"), ".", latest_comfyui="v0.24.1")
    assert not any(lvl == "warn" and "ComfyUI" in msg for lvl, msg in res)


def test_repo_behind_survives_hung_fetch(monkeypatch):
    # a timed-out `git fetch` must NOT masquerade as "not a git checkout" — the docstring promises
    # the offline case compares against the last-known origin/main
    import subprocess
    def fake_run(cmd, **k):
        if "fetch" in cmd:
            raise subprocess.TimeoutExpired(cmd, 15)
        if "rev-parse" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if "rev-list" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="3\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert updates._repo_behind(".") == 3


def test_check_updates_pin_list_matches_update_report_tables(monkeypatch):
    # the pinned-deps guidance must name what is ACTUALLY pinned (update_report's tables are the
    # single source of truth): IPAdapter + the MCP bridges are pins; QwenVL was retired
    monkeypatch.setattr(updates, "_repo_behind", lambda root: 0)
    res = updates.check_updates(FakeClient("v1"), ".", latest_comfyui=None)
    line = next(msg for lvl, msg in res if "PINNED" in msg)
    assert "ComfyUI_IPAdapter_plus" in line
    assert "comfyui-mcp" in line and "blender_mcp" in line
    assert "QwenVL" not in line


def test_repo_behind_parses_count(monkeypatch):
    import subprocess
    def fake_run(cmd, **k):
        if "rev-parse" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if "rev-list" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="5\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")   # fetch
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert updates._repo_behind(".") == 5


def test_repo_behind_not_a_repo_or_git_absent(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: types.SimpleNamespace(returncode=128, stdout="", stderr=""))
    assert updates._repo_behind(".") is None
    def boom(cmd, **k):
        raise FileNotFoundError("git not on PATH")
    monkeypatch.setattr(subprocess, "run", boom)
    assert updates._repo_behind(".") is None


def test_latest_comfyui_release_parses_tag(monkeypatch):
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda req, timeout=0: Resp(json.dumps({"tag_name": "v0.24.5"}).encode()))
    assert updates.latest_comfyui_release() == "v0.24.5"


def test_latest_comfyui_release_offline_returns_none(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("offline")
    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
    assert updates.latest_comfyui_release() is None

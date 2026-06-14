import json, types, pytest
from scripts.brandkit import blender as B


def _fake_proc(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_template_builds_argv_and_parses_manifest(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    seen = {}
    def runner(argv, **kw):
        seen["argv"] = argv; seen["kw"] = kw
        return _fake_proc(stdout='noise\n@@CHIMERA_MANIFEST@@ {"outputs": ["a.png"], "blender_version": "5.1.2"}\nbye')
    out = B.run_template(tmpl, {"samples": 8}, blender_bin="blender", timeout=123, _runner=runner)
    assert out == {"outputs": ["a.png"], "blender_version": "5.1.2"}
    a = seen["argv"]
    assert a[0] == "blender"
    assert "--background" in a and "--factory-startup" in a
    assert a[a.index("--python") + 1] == str(tmpl)
    assert a[-2] == "--" and json.loads(a[-1]) == {"samples": 8}
    assert seen["kw"]["timeout"] == 123


def test_run_template_raises_on_nonzero(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    runner = lambda argv, **kw: _fake_proc(returncode=1, stderr="boom-traceback")
    with pytest.raises(B.BlenderJobError) as e:
        B.run_template(tmpl, {}, blender_bin="blender", _runner=runner)
    assert "boom-traceback" in str(e.value)


def test_run_template_raises_when_no_manifest(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    runner = lambda argv, **kw: _fake_proc(stdout="rendered fine but printed nothing")
    with pytest.raises(B.BlenderJobError):
        B.run_template(tmpl, {}, blender_bin="blender", _runner=runner)


def test_find_blender_prefers_env(monkeypatch):
    monkeypatch.setenv("BLENDER_BIN", "C:/custom/blender.exe")
    monkeypatch.setattr(B.shutil, "which", lambda n: None)
    assert B.find_blender() == "C:/custom/blender.exe"


def test_find_blender_uses_path(monkeypatch):
    monkeypatch.delenv("BLENDER_BIN", raising=False)
    monkeypatch.setattr(B.shutil, "which", lambda n: "/usr/bin/blender")
    assert B.find_blender() == "/usr/bin/blender"


def test_find_blender_raises_when_absent(monkeypatch):
    monkeypatch.delenv("BLENDER_BIN", raising=False)
    monkeypatch.setattr(B.shutil, "which", lambda n: None)
    monkeypatch.setattr(B.os.path, "exists", lambda p: False)
    with pytest.raises(B.BlenderJobError):
        B.find_blender()

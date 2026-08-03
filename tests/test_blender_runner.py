import json, subprocess, types, pytest
from scripts.brandkit import blender as B


def test_run_template_raises_on_timeout(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    def runner(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    with pytest.raises(B.BlenderJobError, match="timed out"):
        B.run_template(tmpl, {}, blender_bin="blender", timeout=5, _runner=runner)


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


def test_run_template_wraps_corrupt_manifest_json(tmp_path):
    # a corrupt/interleaved manifest line must surface as BlenderJobError (the runner contract),
    # not escape as a raw JSONDecodeError — parity with the FreeCAD runner
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    runner = lambda argv, **kw: _fake_proc(stdout="@@CHIMERA_MANIFEST@@ {not json")
    with pytest.raises(B.BlenderJobError, match="not valid JSON"):
        B.run_template(tmpl, {}, blender_bin="blender", _runner=runner)


def test_run_template_no_manifest_surfaces_stderr(tmp_path):
    # blender prints script errors to stderr while exiting 0 — the no-manifest error must carry
    # stderr so callers (and the mesh3d loop) can see WHY the template died
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    runner = lambda argv, **kw: _fake_proc(stdout="clean exit",
                                           stderr="AttributeError: bad bpy call")
    with pytest.raises(B.BlenderJobError, match="AttributeError"):
        B.run_template(tmpl, {}, blender_bin="blender", _runner=runner)


def test_find_blender_globs_newest_default_install(monkeypatch, tmp_path):
    # default Windows discovery must survive version drift (5.2+), like the FreeCAD runner's glob
    monkeypatch.delenv("BLENDER_BIN", raising=False)
    monkeypatch.setattr(B.shutil, "which", lambda n: None)
    for ver in ("5.1", "5.2"):
        d = tmp_path / f"Blender {ver}"; d.mkdir()
        (d / "blender.exe").write_bytes(b"")
    monkeypatch.setattr(B, "_DEFAULT_GLOB", str(tmp_path / "Blender *" / "blender.exe"))
    assert B.find_blender().replace("\\", "/").endswith("Blender 5.2/blender.exe")


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
    monkeypatch.setattr(B.glob, "glob", lambda p: [])
    with pytest.raises(B.BlenderJobError):
        B.find_blender()

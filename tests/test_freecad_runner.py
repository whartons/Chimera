import json, subprocess, types, pytest
from pathlib import Path
from scripts.brandkit import freecad as F


def _fake_proc(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_template_raises_on_timeout(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    def runner(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    with pytest.raises(F.FreeCADJobError, match="timed out"):
        F.run_template(tmpl, {}, freecad_bin="fc", timeout=5, _runner=runner)


def test_run_template_argv_and_paramsfile_and_manifest(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    seen = {}
    def runner(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw
        # params are passed via a temp JSON file = the last argv; it must round-trip the dict
        seen["params"] = json.loads(Path(argv[-1]).read_text())
        return _fake_proc(stdout='noise\n@@CHIMERA_MANIFEST@@ {"outputs": ["b.step"], "freecad_version": "1.1.1"}\nbye')
    out = F.run_template(tmpl, {"shape": "box"}, freecad_bin="fc", timeout=42, _runner=runner)
    assert out == {"outputs": ["b.step"], "freecad_version": "1.1.1"}
    a = seen["argv"]
    assert a[0] == "fc" and a[1] == str(tmpl)
    assert a[-1].endswith(".json")
    assert seen["params"] == {"shape": "box"}
    assert seen["kw"]["timeout"] == 42


def test_run_template_cleans_up_params_file(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    captured = {}
    def runner(argv, **kw):
        captured["pf"] = argv[-1]
        return _fake_proc(stdout='@@CHIMERA_MANIFEST@@ {"outputs": []}')
    F.run_template(tmpl, {"a": 1}, freecad_bin="fc", _runner=runner)
    assert not Path(captured["pf"]).exists()   # temp params file removed in finally


def test_run_template_cleans_up_params_file_on_error(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    captured = {}
    def runner(argv, **kw):
        captured["pf"] = argv[-1]
        return _fake_proc(returncode=1, stderr="boom")
    with pytest.raises(F.FreeCADJobError):
        F.run_template(tmpl, {"a": 1}, freecad_bin="fc", _runner=runner)
    assert not Path(captured["pf"]).exists()


def test_run_template_raises_on_nonzero(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    runner = lambda argv, **kw: _fake_proc(returncode=1, stderr="freecad-boom")
    with pytest.raises(F.FreeCADJobError) as e:
        F.run_template(tmpl, {}, freecad_bin="fc", _runner=runner)
    assert "freecad-boom" in str(e.value)


def test_run_template_raises_when_no_manifest(tmp_path):
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    runner = lambda argv, **kw: _fake_proc(stdout="did stuff, said nothing parseable")
    with pytest.raises(F.FreeCADJobError):
        F.run_template(tmpl, {}, freecad_bin="fc", _runner=runner)


def test_find_freecad_prefers_explicit_then_env(monkeypatch):
    monkeypatch.setenv("FREECAD_BIN", "C:/x/FreeCADCmd.exe")
    monkeypatch.setattr(F.shutil, "which", lambda n: None)
    assert F.find_freecad("C:/explicit/FreeCADCmd.exe") == "C:/explicit/FreeCADCmd.exe"
    assert F.find_freecad() == "C:/x/FreeCADCmd.exe"


def test_find_freecad_uses_path(monkeypatch):
    monkeypatch.delenv("FREECAD_BIN", raising=False)
    monkeypatch.setattr(F.shutil, "which", lambda n: "/usr/bin/freecadcmd" if n == "freecadcmd" else None)
    assert F.find_freecad() == "/usr/bin/freecadcmd"


def test_find_freecad_raises_when_absent(monkeypatch):
    monkeypatch.delenv("FREECAD_BIN", raising=False)
    monkeypatch.setattr(F.shutil, "which", lambda n: None)
    monkeypatch.setattr(F.glob, "glob", lambda p: [])
    with pytest.raises(F.FreeCADJobError):
        F.find_freecad()

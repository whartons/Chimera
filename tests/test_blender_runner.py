import json, subprocess, types, pytest
from scripts.brandkit import blender as B
from scripts.brandkit import dcc as D


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
    monkeypatch.setattr(D.shutil, "which", lambda n: None)
    for ver in ("5.1", "5.2"):
        d = tmp_path / f"Blender {ver}"; d.mkdir()
        (d / "blender.exe").write_bytes(b"")
    monkeypatch.setattr(B, "_DEFAULT_GLOB", str(tmp_path / "Blender *" / "blender.exe"))
    assert B.find_blender().replace("\\", "/").endswith("Blender 5.2/blender.exe")


def test_find_blender_prefers_env(monkeypatch):
    monkeypatch.setenv("BLENDER_BIN", "C:/custom/blender.exe")
    monkeypatch.setattr(D.shutil, "which", lambda n: None)
    assert B.find_blender() == "C:/custom/blender.exe"


def test_find_blender_uses_path(monkeypatch):
    monkeypatch.delenv("BLENDER_BIN", raising=False)
    monkeypatch.setattr(D.shutil, "which", lambda n: "/usr/bin/blender")
    assert B.find_blender() == "/usr/bin/blender"


def test_find_blender_raises_when_absent(monkeypatch):
    monkeypatch.delenv("BLENDER_BIN", raising=False)
    monkeypatch.setattr(D.shutil, "which", lambda n: None)
    monkeypatch.setattr(D.glob, "glob", lambda p: [])
    with pytest.raises(B.BlenderJobError):
        B.find_blender()


def test_run_template_decodes_utf8_and_reports_a_missing_binary(tmp_path):
    # the locale codec (cp1252) garbled a non-ASCII path in Blender's output; a wrong --blender-bin
    # surfaced as a raw FileNotFoundError traceback
    import pytest as _pytest
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")
    seen = {}

    def runner(argv, **kw):
        seen.update(kw)
        return _fake_proc(stdout='@@CHIMERA_MANIFEST@@ {"outputs": ["C:/Users/\u00e9/r.png"]}')
    assert B.run_template(tmpl, {}, blender_bin="blender", _runner=runner)["outputs"] == ["C:/Users/\u00e9/r.png"]
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"

    def missing(argv, **kw):
        raise FileNotFoundError(2, "The system cannot find the file specified")
    with _pytest.raises(B.BlenderJobError, match="couldn.t start"):
        B.run_template(tmpl, {}, blender_bin="C:/nope/blender.exe", _runner=missing)


def test_blender_jobs_and_freecad_jobs_get_no_credentials(tmp_path, monkeypatch):
    # FreeCAD was scrubbed but headless Blender inherited every API key; and the name list missed proxies with
    # user:password, package-index URLs, webhooks and connection strings (2026-10 security review)
    for k, v in {"OPENAI_API_KEY": "sk", "HTTPS_PROXY": "http://u:p@h", "PIP_INDEX_URL": "https://t@x/simple",
                 "SLACK_WEBHOOK": "https://hooks", "AWS_PROFILE": "prod", "REDIS_URL": "redis://:p@h",
                 "GIT_ASKPASS": "x", "MY_PASSPHRASE": "x"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CHIMERA_TEST_KEEP", "1")
    seen = {}
    tmpl = tmp_path / "t.py"; tmpl.write_text("x")

    def runner(argv, **kw):
        seen.update(kw["env"])
        return types.SimpleNamespace(returncode=0, stdout=D.MANIFEST_TAG + ' {"outputs": []}', stderr="")
    B.run_template(tmpl, {}, blender_bin="blender", _runner=runner)
    assert not {"OPENAI_API_KEY", "HTTPS_PROXY", "PIP_INDEX_URL", "SLACK_WEBHOOK", "AWS_PROFILE", "REDIS_URL",
                "GIT_ASKPASS", "MY_PASSPHRASE"} & set(seen)
    assert seen.get("CHIMERA_TEST_KEEP") == "1" and any(k.upper() == "PATH" for k in seen)


def test_job_outputs_must_stay_in_the_job_folder(tmp_path):
    inside = tmp_path / "job" / "m.stl"
    assert D.job_outputs({"outputs": [str(inside)]}, tmp_path / "job", RuntimeError) == [str(inside)]
    assert D.job_outputs({}, tmp_path / "job", RuntimeError) == []
    with pytest.raises(RuntimeError, match="outside its folder"):
        D.job_outputs({"outputs": [str(inside), str(tmp_path / "other.stl")]}, tmp_path / "job", RuntimeError)
    with pytest.raises(RuntimeError, match="outside its folder"):
        D.job_outputs({"outputs": [str(tmp_path / "job" / ".." / "x.stl")]}, tmp_path / "job", RuntimeError)



def test_the_env_scrub_drops_passwords_proxies_and_connection_urls(monkeypatch):
    names = ("DB_PASS", "SMTP_PASS", "PGPASSFILE", "HTTPS_PROXY", "SLACK_WEBHOOK_URL", "MONGO_URI", "AWS_PROFILE")
    for k in names:
        monkeypatch.setenv(k, "secret")
    env = D.scrubbed_env()
    assert not set(names) & set(env)
    assert any(k.upper() == "PATH" for k in env)

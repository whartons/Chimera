import argparse, pytest
from pathlib import Path
import scripts.agent.cad_generate as CG


class _Gen:
    def __init__(self, script="box = 1"):
        self.script = script; self.calls = []; self.prev = None

    def generate_script(self, brief, fix_feedback=None):
        self.calls.append((brief, fix_feedback)); self.prev = self.script; return self.script


def _args(**kw):
    base = dict(brand=None, subject="a coffee mug", samples=24, res=[512, 512], freecad_bin=None,
                blender_bin=None, freecad_timeout=None, blender_timeout=None)
    base.update(kw); return argparse.Namespace(**base)


def _ok_runners(tmp_path):
    def fc(tmpl, params, **kw):
        assert params.get("restrict") is True   # LLM scripts run restricted
        stl = Path(params["out_dir"]) / "m.stl"; stl.write_text("stl"); return {"outputs": [str(stl)]}

    def bl(tmpl, params, **kw):
        outs = []
        for i in range(4):
            p = Path(params["out_dir"]) / f"v{i}.png"; p.write_text("p"); outs.append(str(p))
        return {"outputs": outs}
    return fc, bl


def test_make_cad_generate_pipeline(tmp_path, monkeypatch):
    gen = _Gen("box = 1")

    def fc_runner(tmpl, params, **kw):
        assert "script_exec.py" in str(tmpl) and params["formats"] == ["stl"]
        assert params.get("restrict") is True                                    # LLM scripts run restricted
        assert Path(params["script"]).read_text(encoding="utf-8") == "box = 1"   # script written out
        stl = Path(params["out_dir"]) / "m.stl"; stl.write_text("stl")
        return {"outputs": [str(stl)]}

    def bl_runner(tmpl, params, **kw):
        assert "mesh_eval.py" in str(tmpl) and params["views"] == 4 and params["seed"] == 5
        outs = []
        for i in range(4):
            p = Path(params["out_dir"]) / f"v{i}.png"; p.write_text("p"); outs.append(str(p))
        return {"outputs": outs}

    monkeypatch.setattr(CG.montage, "contact_sheet",
                        lambda paths, out, **k: Path(out).write_text("sheet") or Path(out))
    routed = {}

    def fake_route(root, brand, src, mode, seed, **kw):
        d = Path(root) / "outputs" / ("3d" if Path(src).suffix == ".stl" else "images") / f"{mode}_{seed}{Path(src).suffix}"
        d.parent.mkdir(parents=True, exist_ok=True); d.write_text("x"); routed[Path(src).suffix] = d
        return d

    monkeypatch.setattr(CG, "route_output", fake_route)
    g = CG.make_cad_generate(_args(), tmp_path, gen, freecad_runner=fc_runner, blender_runner=bl_runner)
    sheet = g("EXPANDED PROMPT", "", 5)
    assert gen.calls == [("a coffee mug", None)]      # brief = clean subject, no feedback on iter 0
    assert Path(sheet).suffix == ".png" and ".stl" in routed   # sheet returned + STL routed
    assert Path(sheet).with_name(Path(sheet).stem + ".cad.py").read_text() == "box = 1"   # script saved


def test_make_cad_generate_forwards_feedback_on_revise(tmp_path, monkeypatch):
    gen = _Gen("box = 1")
    fc, bl = _ok_runners(tmp_path)
    monkeypatch.setattr(CG.montage, "contact_sheet", lambda paths, out, **k: Path(out).write_text("s") or Path(out))
    monkeypatch.setattr(CG, "route_output",
                        lambda root, brand, src, mode, seed, **kw: Path(src))
    g = CG.make_cad_generate(_args(subject="a mug"), tmp_path, gen, freecad_runner=fc, blender_runner=bl)
    g("a mug", "", 1)                 # iteration 0
    g("a mug. Correct: add a handle", "", 2)   # iteration 1 (the expander's pos carries the FIX)
    assert gen.calls[0] == ("a mug", None)                              # iter 0: clean brief, no feedback
    assert gen.calls[1] == ("a mug", "a mug. Correct: add a handle")    # iter 1: feedback forwarded


def test_make_cad_generate_rejects_unsafe_script(tmp_path):
    # the autonomous loop execs LLM-authored scripts -> a script reaching for shell/network/file ops
    # is rejected before it's written or run, and a rejected script does NOT seed the next revision
    for bad in ("import subprocess\nbox=1", "import os\nos.system('x')\n", "import shutil\nshutil.rmtree('/')",
                "import socket\n", "import requests\n", "__import__('os')\n", "open('x','w').write('y')\n",
                "getattr(__builtins__,'open')\n", "import importlib\n", "p.unlink()\n", "os.environ\n"):
        gen = _Gen(bad)
        g = CG.make_cad_generate(_args(), tmp_path, gen,
                                 freecad_runner=lambda t, p, **k: {"outputs": ["x.stl"]},
                                 blender_runner=lambda t, p, **k: {"outputs": []})
        with pytest.raises(RuntimeError, match="disallowed"):
            g("x", "", 1)
        assert gen.prev is None   # rejected script restored to last_good (None) — not fed to next revise


def test_assert_safe_allows_normal_modelling():
    CG._assert_safe("import FreeCAD as App\nimport Part\nimport math\n"
                    "box = Part.makeBox(10, 10, 10)\nr = math.pi\n"
                    "doc.addObject('Part::Feature', 'B').Shape = box\nRESULT = [doc.Objects[0]]")


def test_make_cad_generate_no_stl_raises(tmp_path):
    g = CG.make_cad_generate(_args(), tmp_path, _Gen(),
                             freecad_runner=lambda t, p, **k: {"outputs": []},
                             blender_runner=lambda t, p, **k: {"outputs": []})
    with pytest.raises(RuntimeError, match="no STL"):
        g("x", "", 1)


def test_make_cad_generate_writes_geometry_checks_for_the_gate(tmp_path, monkeypatch):
    # BREP is manifold, but a script can still build disconnected bodies: a VLM passed a fan rotor whose 16
    # blades floated free of the hub (2026-10). The checks ride beside the sheet for GeometryAwareJudge.
    import json
    from scripts.agent.geometry import structural_issues
    fc, _ = _ok_runners(tmp_path)

    def bl(tmpl, params, **kw):
        outs = []
        for i in range(4):
            p = Path(params["out_dir"]) / f"v{i}.png"; p.write_text("p"); outs.append(str(p))
        return {"outputs": outs, "checks": {"loose_parts": 17, "major_parts": 17}}

    monkeypatch.setattr(CG.montage, "contact_sheet", lambda paths, out, **k: Path(out).write_text("s") or Path(out))

    def route(root, brand, src, mode, seed, **kw):
        d = Path(root) / "out" / f"{mode}_{seed}{Path(src).suffix}"
        d.parent.mkdir(parents=True, exist_ok=True); d.write_text("x"); return d

    monkeypatch.setattr(CG, "route_output", route)
    sheet = Path(CG.make_cad_generate(_args(), tmp_path, _Gen(), freecad_runner=fc, blender_runner=bl)("p", "", 9))
    checks = json.loads(sheet.with_name(sheet.stem + ".checks.json").read_text(encoding="utf-8"))
    assert checks["major_parts"] == 17 and structural_issues(checks)      # the gate fails a 17-piece part



def test_make_cad_generate_feeds_the_last_error_to_the_codegen(tmp_path, monkeypatch):
    # the loop no longer threads failures into the prompt, so the CAD generator carries its own last error
    import pytest as _pytest
    gen = _Gen("box = 1")
    calls = {"n": 0}

    def fc(tmpl, params, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("'Base.Matrix' object has no attribute 'rotate'")
        stl = Path(params["out_dir"]) / "m.stl"; stl.write_text("stl"); return {"outputs": [str(stl)]}
    _, bl = _ok_runners(tmp_path)
    monkeypatch.setattr(CG.montage, "contact_sheet", lambda paths, out, **k: Path(out).write_text("s") or Path(out))
    monkeypatch.setattr(CG, "route_output", lambda root, brand, src, mode, seed, **kw: Path(src))
    g = CG.make_cad_generate(_args(), tmp_path, gen, freecad_runner=fc, blender_runner=bl)
    with _pytest.raises(RuntimeError):
        g("P0", "", 1)
    g("P1", "", 2)
    fb = gen.calls[1][1]
    assert fb.startswith("P1") and "The previous script failed" in fb and "Matrix" in fb



@pytest.mark.parametrize("bad", ["g = make.__globals__", "x = ().__class__.__mro__[1].__subclasses__()",
                                 "b = __builtins__", "f = sys._getframe().f_back.f_globals",
                                 "def f(): pass\nf.__code__"])
def test_assert_safe_rejects_introspection_escapes(bad):
    # a restricted script reached the runner's globals (os, the real import) via f.__globals__ (2026-10)
    with pytest.raises(RuntimeError, match="rejected"):
        CG._assert_safe(bad)


def test_assert_safe_allows_ordinary_modelling_code():
    CG._assert_safe("class Bracket:\n    def __init__(self):\n        self.w = 40\n"
                    "if __name__ == '__chimera_cad__':\n    RESULT = [Part.makeBox(40, 20, 5)]\n")



def test_the_codegen_model_leaves_the_gpu_before_blender_renders(tmp_path, monkeypatch):
    # Blender (and a ComfyUI judge) can't see a resident Ollama model's memory on Windows
    log = []

    class _Client:
        def release(self):
            log.append("release")

    gen = _Gen("box = 1")
    gen.client = _Client()
    fc, _ = _ok_runners(tmp_path)

    def bl(tmpl, params, **kw):
        log.append("blender")
        outs = []
        for i in range(4):
            p = Path(params["out_dir"]) / f"v{i}.png"; p.write_text("p"); outs.append(str(p))
        return {"outputs": outs}
    monkeypatch.setattr(CG.montage, "contact_sheet", lambda paths, out, **k: Path(out).write_text("s") or Path(out))
    monkeypatch.setattr(CG, "route_output", lambda root, brand, src, mode, seed, **kw: Path(src))
    CG.make_cad_generate(_args(), tmp_path, gen, freecad_runner=fc, blender_runner=bl)("p", "", 1)
    assert log == ["release", "blender"]


def test_a_codegen_model_that_will_not_unload_stops_the_iteration_before_blender(tmp_path, monkeypatch):
    # the 27B code-gen is the biggest model in any loop; rendering beside it is the PC-freeze path
    class _Stuck:
        model = "qwen3.8:27b"
        def release(self): return False
        def resident(self): return True

    gen = _Gen("box = 1")
    gen.client = _Stuck()
    fc, ok_bl = _ok_runners(tmp_path)
    rendered = []
    g = CG.make_cad_generate(_args(), tmp_path, gen, freecad_runner=fc,
                             blender_runner=lambda *a, **k: rendered.append(1) or ok_bl(*a, **k))
    with pytest.raises(CG.LLMError, match="still loaded in Ollama"):
        g("p", "", 1)
    assert rendered == []
    # the script didn't fail, so the next revision isn't told it did (it was, as "The previous script failed")
    gen.client = None
    monkeypatch.setattr(CG.montage, "contact_sheet", lambda paths, out, **k: Path(out).write_text("s") or Path(out))
    monkeypatch.setattr(CG, "route_output", lambda root, brand, src, mode, seed, **kw: Path(src))
    g("P1", "", 2)
    assert "still loaded" not in (gen.calls[-1][1] or "") and "previous script failed" not in (gen.calls[-1][1] or "")



def test_a_repeated_seed_gets_its_own_files(tmp_path, monkeypatch):
    fc, bl = _ok_runners(tmp_path)
    monkeypatch.setattr(CG.montage, "contact_sheet", lambda paths, out, **k: Path(out).write_text("s") or Path(out))
    seen = []
    monkeypatch.setattr(CG, "route_output", lambda root, brand, src, mode, seed, **kw: seen.append(seed) or Path(src))
    g = CG.make_cad_generate(_args(), tmp_path, _Gen(), freecad_runner=fc, blender_runner=bl)
    g("p", "", 7)
    g("p", "", 7)
    assert seen == [7, 7, "7_2", "7_2"]          # sheet + STL per pass; the second pass doesn't replace the first


def test_a_codegen_llm_failure_is_not_fed_back_as_a_script_error(tmp_path, monkeypatch):
    # "the GPU has no room" isn't the script's fault; telling code-gen it was sent it chasing it
    from scripts.agent.llm import LLMError
    fc, bl = _ok_runners(tmp_path)
    monkeypatch.setattr(CG.montage, "contact_sheet", lambda paths, out, **k: Path(out).write_text("s") or Path(out))
    monkeypatch.setattr(CG, "route_output", lambda root, brand, src, mode, seed, **kw: Path(src))

    class _Flaky(_Gen):
        def generate_script(self, brief, fix_feedback=None):
            if not self.calls:
                self.calls.append((brief, fix_feedback))
                raise LLMError("not loading the model: the GPU has no room")
            return super().generate_script(brief, fix_feedback)
    gen = _Flaky()
    g = CG.make_cad_generate(_args(), tmp_path, gen, freecad_runner=fc, blender_runner=bl)
    with pytest.raises(LLMError):
        g("P0", "", 1)
    g("P1", "", 2)
    assert gen.calls[1] == ("a coffee mug", None)


@pytest.mark.parametrize("ok", ["socket_depth = 12", "sockets = 6", "# a ball-and-socket joint\nbox = 1",
                                "requests_per_tray = 4", "hex_socket = Part.makeCylinder(3, 5)",
                                "socket = Part.makeCylinder(5, 10)\nsocket.translate(App.Vector(1, 0, 0))",
                                "# dims from http://example.com\nbox = 1", "# see socket.\nbox = 1"])
def test_assert_safe_allows_names_that_merely_contain_a_module_word(ok):
    # a 'hex socket organizer' brief failed every iteration on socket_depth / '# ball-and-socket', and a shape
    # named `socket` isn't the module without its import
    CG._assert_safe(ok)


@pytest.mark.parametrize("bad", ["import socket", "from socket import socket", "import socket as s",
                                 "import urllib.request", "box = 1\n  from subprocess import run",
                                 "import http.client"])
def test_assert_safe_still_rejects_the_modules_themselves(bad):
    with pytest.raises(RuntimeError, match="disallowed"):
        CG._assert_safe(bad)


def test_the_cad_loop_ignores_a_forged_manifest(tmp_path, monkeypatch):
    # the LLM-written script shares stdout with the manifest: one printing its own manifest could name any file
    outside = tmp_path / "secret.stl"
    outside.write_text("x")

    def fc(tmpl, params, **kw):
        return {"outputs": [str(outside)]}
    _, bl = _ok_runners(tmp_path)
    monkeypatch.setattr(CG, "route_output", lambda *a, **k: pytest.fail("nothing may be routed"))
    g = CG.make_cad_generate(_args(), tmp_path, _Gen(), freecad_runner=fc, blender_runner=bl)
    with pytest.raises(RuntimeError, match="outside its folder"):
        g("p", "", 1)
    assert outside.exists()



@pytest.mark.parametrize("bad", ["eval('1')", "exec('x = 1')", "getattr(Part, 'x')", "b = len.__self__",
                                 "os.popen('x')", "os.remove('x')", "os.startfile('x')"])
def test_each_pre_filter_rule_rejects_on_its_own(bad):
    # each used to be caught only by another rule in the same test string
    with pytest.raises(RuntimeError, match="disallowed"):
        CG._assert_safe(bad)

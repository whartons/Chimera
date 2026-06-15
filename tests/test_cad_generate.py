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

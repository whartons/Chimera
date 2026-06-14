import argparse, pytest
from pathlib import Path
import scripts.agent.cad_generate as CG


class _Gen:
    def __init__(self, script="box = 1"):
        self.script = script; self.calls = []

    def generate_script(self, brief, fix_feedback=None):
        self.calls.append((brief, fix_feedback)); return self.script


def _args(**kw):
    base = dict(brand=None, samples=24, res=[512, 512], freecad_bin=None, blender_bin=None,
                freecad_timeout=None, blender_timeout=None)
    base.update(kw); return argparse.Namespace(**base)


def test_make_cad_generate_pipeline(tmp_path, monkeypatch):
    gen = _Gen("box = 1")

    def fc_runner(tmpl, params, **kw):
        assert "script_exec.py" in str(tmpl) and params["formats"] == ["stl"]
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
    sheet = g("a coffee mug", "", 5)
    assert gen.calls == [("a coffee mug", None)]      # pos passed as the brief
    assert Path(sheet).suffix == ".png" and ".stl" in routed   # sheet returned + STL routed
    assert Path(sheet).with_name(Path(sheet).stem + ".cad.py").read_text() == "box = 1"   # script saved


def test_make_cad_generate_rejects_unsafe_script(tmp_path):
    # the autonomous loop execs LLM-authored scripts -> a script reaching for shell/network/delete
    # is rejected before it's written or run
    for bad in ("import subprocess\nbox=1", "import os\nos.system('x')\n", "import shutil\nshutil.rmtree('/')",
                "import socket\n", "import requests\n", "__import__('os')\n"):
        g = CG.make_cad_generate(_args(), tmp_path, _Gen(bad),
                                 freecad_runner=lambda t, p, **k: {"outputs": ["x.stl"]},
                                 blender_runner=lambda t, p, **k: {"outputs": []})
        with pytest.raises(RuntimeError, match="disallowed"):
            g("x", "", 1)


def test_assert_safe_allows_normal_modelling():
    CG._assert_safe("import FreeCAD as App\nimport Part\nimport os\np=os.path.join('a','b')\n"
                    "box = Part.makeBox(10,10,10)\ndoc.addObject('Part::Feature','B').Shape = box")


def test_make_cad_generate_no_stl_raises(tmp_path):
    g = CG.make_cad_generate(_args(), tmp_path, _Gen(),
                             freecad_runner=lambda t, p, **k: {"outputs": []},
                             blender_runner=lambda t, p, **k: {"outputs": []})
    with pytest.raises(RuntimeError, match="no STL"):
        g("x", "", 1)

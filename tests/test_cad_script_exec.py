"""workflows/templates/freecad/script_exec.py runs inside FreeCADCmd; exercise its script namespace with stub
FreeCAD modules so the sandbox contract is tested without FreeCAD installed."""
from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "workflows" / "templates" / "freecad" / "script_exec.py"


class _Shape:  # stands in for Part.Shape
    pass


def _run(monkeypatch, tmp_path, script, *, restrict, objects=()):
    fc = types.ModuleType("FreeCAD")
    fc.Vector = lambda *a: a

    class _Doc:
        Name = "chimera_cad"
        Objects: list = list(objects)

        def recompute(self):
            pass

        def addObject(self, kind, name):
            return types.SimpleNamespace(Name=name, Shape=None, isDerivedFrom=lambda t: True)

    fc.newDocument = lambda name: _Doc()
    fc.setActiveDocument = lambda name: None
    part = types.ModuleType("Part")
    part.Shape = _Shape
    mesh = types.ModuleType("Mesh")
    mesh.Mesh = type("Mesh", (), {})
    exported = []
    common = types.ModuleType("_common")
    sp = tmp_path / "model.py"
    sp.write_text(script, encoding="utf-8")
    common.args = lambda: {"script": str(sp), "out_dir": str(tmp_path), "stem": "m", "formats": ["stl"],
                           "restrict": restrict}
    common.export_shapes = lambda objs, out_dir, stem, formats: exported.extend(objs) or ["m.stl"]
    common.emit = lambda manifest: None
    for name, mod in (("FreeCAD", fc), ("Part", part), ("Mesh", mesh), ("_common", common)):
        monkeypatch.setitem(sys.modules, name, mod)
    runpy.run_path(str(TEMPLATE), run_name="__main__")
    return fc, exported


@pytest.mark.parametrize("restrict", [True, False])
def test_import_app_resolves_to_freecad_in_both_modes(monkeypatch, tmp_path, restrict):
    # FreeCAD 1.1 ships an unrelated top-level `App` namespace package (no Vector); a script's own
    # `import App` must get FreeCAD, the alias the namespace promises (live 2026-10 CAD-loop failures).
    script = ("import App\nfrom App import Vector\nimport App as A\n"
              "assert A is FreeCAD and Vector is FreeCAD.Vector and App.Vector(1, 2, 3) == (1, 2, 3)\n"
              "RESULT = [Part.Shape()]\n")
    _, exported = _run(monkeypatch, tmp_path, script, restrict=restrict)
    assert len(exported) == 1 and exported[0].Name == "ChimeraShape"


def test_restricted_scripts_still_cannot_import_arbitrary_modules(monkeypatch, tmp_path):
    with pytest.raises(ImportError, match="may not import 'os'"):
        _run(monkeypatch, tmp_path, "import os\nRESULT = [Part.Shape()]\n", restrict=True)



def test_restricted_scripts_can_define_classes(monkeypatch, tmp_path):
    script = ("class Fin:\n    def __init__(self, h):\n        self.h = h\n"
              "RESULT = [Part.Shape()] if Fin(3).h == 3 else []\n")
    _, exported = _run(monkeypatch, tmp_path, script, restrict=True)
    assert len(exported) == 1


def _features(spec):
    """Stub doc objects from {name: (TypeId, bases, has_shape, uses)}: InList is filled in from `uses`."""
    objs = {}
    for name, (type_id, bases, has_shape, _) in spec.items():
        kinds = {type_id, *bases}
        objs[name] = types.SimpleNamespace(Name=name, TypeId=type_id, Shape=object() if has_shape else None,
                                           InList=[], isDerivedFrom=lambda t, k=kinds: t in k)
    for name, (*_, uses) in spec.items():
        for used in uses:
            objs[used].InList.append(objs[name])
    return list(objs.values())


_PART = ("Part::Feature",)
_SKETCH = ("Sketcher::SketchObject", ("Part::Part2DObject", "Part::Feature"), True, ())


@pytest.mark.parametrize("spec, want", [
    # a box minus a cylinder exported the uncut box + the cylinder + the cut: the hole vanished, ~2.5x the volume
    ({"Box": ("Part::Box", _PART, True, ()), "Hole": ("Part::Cylinder", _PART, True, ()),
      "Cut": ("Part::Cut", _PART, True, ("Box", "Hole"))}, ["Cut"]),
    ({"Sketch": _SKETCH, "Pad": ("PartDesign::Pad", _PART, True, ("Sketch",)),
      "Body": ("PartDesign::Body", _PART, True, ("Pad",))}, ["Body"]),
    ({"Sketch": _SKETCH, "Box": ("Part::Box", _PART, True, ())}, ["Box"]),           # a loose sketch is no solid
    ({"A": ("Part::Box", _PART, True, ()), "B": ("Part::Sphere", _PART, True, ())}, ["A", "B"]),
    # a group holds no geometry of its own, so what it contains is still a leaf
    ({"Group": ("App::DocumentObjectGroup", (), False, ("Box",)), "Box": ("Part::Box", _PART, True, ())}, ["Box"]),
])
def test_without_result_only_the_finished_objects_are_exported(monkeypatch, tmp_path, spec, want):
    _, exported = _run(monkeypatch, tmp_path, "x = 1\n", restrict=False, objects=_features(spec))
    assert [o.Name for o in exported] == want

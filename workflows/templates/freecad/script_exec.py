"""script_exec: run an agent/user-authored FreeCAD Python script headless and export the geometry it
builds. The script runs in a namespace with `App`/`FreeCAD`, `Part`, `Mesh`, and an active `doc`; it
should build geometry as objects in `doc` (e.g. `o = doc.addObject('Part::Feature','X'); o.Shape = ...`)
or set a module global `RESULT = [objs]` (the entries may be raw Part shapes / Mesh objects — the runner
wraps those into doc objects). The runner exports those to step/stl/obj and emits the manifest, so the
script only owns the modelling. Params: {script, out_dir, stem, formats}.

This powers generative CAD self-correction (text -> agent-authored parametric script -> solid -> render ->
judge -> revise). The script is first-party/local/headless (no network) in an isolated FreeCADCmd process."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import FreeCAD as App
import Part
import Mesh
import _common as C

p = C.args()
doc = App.newDocument("chimera_cad")
App.setActiveDocument(doc.Name)

with open(p["script"], encoding="utf-8") as fh:
    src = fh.read()
ns = {"App": App, "FreeCAD": App, "Part": Part, "Mesh": Mesh, "doc": doc, "__name__": "__chimera_cad__"}

if p.get("restrict"):
    # Autonomous (LLM-authored) scripts run with restricted builtins + an import allowlist: no
    # open/eval/exec/compile/getattr/__import__-of-arbitrary-modules, so the python-level escape hatches
    # are closed. NOT a full sandbox (FreeCAD's own Part.export/doc.saveAs can still touch the filesystem),
    # but it raises the bar far past the host-side regex pre-filter. Human `cad --mode script` is trusted
    # and stays unrestricted.
    import builtins as _b
    _ALLOWED = {"App", "FreeCAD", "Part", "Mesh", "math", "Draft", "PartDesign", "BOPTools", "MeshPart"}
    _real_import = _b.__import__

    def _safe_import(name, *a, **k):
        if name.split(".")[0] not in _ALLOWED:
            raise ImportError(f"restricted CAD script may not import {name!r}")
        return _real_import(name, *a, **k)

    _SAFE = {n: getattr(_b, n) for n in (
        "abs", "min", "max", "round", "sum", "len", "range", "enumerate", "zip", "map", "filter",
        "sorted", "reversed", "list", "dict", "tuple", "set", "frozenset", "str", "int", "float",
        "bool", "complex", "print", "isinstance", "issubclass", "type", "repr", "format", "divmod",
        "pow", "any", "all", "ord", "chr", "hex", "oct", "bin", "iter", "next", "slice", "hash",
        "Exception", "ValueError", "TypeError", "RuntimeError", "ZeroDivisionError", "IndexError",
        "KeyError", "AttributeError", "ImportError") if hasattr(_b, n)}
    _SAFE["__import__"] = _safe_import
    ns["__builtins__"] = _SAFE

exec(compile(src, p["script"], "exec"), ns)
doc.recompute()

# objects to export: an explicit RESULT list, else every doc object carrying geometry
objs = ns.get("RESULT")
if not objs:
    objs = [o for o in doc.Objects
            if getattr(o, "Shape", None) is not None or o.isDerivedFrom("Mesh::Feature")]
if not objs:
    raise ValueError("script produced no exportable geometry — add Part/Mesh objects to `doc` "
                     "or set RESULT=[objs]")

# RESULT may hold raw Part shapes / Mesh objects (LLMs commonly write `RESULT = [shape]`); wrap them
# into doc objects so Part.export / Mesh.export (which take document objects) accept them.
_wrapped = []
for _o in objs:
    # Check raw shapes/meshes FIRST: a raw Part.Shape ALSO has isDerivedFrom, so testing that first
    # would mis-classify a bare shape as a doc object (and later o.Name would blow up).
    if isinstance(_o, Part.Shape):            # raw BREP shape -> wrap in a Part::Feature
        _f = doc.addObject("Part::Feature", "ChimeraShape"); _f.Shape = _o
        _wrapped.append(_f)
    elif isinstance(_o, Mesh.Mesh):           # raw mesh -> wrap in a Mesh::Feature
        _f = doc.addObject("Mesh::Feature", "ChimeraMesh"); _f.Mesh = _o
        _wrapped.append(_f)
    elif hasattr(_o, "isDerivedFrom"):        # already a DocumentObject (Part::/Mesh::Feature)
        _wrapped.append(_o)
    else:
        raise ValueError(f"RESULT entry {_o!r} is neither a doc object nor a Part/Mesh shape")
objs = _wrapped
doc.recompute()

# STEP is a BREP format: Part.export needs real Part shapes. A Mesh::Feature would fail (or emit
# garbage) inside Part.export, so reject the combo up front with a legible message (convert mode has
# an equivalent host-side guard; script geometry can only be known here, at runtime).
if any(str(f).lower() in ("step", "stp") for f in p["formats"]):
    not_brep = [o.Name for o in objs if getattr(o, "Shape", None) is None]
    if not_brep:
        raise ValueError("STEP export needs Part (BREP) geometry; these objects are not Part shapes: "
                         f"{not_brep}. Export stl/obj for mesh geometry, or build Part solids.")

outs = C.export_shapes(objs, p["out_dir"], p["stem"], p["formats"])
C.emit({"outputs": outs, "script": os.path.basename(p["script"]), "objects": len(objs)})

"""script_exec: run an agent/user-authored FreeCAD Python script headless and export the geometry it
builds. The script runs in a namespace with `App`/`FreeCAD`, `Part`, `Mesh`, and an active `doc`; it
should build geometry as objects in `doc` (e.g. `o = doc.addObject('Part::Feature','X'); o.Shape = ...`)
or set a module global `RESULT = [objs]`. The runner exports those to step/stl/obj and emits the manifest,
so the script only owns the modelling. Params: {script, out_dir, stem, formats}.

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

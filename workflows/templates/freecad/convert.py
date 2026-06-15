"""convert: import an existing CAD/mesh file and re-export to step/stl/obj. BREP family
(step/stp/iges/igs/brep) imports via Part.Shape().read; mesh family (stl/obj) via Mesh.Mesh.
The host (_validate_cad) already refuses the one impossible combo (mesh source -> STEP), so a
Mesh::Feature is never handed to Part.export. Params: {source, out_dir, stem, formats}."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import FreeCAD as App
import Part
import Mesh
import _common as C

p = C.args()
doc = App.newDocument("chimera_cad")
src = p["source"]
ext = os.path.splitext(src)[1].lower()
if ext in (".step", ".stp", ".iges", ".igs", ".brep"):
    shp = Part.Shape()
    shp.read(src)
    feat = doc.addObject("Part::Feature", "Imported")
    feat.Shape = shp
    solids = len(shp.Solids)
elif ext in (".stl", ".obj"):
    m = Mesh.Mesh(src)
    feat = doc.addObject("Mesh::Feature", "Imported")
    feat.Mesh = m
    solids = 0
else:
    raise ValueError("unsupported source extension: " + ext)
doc.recompute()
outs = C.export_shapes([feat], p["out_dir"], p["stem"], p["formats"])
C.emit({"outputs": outs, "source": os.path.basename(src), "solids": solids})

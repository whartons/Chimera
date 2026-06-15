"""primitive: build a parametric solid (box/cylinder/cone/sphere/tube) from params and export to
step/stl/obj. Params: {shape, length,width,height, radius,radius2,inner_radius, out_dir, stem, formats}.
Dimensions are millimetres. Run only inside `FreeCADCmd primitive.py <params.json>`."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import FreeCAD as App
import Part
import _common as C

p = C.args()
doc = App.newDocument("chimera_cad")
shape = p["shape"]
if shape == "box":
    s = Part.makeBox(p["length"], p["width"], p["height"])
elif shape == "cylinder":
    s = Part.makeCylinder(p["radius"], p["height"])
elif shape == "cone":
    s = Part.makeCone(p["radius"], p["radius2"], p["height"])
elif shape == "sphere":
    s = Part.makeSphere(p["radius"])
elif shape == "tube":
    s = Part.makeCylinder(p["radius"], p["height"]).cut(Part.makeCylinder(p["inner_radius"], p["height"]))
else:
    raise ValueError("unknown shape: " + str(shape))
feat = doc.addObject("Part::Feature", "Solid")
feat.Shape = s
doc.recompute()
outs = C.export_shapes([feat], p["out_dir"], p["stem"], p["formats"])
C.emit({"outputs": outs, "shape": shape, "solids": len(s.Solids)})

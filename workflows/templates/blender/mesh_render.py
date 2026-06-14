"""mesh_render: import a mesh -> studio look -> Cycles -> hero PNG (+ optional turntable MP4).
Params: {mesh, out_dir, stem, samples, res:[w,h], turntable:bool, frames:int}."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

p = C.args()
scn = C.reset_scene()
dev = C.enable_gpu(scn)
scn.cycles.samples = int(p["samples"])
scn.render.resolution_x, scn.render.resolution_y = int(p["res"][0]), int(p["res"][1])
obj = C.import_mesh(p["mesh"])
C.frame_object(scn, obj)

outputs = [C.render_still(scn, os.path.join(p["out_dir"], p["stem"] + "_hero.png"))]
if p.get("turntable"):
    outputs.append(C.render_turntable(scn, obj, p["out_dir"], p["stem"], int(p.get("frames", 72))))
C.emit({"outputs": outputs, "device": dev})

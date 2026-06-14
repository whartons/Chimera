"""render_views (Phase 4b auto-repaint input): import a mesh -> render a per-view DEPTH map at each of
N ring azimuths, for a depth-ControlNet. Depth is rendered via an emission "depth material"
(CameraData View-Z-Depth -> MapRange near=white/far=black -> Emission), so one Cycles sample is exact and
no compositor is needed (robust headless). Params: {mesh, out_dir, stem, azimuths, elevation, res,
samples}. Emits {outputs:[depth PNGs], azimuths}. The repaint backend feeds each depth + the concept
image (IPAdapter) to SDXL, then the corrected views go to _common.bake_multiview."""
import bpy, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C
import mathutils

p = C.args()
scn = C.reset_scene()
dev = C.enable_gpu(scn)
scn.cycles.samples = int(p.get("samples", 1))   # flat emission -> 1 sample is exact
res = p.get("res", [768, 768])
scn.render.resolution_x, scn.render.resolution_y = int(res[0]), int(res[1])
scn.world = bpy.data.worlds.new("W")
scn.world.use_nodes = True
scn.world.node_tree.nodes["Background"].inputs[1].default_value = 0.0   # black background = far

obj = C.import_mesh(p["mesh"])
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')

bbox = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
centre = sum(bbox, mathutils.Vector()) / 8.0
radius = max((v - centre).length for v in bbox) or 1.0
cam_dist = radius * 3.0   # _ring_camera places cameras at this distance

# depth material: View Z Depth -> MapRange (near=white, far=black) -> Emission
mat = bpy.data.materials.new("Depth")
mat.use_nodes = True
obj.data.materials.clear()
obj.data.materials.append(mat)
nt = mat.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputMaterial")
emit = nt.nodes.new("ShaderNodeEmission")
camd = nt.nodes.new("ShaderNodeCameraData")
mr = nt.nodes.new("ShaderNodeMapRange")
mr.inputs["From Min"].default_value = cam_dist - radius
mr.inputs["From Max"].default_value = cam_dist + radius
mr.inputs["To Min"].default_value = 1.0    # near -> white
mr.inputs["To Max"].default_value = 0.0    # far  -> black
mr.clamp = True
zsock = camd.outputs["View Z Depth"] if "View Z Depth" in camd.outputs else camd.outputs[1]
nt.links.new(zsock, mr.inputs["Value"])
nt.links.new(mr.outputs["Result"], emit.inputs["Color"])
nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

azimuths = [float(a) for a in p["azimuths"]]
elevation = float(p.get("elevation", 15.0))
depths = []
for i, az in enumerate(azimuths):
    cam_o, cam_d, _ = C._ring_camera(scn, centre, radius, az, elevation)
    scn.camera = cam_o
    depths.append(C.render_still(scn, os.path.join(p["out_dir"], f"{p['stem']}_depth{i}.png")))
    bpy.data.objects.remove(cam_o, do_unlink=True)
    bpy.data.cameras.remove(cam_d)

C.emit({"outputs": depths, "azimuths": azimuths, "device": dev})

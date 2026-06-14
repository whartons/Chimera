"""comfy_to_scene: place a ComfyUI image as an emissive backdrop behind a chrome focal object on a
reflective floor -> Cycles render. Params: {asset, out_dir, stem, samples, res:[w,h], seed}.
V1: image input + 'backdrop' placement only (plane/texture + video input are roadmap)."""
import bpy, sys, os, math, mathutils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

p = C.args()
scn = C.reset_scene()
dev = C.enable_gpu(scn)
scn.cycles.samples = int(p["samples"])
scn.cycles.seed = int(p.get("seed", 0))
scn.render.resolution_x, scn.render.resolution_y = int(p["res"][0]), int(p["res"][1])

img = bpy.data.images.load(p["asset"])
W, H = img.size
aspect = (W / H) if H else 1.0

C.floor(scn, rough=0.12)
# emissive backdrop textured with the concept image
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 6, 3.2))
bp = bpy.context.active_object
bp.rotation_euler = (math.radians(90), 0, 0)
bp.scale = (3.2 * aspect, 3.2, 1)
em = bpy.data.materials.new("Concept")
em.use_nodes = True
nt = em.node_tree
nt.nodes.clear()
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = img
emit = nt.nodes.new("ShaderNodeEmission")
emit.inputs["Strength"].default_value = 1.3
out = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
bp.data.materials.append(em)

# chrome focal object
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=1.3, location=(0, 1.0, 1.3))
bpy.ops.object.shade_smooth()
sm = bpy.data.materials.new("Chrome")
sm.use_nodes = True
sb = sm.node_tree.nodes["Principled BSDF"]
sb.inputs["Base Color"].default_value = (0.9, 0.9, 0.95, 1)
sb.inputs["Metallic"].default_value = 1.0
sb.inputs["Roughness"].default_value = 0.05
bpy.context.active_object.data.materials.append(sm)

C.studio(scn, world_strength=0.15)
cam = bpy.data.cameras.new("Cam")
cam.lens = 50
co = bpy.data.objects.new("Cam", cam)
scn.collection.objects.link(co)
scn.camera = co
co.location = (0, -7.5, 2.4)
d = mathutils.Vector((0, 2.0, 1.6)) - co.location
co.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

outputs = [C.render_still(scn, os.path.join(p["out_dir"], p["stem"] + "_scene.png"))]
C.emit({"outputs": outputs, "device": dev, "image_px": [W, H]})

"""mesh_finish: import an AI mesh -> clean -> optional voxel-remesh (watertight) -> decimate ->
optional scale-to-mm -> material (or emissive image projection) -> export STL/GLB (+ optional
hero render). Params: {mesh, out_dir, stem, samples, res:[w,h], target_tris, watertight:bool,
scale_mm:float|null, color: material|project, formats:[..], render_still:bool, asset?}."""
import bpy, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

p = C.args()
scn = C.reset_scene()
dev = C.enable_gpu(scn)
scn.cycles.samples = int(p["samples"])
scn.cycles.seed = int(p.get("seed", 0))
scn.render.resolution_x, scn.render.resolution_y = int(p["res"][0]), int(p["res"][1])
obj = C.import_mesh(p["mesh"])
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

# clean: merge doubles + recalc normals
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=0.0001)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode='OBJECT')

if p.get("watertight"):
    rm = obj.modifiers.new("Remesh", 'REMESH')
    rm.mode = 'VOXEL'
    rm.voxel_size = max(obj.dimensions) / 256.0
    bpy.ops.object.modifier_apply(modifier=rm.name)

# decimate to target tri budget
tris = len(obj.data.polygons)
target = int(p.get("target_tris", 200000))
if tris > target:
    dec = obj.modifiers.new("Decimate", 'DECIMATE')
    dec.ratio = max(0.01, target / tris)
    bpy.ops.object.modifier_apply(modifier=dec.name)

# scale longest dimension to scale_mm (Blender unit = 1 m)
if p.get("scale_mm"):
    longest = max(obj.dimensions) or 1.0
    factor = (float(p["scale_mm"]) / 1000.0) / longest
    obj.scale = (factor, factor, factor)
    bpy.ops.object.transform_apply(scale=True)

bpy.ops.object.shade_smooth()

# color
obj.data.materials.clear()
if p.get("color") == "project" and p.get("asset"):
    img = bpy.data.images.load(p["asset"])
    mat = bpy.data.materials.new("Projected")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
else:
    mat = bpy.data.materials.new("Clay")
    mat.use_nodes = True
    cb = mat.node_tree.nodes["Principled BSDF"]
    cb.inputs["Base Color"].default_value = (0.82, 0.45, 0.32, 1)
    cb.inputs["Roughness"].default_value = 0.4
    if "Subsurface Weight" in cb.inputs:
        cb.inputs["Subsurface Weight"].default_value = 0.12
obj.data.materials.append(mat)

outputs = []
fmts = p.get("formats", ["stl", "glb"])
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
if "stl" in fmts:
    stl = os.path.join(p["out_dir"], p["stem"] + ".stl")
    bpy.ops.wm.stl_export(filepath=stl, export_selected_objects=True)
    outputs.append(stl)
if "glb" in fmts:
    glb = os.path.join(p["out_dir"], p["stem"] + ".glb")
    bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB', use_selection=True)
    outputs.append(glb)

if p.get("render_still", True):
    C.frame_object(scn, obj)
    outputs.append(C.render_still(scn, os.path.join(p["out_dir"], p["stem"] + "_hero.png")))

C.emit({"outputs": outputs, "device": dev,
        "tris_final": len(obj.data.polygons), "watertight": bool(p.get("watertight"))})

"""mesh_finalize (Phase 4b): import a mesh -> all-around albedo bake from N corrected views
(_common.bake_multiview) -> export a textured GLB -> render orbit verification stills. Params:
{mesh, view_images:[...], azimuths:[...], out_dir, stem, samples, res:[w,h], seed, elevation,
back_fill, palette, texture_res}. The corrected views are supplied by the caller (an artist's paints,
or — roadmap — the ComfyUI depth-ControlNet+IPAdapter repaint backend). Cycles only."""
import bpy, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

p = C.args()
scn = C.reset_scene()
dev = C.enable_gpu(scn)
scn.cycles.samples = int(p.get("samples", 48))
scn.cycles.seed = int(p.get("seed", 0))
scn.render.resolution_x, scn.render.resolution_y = int(p["res"][0]), int(p["res"][1])

obj = C.import_mesh(p["mesh"])
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
C.frame_object(scn, obj)        # studio camera + lights for the verification render

C.bake_multiview(obj, scn, [str(v) for v in p["view_images"]],
                 azimuths=[float(a) for a in p["azimuths"]],
                 elevation_deg=float(p.get("elevation", 15.0)),
                 back_fill=p.get("back_fill", "palette"), palette=p.get("palette") or [],
                 res=int(p.get("texture_res", 1024)))

glb = os.path.join(p["out_dir"], p["stem"] + "_textured.glb")
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB', use_selection=True)

# orbit verification stills (rotate the object about Z; origin is centred so it stays framed)
views = 4
obj.rotation_mode = 'XYZ'
base = obj.rotation_euler[2]
stills = []
for i in range(views):
    obj.rotation_euler[2] = base + math.radians(360.0 * i / views)
    bpy.context.view_layer.update()
    stills.append(C.render_still(scn, os.path.join(p["out_dir"], f"{p['stem']}_v{i}.png")))
obj.rotation_euler[2] = base

C.emit({"outputs": stills, "textured_glb": glb, "views": len(p["view_images"]), "device": dev})

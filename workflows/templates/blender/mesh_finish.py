"""mesh_finish: import an AI mesh -> clean -> optional voxel-remesh (watertight) -> decimate ->
optional scale-to-mm -> material (or emissive image projection) -> export STL/GLB (+ optional
hero render). Params: {mesh, out_dir, stem, samples, res:[w,h], target_tris, watertight:bool,
solid:bool, scale_mm:float|null, color: auto|material|project|keep, formats:[..], render_still:bool,
asset?}. auto keeps a textured mesh's own materials (a TRELLIS.2 PBR GLB) and clays an untextured one.
solid = the mesh is already one solid from the host's solidify step (`render --mode finish --solid`):
no voxel remesh, keep only its largest piece. STL is written in millimetres, what every slicer assumes:
stl_scale (mm per Blender unit, from the host) is 1000 for metres and 1 for an unscaled STL/OBJ input that's
already mm. GLB stays in metres per the glTF spec."""
import bpy, bmesh, mathutils, sys, os
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


def _textured(o):
    """True when the imported mesh carries image textures (e.g. a TRELLIS.2 PBR GLB)."""
    return any(m and m.use_nodes and any(n.type == 'TEX_IMAGE' and n.image for n in m.node_tree.nodes)
               for m in o.data.materials)


# color: `auto` keeps a textured mesh's own materials; replacing them with clay erased TRELLIS.2's baked
# PBR textures (2026-10). A voxel remesh drops UVs, so --watertight always clays (the host rejects keep).
color = p.get("color") or "auto"
if color == "auto":
    color = "keep" if _textured(obj) and not p.get("watertight") else "material"
keep = color == "keep"

if not keep:
    # clean a raw AI mesh: merge doubles + recalc normals. A textured asset keeps its own topology and
    # normals: rewriting them broke its baked normal map (a shattered, faceted render)
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

solid = bool(p.get("solid"))
dropped = 0
if solid:
    # keep the largest connected piece: marching cubes can leave specks the slicer would print as debris
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    seen, groups = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, members = [v], []
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            members.append(cur)
            for e in cur.link_edges:
                o = e.other_vert(cur)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
        groups.append(members)
    groups.sort(key=len, reverse=True)
    kill = [v for g in groups[1:] for v in g]
    dropped = len(groups) - 1
    if kill:
        bmesh.ops.delete(bm, geom=kill, context='VERTS')
    bm.to_mesh(obj.data)
    bm.free()

# decimate to target tri budget
tris = len(obj.data.polygons)
target = int(p.get("target_tris", 200000))
if tris > target:
    dec = obj.modifiers.new("Decimate", 'DECIMATE')
    dec.ratio = max(0.01, target / tris)
    bpy.ops.object.modifier_apply(modifier=dec.name)

repaired = 0
if solid or p.get("watertight"):
    # decimation can pinch a few edges into non-manifold spots, which slicers reject: cut the faces
    # around each one out and re-fill the hole
    for _ in range(4):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bad = [e for e in bm.edges if not e.is_manifold]
        if not bad:
            bm.free()
            break
        repaired += len(bad)
        kill = {f for e in bad for v in e.verts for f in v.link_faces}
        bmesh.ops.delete(bm, geom=list(kill), context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if len(e.link_faces) == 1], sides=0)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        bm.free()

# scale longest dimension to scale_mm (Blender unit = 1 m)
if p.get("scale_mm"):
    longest = max(obj.dimensions) or 1.0
    factor = (float(p["scale_mm"]) / 1000.0) / longest
    obj.scale = (factor, factor, factor)
    bpy.ops.object.transform_apply(scale=True)
    # scaling about the origin left the model in the air (0.39 m up for a GLB at --scale-mm 228.6, 114 m for a
    # mm STL), away from the floor and the light rig, which sit at the origin: a dim or black hero render, and
    # an STL that doesn't start at z=0 (2026-10). Bake the transform, then centre it on the floor again.
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    obj.data.transform(mathutils.Matrix.Translation((-(min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2,
                                                     -min(zs))))
    obj.data.update()
    bpy.context.view_layer.update()

if keep:
    for img in bpy.data.images:   # the textures ride in the GLB: cap 4096 bakes at 2048
        w, h = img.size
        if max(w, h) > 2048:
            img.scale(int(w * 2048 / max(w, h)), int(h * 2048 / max(w, h)))
else:
    bpy.ops.object.shade_smooth()
    obj.data.materials.clear()
    if color == "project" and p.get("asset"):
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
    # STL has no units and slicers read it as mm. The host sends mm per Blender unit: 1000 for metres (glTF, or
    # after --scale-mm; raw units loaded --scale-mm 60 as 0.06 mm), 1 for an unscaled STL/OBJ that's already mm
    bpy.ops.wm.stl_export(filepath=stl, export_selected_objects=True, global_scale=float(p.get("stl_scale", 1000.0)))
    outputs.append(stl)
if "glb" in fmts:
    glb = os.path.join(p["out_dir"], p["stem"] + ".glb")
    kw = dict(filepath=glb, export_format='GLB', use_selection=True)
    if color == "keep":   # PNG PBR textures alone made a TRELLIS.2 GLB ~37 MB; JPEG at q90 is ~1/8 of that
        kw["export_image_format"] = "JPEG"
        try:
            bpy.ops.export_scene.gltf(**kw, export_image_quality=90)
        except TypeError:          # older exporters name it export_jpeg_quality
            bpy.ops.export_scene.gltf(**kw, export_jpeg_quality=90)
    else:
        bpy.ops.export_scene.gltf(**kw)
    outputs.append(glb)

if p.get("render_still", True):
    C.frame_object(scn, obj)
    outputs.append(C.render_still(scn, os.path.join(p["out_dir"], p["stem"] + "_hero.png")))

C.emit({"outputs": outputs, "device": dev, "color": color,
        "tris_final": len(obj.data.polygons), "watertight": bool(p.get("watertight")), "solid": solid,
        "pieces_dropped": dropped, "repaired_edges": repaired})

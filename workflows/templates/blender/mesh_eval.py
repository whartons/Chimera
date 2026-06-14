"""mesh_eval: import a mesh -> studio -> render N orbit stills -> compute bmesh geometry checks ->
emit {outputs:[stills], checks:{...}}. Params: {mesh,out_dir,stem,samples,res:[w,h],seed,views}.
Phase 3: the judged artifact is a contact sheet of the stills; the checks catch defects a VLM can't
see (non-manifold, open/holey, disconnected, degenerate). Cycles only (headless EEVEE is Linux-only)."""
import bpy, sys, os, math, bmesh
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

p = C.args()
scn = C.reset_scene()
dev = C.enable_gpu(scn)
scn.cycles.samples = int(p["samples"])
scn.cycles.seed = int(p.get("seed", 0))
scn.render.resolution_x, scn.render.resolution_y = int(p["res"][0]), int(p["res"][1])

obj = C.import_mesh(p["mesh"])
# centre the origin on the geometry bounds so Z-rotation orbits in place (stays framed/on floor)
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
C.frame_object(scn, obj)

# --- geometry checks (bmesh on the imported mesh data) ---
bm = bmesh.new()
bm.from_mesh(obj.data)
# glTF/GLB (incl. Hunyuan3D output) splits vertices along UV seams / normals, so the imported
# mesh is a triangle-soup of coincident-but-separate verts — every edge reads as a boundary and
# every vert as its own component. Weld the exact-coincident duplicates first so the topology
# checks reflect the real surface (same reason mesh_finish runs remove_doubles).
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-4)
non_manifold = sum(1 for e in bm.edges if len(e.link_faces) > 2)   # >2 faces = non-manifold junction
open_edges = sum(1 for e in bm.edges if len(e.link_faces) < 2)     # <2 faces = boundary/hole


def _loose_parts(bmesh_obj):
    """Connected-component count via a vertex walk over link_edges."""
    seen, parts = set(), 0
    for v in bmesh_obj.verts:
        if v.index in seen:
            continue
        parts += 1
        stack = [v]
        while stack:
            cur = stack.pop()
            if cur.index in seen:
                continue
            seen.add(cur.index)
            for e in cur.link_edges:
                ov = e.other_vert(cur)
                if ov is not None and ov.index not in seen:
                    stack.append(ov)
    return parts


bm.verts.index_update()
loose_parts = _loose_parts(bm)
bounds_ok = all(d > 1e-4 for d in obj.dimensions)
bmesh.ops.triangulate(bm, faces=bm.faces[:])   # do last — mutates faces
tri_count = len(bm.faces)
bm.free()

checks = {"non_manifold_edges": int(non_manifold), "open_edges": int(open_edges),
          "loose_parts": int(loose_parts), "tri_count": int(tri_count),
          "bounds_ok": bool(bounds_ok)}

# --- Phase 4a: optional front-projection albedo bake (colors the stills + exports a textured GLB) ---
textured = False
textured_glb = None
if p.get("texture") and p.get("asset"):
    try:
        C.bake_albedo(obj, scn, p["asset"], palette=p.get("palette") or [],
                      back_fill=p.get("back_fill", "palette"), res=int(p.get("texture_res", 1024)))
        glb = os.path.join(p["out_dir"], p["stem"] + "_textured.glb")
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB', use_selection=True)
        textured, textured_glb = True, glb
    except Exception as exc:  # bake is new bpy surface — fall back to grey clay, report it
        print("mesh_eval: bake_albedo failed, falling back to grey clay:", exc, file=sys.stderr)

# --- N orbit stills (rotate the object about Z; origin is centred so it stays framed) ---
views = int(p.get("views", 4))
obj.rotation_mode = 'XYZ'
base = obj.rotation_euler[2]
stills = []
for i in range(views):
    obj.rotation_euler[2] = base + math.radians(360.0 * i / views)
    bpy.context.view_layer.update()
    stills.append(C.render_still(scn, os.path.join(p["out_dir"], f"{p['stem']}_v{i}.png")))
obj.rotation_euler[2] = base

C.emit({"outputs": stills, "checks": checks, "device": dev,
        "textured": textured, "textured_glb": textured_glb})

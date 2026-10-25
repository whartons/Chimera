"""mesh_raw_mm: step 1 of `render --mode finish --solid`. Import a mesh, scale its longest side to `size_mm`
with 1 Blender unit = 1 mm, centre it on the plate, weld the vertices glTF splits along UV seams, cap small holes
(fans; they only need to block leaks for the host's solidify step), and write a raw binary STL in mm.
Params: {mesh, out, size_mm, cap_frac?}. Holes wider than cap_frac * size_mm (default 0.1) stay open."""
import bmesh, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C
import bpy

p = C.args()
C.reset_scene()
obj = C.import_mesh(p["mesh"])
bm = bmesh.new()
bm.from_mesh(obj.data)
bm.transform(obj.matrix_world)
pts = [v.co for v in bm.verts]
lo = [min(c[k] for c in pts) for k in range(3)]
hi = [max(c[k] for c in pts) for k in range(3)]
s = float(p["size_mm"]) / (max(hi[k] - lo[k] for k in range(3)) or 1.0)
bmesh.ops.scale(bm, vec=(s, s, s), verts=bm.verts)
bmesh.ops.translate(bm, vec=(-(hi[0] + lo[0]) / 2 * s, -(hi[1] + lo[1]) / 2 * s, -lo[2] * s), verts=bm.verts)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.02)
bmesh.ops.triangulate(bm, faces=bm.faces)

cap_max = float(p.get("cap_frac", 0.1)) * float(p["size_mm"])
seen, loops = set(), []
for e in [e for e in bm.edges if len(e.link_faces) == 1]:
    if e.index in seen:
        continue
    stack, comp = [e], []
    seen.add(e.index)
    while stack:
        cur = stack.pop()
        comp.append(cur)
        for v in cur.verts:
            for e2 in v.link_edges:
                if len(e2.link_faces) == 1 and e2.index not in seen:
                    seen.add(e2.index)
                    stack.append(e2)
    loops.append(comp)
capped = 0
for comp in loops:
    vs = [v.co.copy() for e in comp for v in e.verts]
    if max(max(c[k] for c in vs) - min(c[k] for c in vs) for k in range(3)) > cap_max:
        continue
    centre = bm.verts.new(sum(vs, vs[0] * 0) / len(vs))
    for e in comp:
        a, b = e.verts
        try:
            bm.faces.new((centre, b, a))
        except ValueError:
            pass
    capped += 1
obj.matrix_world.identity()
bm.to_mesh(obj.data)
bm.free()
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.wm.stl_export(filepath=p["out"], export_selected_objects=True, ascii_format=False, global_scale=1.0)
C.emit({"outputs": [p["out"]], "tris": len(obj.data.polygons), "holes": len(loops), "capped": capped})

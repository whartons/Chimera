"""Shared bpy helpers for Chimera's headless Blender templates. Each template does:
    import _common as C; p = C.args(); ... ; C.emit({"outputs": [...], "blender_version": ...})
Run only inside `blender --background --python <template> -- <json>`."""
import bpy, bmesh, sys, os, json, math, glob, mathutils


def args() -> dict:
    """Parse the JSON params blob passed after `--`."""
    argv = sys.argv
    raw = argv[argv.index("--") + 1] if "--" in argv else "{}"
    return json.loads(raw)


def emit(manifest: dict):
    """Print the one-line result manifest the host runner parses."""
    manifest.setdefault("blender_version", bpy.app.version_string)
    print("@@CHIMERA_MANIFEST@@ " + json.dumps(manifest))


def reset_scene(name="ChimeraRender"):
    if name in bpy.data.scenes:
        bpy.data.scenes.remove(bpy.data.scenes[name])
    scn = bpy.data.scenes.new(name)
    bpy.context.window.scene = scn
    return scn


def enable_gpu(scn):
    """Cycles + GPU (OptiX/CUDA) with CPU fallback. Proven on the RTX 5090 / Blender 5.1."""
    scn.render.engine = 'CYCLES'
    label = "CPU"
    try:
        cp = bpy.context.preferences.addons['cycles'].preferences
        for dt in ('OPTIX', 'CUDA'):
            try:
                cp.compute_device_type = dt
                cp.get_devices()
                if any(d.type == dt for d in cp.devices):
                    break
            except Exception:
                pass
        for d in cp.devices:
            d.use = True
        scn.cycles.device = 'GPU'
        label = next((d.name for d in cp.devices if d.use and d.type != 'CPU'), "GPU")
    except Exception:
        scn.cycles.device = 'CPU'
    return label


def studio(scn, world_strength=0.25):
    scn.world = bpy.data.worlds.new("W")
    scn.world.use_nodes = True
    scn.world.node_tree.nodes["Background"].inputs[1].default_value = world_strength
    for nm, e, loc, rot in (("Key", 1400, (-5, -5, 8), (45, 0, -40)),
                            ("Fill", 500, (5, -3, 4), (60, 0, 55)),
                            ("Rim", 900, (3, 6, 6), (60, 0, 150))):
        lt = bpy.data.lights.new(nm, 'AREA')
        lt.energy = e
        lt.size = 5
        o = bpy.data.objects.new(nm, lt)
        scn.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = tuple(math.radians(a) for a in rot)


def floor(scn, rough=0.4):
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
    m = bpy.data.materials.new("Floor")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.03, 0.03, 0.04, 1)
    b.inputs["Roughness"].default_value = rough
    bpy.context.active_object.data.materials.append(m)


def import_mesh(path):
    """Import a mesh by extension; return a single joined mesh object placed on the floor."""
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise RuntimeError(f"unsupported mesh extension: {ext}")
    new = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if not new:
        raise RuntimeError("import produced no mesh objects")
    bpy.ops.object.select_all(action='DESELECT')
    for o in new:
        o.select_set(True)
    bpy.context.view_layer.objects.active = new[0]
    if len(new) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    # drop to floor + center on XY
    zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
    obj.location.z -= min(zs)
    return obj


def frame_object(scn, obj, lens=70, margin=1.4):
    """Add a camera that frames `obj`'s bounding sphere; add floor + studio lights."""
    floor(scn)
    studio(scn)
    bbox = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    center = sum(bbox, mathutils.Vector()) / 8.0
    radius = max((v - center).length for v in bbox)
    cam = bpy.data.cameras.new("Cam")
    cam.lens = lens
    co = bpy.data.objects.new("Cam", cam)
    scn.collection.objects.link(co)
    scn.camera = co
    dist = margin * radius * (50.0 / lens) * 2.2
    co.location = center + mathutils.Vector((dist * 0.7, -dist, dist * 0.5))
    d = center - co.location
    co.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def render_still(scn, path):
    scn.render.image_settings.media_type = 'IMAGE'   # Blender 5.x: select stills before format
    scn.render.image_settings.file_format = 'PNG'
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def render_turntable(scn, obj, out_dir, stem, frames):
    """Spin `obj` 360 over `frames` and encode an MP4 (Blender-bundled FFmpeg). Returns the
    actual .mp4 path (globbed, since Blender appends a frame-range suffix)."""
    # default new keyframes to LINEAR for a constant-speed spin — set via the user pref BEFORE
    # inserting, so we never touch Action.fcurves (removed in Blender 5.x slotted actions).
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    except Exception:
        pass
    obj.rotation_mode = 'XYZ'
    obj.rotation_euler[2] = 0.0
    obj.keyframe_insert("rotation_euler", index=2, frame=1)
    obj.rotation_euler[2] = math.radians(360)
    obj.keyframe_insert("rotation_euler", index=2, frame=frames)
    scn.frame_start, scn.frame_end = 1, frames
    scn.render.image_settings.media_type = 'VIDEO'   # Blender 5.x: VIDEO exposes the FFMPEG format
    scn.render.image_settings.file_format = 'FFMPEG'
    scn.render.ffmpeg.format = 'MPEG4'
    scn.render.ffmpeg.codec = 'H264'
    scn.render.filepath = os.path.join(out_dir, stem + "_tt")
    bpy.ops.render.render(animation=True)
    hits = sorted(glob.glob(os.path.join(out_dir, stem + "_tt*.mp4")))
    if not hits:
        raise RuntimeError("turntable produced no .mp4 (check Blender FFmpeg support)")
    return hits[-1]


def _hex_to_rgba(h, default=(0.5, 0.5, 0.5, 1.0)):
    """'#1c1f22' -> (r,g,b,1.0) in 0..1. Returns `default` on anything unparseable."""
    try:
        s = str(h).lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        r, g, b = (int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, 1.0)
    except Exception:
        return default


def _weld_for_bake(obj):
    """Weld coincident verts + recompute normals before a smart_project bake. glTF/GLB import splits a
    vertex per face-corner (along every UV/normal seam), so a re-imported mesh has NO shared edges —
    smart_project then treats every face as its own island, packs them into sub-pixel specks, and the
    EMIT bake rasterizes essentially nothing (a black atlas). Welding reconnects the surface so the
    unwrap yields real, packable islands. (The bake engine was validated on a clean primitive sphere,
    whose verts are already shared, so this never surfaced until a real Hunyuan3D GLB was baked.)"""
    me = obj.data
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bm.normal_update()
    bm.to_mesh(me); bm.free()
    me.update()


def bake_albedo(obj, scn, concept_path, *, palette, back_fill="palette", res=1024):
    """Smart-UV unwrap `obj`, project `concept_path` from a dead-front camera onto front-facing
    faces, and EMIT-bake into a res×res albedo atlas; back/grazing faces get a flat fill (palette[0]
    or neutral grey), or a back-projected flipped concept when back_fill='mirror'. Leaves the
    material wired for render (Principled Base Color <- baked atlas on the smart-project UV) and
    returns the baked image. NEW bpy surface — validated in live smoke."""
    fill = _hex_to_rgba(palette[0]) if palette else (0.5, 0.5, 0.5, 1.0)

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    _weld_for_bake(obj)   # reconnect GLB-split verts so smart_project yields real (not sub-pixel) islands

    # 1. atlas UV (the bake target layout)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    atlas_uv = obj.data.uv_layers.active.name

    # 2. dead-front camera aligned to the concept's view (looks at the object centre along +Y)
    bbox = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    centre = sum(bbox, mathutils.Vector()) / 8.0
    radius = max((v - centre).length for v in bbox) or 1.0
    fcam_d = bpy.data.cameras.new("FrontCam")
    fcam = bpy.data.objects.new("FrontCam", fcam_d)
    scn.collection.objects.link(fcam)
    fcam.location = centre + mathutils.Vector((0.0, -radius * 3.0, 0.0))
    fdir = (centre - fcam.location).normalized()
    fcam.rotation_euler = fdir.to_track_quat('-Z', 'Y').to_euler()
    prev_cam = scn.camera
    scn.camera = fcam

    # 3. projection UV from the front camera, computed directly per-loop. (bpy.ops.uv.project_from_view
    #    needs a VIEW_3D region context, which does not exist under `blender --background`; the
    #    world_to_camera_view math is headless-safe and gives the same screen-space == concept coords.)
    from bpy_extras.object_utils import world_to_camera_view
    proj_uv = obj.data.uv_layers.new(name="Proj").name
    bpy.context.view_layer.update()
    me = obj.data
    mw = obj.matrix_world
    proj_data = me.uv_layers[proj_uv].data
    for poly in me.polygons:
        for li in poly.loop_indices:
            co = world_to_camera_view(scn, fcam, mw @ me.vertices[me.loops[li].vertex_index].co)
            proj_data[li].uv = (co.x, co.y)
    obj.data.uv_layers.active = me.uv_layers[atlas_uv]  # bake target layout is the smart-project UV

    # 4. albedo target image
    img = bpy.data.images.new("albedo", width=res, height=res, alpha=False)

    # 5. material: EMIT = mix(fill, concept-via-Proj, front-mask); + the atlas bake-target node
    mat = bpy.data.materials.new("Albedo")
    mat.use_nodes = True
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    concept = bpy.data.images.load(concept_path)
    ctex = nt.nodes.new("ShaderNodeTexImage"); ctex.image = concept
    cuv = nt.nodes.new("ShaderNodeUVMap"); cuv.uv_map = proj_uv
    nt.links.new(cuv.outputs["UV"], ctex.inputs["Vector"])
    # front mask: dot(world Normal, -front_dir) > 0 — front faces point back toward the camera
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath"); dot.operation = 'DOT_PRODUCT'
    dot.inputs[1].default_value = (-fdir.x, -fdir.y, -fdir.z)
    gt = nt.nodes.new("ShaderNodeMath"); gt.operation = 'GREATER_THAN'; gt.inputs[1].default_value = 0.15
    nt.links.new(geo.outputs["Normal"], dot.inputs[0])
    nt.links.new(dot.outputs["Value"], gt.inputs[0])
    mix = nt.nodes.new("ShaderNodeMixRGB")  # TODO(blender>5.x): ShaderNodeMix(data_type='RGBA') when the MixRGB alias is dropped
    mix.inputs["Color1"].default_value = fill            # back / grazing -> fill
    nt.links.new(gt.outputs["Value"], mix.inputs["Fac"])
    if back_fill == "mirror":
        # back-project a horizontally-flipped concept for rear faces (symmetric subjects)
        flip = nt.nodes.new("ShaderNodeMapping"); flip.inputs["Scale"].default_value = (-1.0, 1.0, 1.0)
        muv = nt.nodes.new("ShaderNodeUVMap"); muv.uv_map = proj_uv
        nt.links.new(muv.outputs["UV"], flip.inputs["Vector"])
        mtex = nt.nodes.new("ShaderNodeTexImage"); mtex.image = concept
        nt.links.new(flip.outputs["Vector"], mtex.inputs["Vector"])
        nt.links.new(mtex.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(ctex.outputs["Color"], mix.inputs["Color2"])  # front -> concept
    nt.links.new(mix.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    # bake-target node: the atlas image on the smart-project UV, selected+active
    auv = nt.nodes.new("ShaderNodeUVMap"); auv.uv_map = atlas_uv
    atex = nt.nodes.new("ShaderNodeTexImage"); atex.image = img
    nt.links.new(auv.outputs["UV"], atex.inputs["Vector"])
    for n in nt.nodes:
        n.select = False
    atex.select = True
    nt.nodes.active = atex

    # 6. EMIT bake into the atlas (Blender 5.1: set EXTEND margin explicitly)
    scn.render.engine = 'CYCLES'
    scn.render.bake.margin_type = 'EXTEND'
    bpy.ops.object.bake(type='EMIT', margin=max(4, res // 64))

    # 7. rewire for RENDER: Principled Base Color <- baked atlas on the atlas UV
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.6
    auv2 = nt.nodes.new("ShaderNodeUVMap"); auv2.uv_map = atlas_uv
    atex2 = nt.nodes.new("ShaderNodeTexImage"); atex2.image = img
    nt.links.new(auv2.outputs["UV"], atex2.inputs["Vector"])
    nt.links.new(atex2.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    scn.camera = prev_cam
    bpy.data.objects.remove(fcam, do_unlink=True)   # don't leak the temp cam (Phase 4b may re-bake)
    bpy.data.cameras.remove(fcam_d)
    return img


def _ring_camera(scn, centre, radius, az_deg, el_deg):
    """Create+link a temp camera on a ring around `centre` at azimuth/elevation (deg), looking at it.
    Returns (cam_object, cam_data, view_dir). az 0 = front (-Y); +az rotates toward +X (right);
    so 4 evenly-spaced views are front / right / back / left. Caller removes both datablocks."""
    a, e = math.radians(az_deg), math.radians(el_deg)
    offset = mathutils.Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam_d = bpy.data.cameras.new("RingCam")
    cam = bpy.data.objects.new("RingCam", cam_d)
    scn.collection.objects.link(cam)
    cam.location = centre + offset * (radius * 3.0)
    view_dir = (centre - cam.location).normalized()
    cam.rotation_euler = view_dir.to_track_quat('-Z', 'Y').to_euler()
    return cam, cam_d, view_dir


def bake_multiview(obj, scn, view_images, *, azimuths, elevation_deg=15.0,
                   back_fill="palette", palette=None, res=1024):
    """All-around albedo bake (Phase 4b): project N corrected views (one per `azimuths` entry) onto the
    mesh and EMIT-bake a weighted blend into a res×res atlas. Each face takes each view weighted by how
    front-on it is to that view (max(0, dot(Normal, -view_dir))^2), gated to zero off the view's frame.
    Faces no view sees get a flat `back_fill` (palette[0] or neutral grey). Generalizes bake_albedo (N=1)
    for the one-shot finalize of a winning mesh. Pure bpy/Cycles — never touches the blocked
    custom_rasterizer path. Returns the baked image. NEW bpy surface — validated in live smoke (synthetic
    distinct-per-view colours).

    Best for convex / near-convex meshes: like all projection baking there is no occlusion test, so a
    deeply concave self-occluder can get an occluder's pixels projected onto a hidden-but-front-facing
    face. At most 7 views (Blender caps a mesh at 8 UV layers; one is the atlas)."""
    if len(view_images) != len(azimuths):
        raise ValueError("bake_multiview: view_images and azimuths must be the same length")
    palette = palette or []
    fill = _hex_to_rgba(palette[0]) if (back_fill == "palette" and palette) else (0.5, 0.5, 0.5, 1.0)
    eps = 1e-4

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    _weld_for_bake(obj)   # reconnect GLB-split verts so smart_project yields real (not sub-pixel) islands

    # 1. atlas UV (bake-target layout)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    atlas_uv = obj.data.uv_layers.active.name

    # 2. frame: object bounds centre + radius
    bbox = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    centre = sum(bbox, mathutils.Vector()) / 8.0
    radius = max((v - centre).length for v in bbox) or 1.0

    from bpy_extras.object_utils import world_to_camera_view
    me = obj.data
    mw = obj.matrix_world
    prev_cam = scn.camera
    prev_res = (scn.render.resolution_x, scn.render.resolution_y)  # restored at the end (stills use it)

    mat = bpy.data.materials.new("AlbedoMV")
    mat.use_nodes = True
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    geo = nt.nodes.new("ShaderNodeNewGeometry")

    cams = []                       # temp cameras to remove at the end
    num_node = None                 # running Σ (w_i · color_i)  (vector)
    den_node = None                 # running Σ w_i              (scalar)
    for i, (img_path, az) in enumerate(zip(view_images, azimuths, strict=True)):
        cam, cam_d, vdir = _ring_camera(scn, centre, radius, az, elevation_deg)
        cams.append((cam, cam_d))
        scn.camera = cam
        # match the projection frame to THIS view image's aspect (world_to_camera_view uses the scene
        # render resolution for the frame) so non-square views aren't stretched; restored at the end.
        vimg = bpy.data.images.load(img_path)
        iw, ih = vimg.size
        if iw and ih:
            scn.render.resolution_x, scn.render.resolution_y = iw, ih
        bpy.context.view_layer.update()
        # per-view projection UV (world_to_camera_view: headless-safe, unlike uv.project_from_view)
        proj_uv = me.uv_layers.new(name=f"Proj{i}").name
        pdata = me.uv_layers[proj_uv].data
        for poly in me.polygons:
            for li in poly.loop_indices:
                co = world_to_camera_view(scn, cam, mw @ me.vertices[me.loops[li].vertex_index].co)
                pdata[li].uv = (co.x, co.y)
        # view image sampled on its projection UV; CLIP so off-frame faces read transparent (alpha 0)
        uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = proj_uv
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = vimg; tex.extension = 'CLIP'
        nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])
        # weight w_i = max(0, dot(Normal, -view_dir))^2  (front-facing to THIS view)
        dot = nt.nodes.new("ShaderNodeVectorMath"); dot.operation = 'DOT_PRODUCT'
        dot.inputs[1].default_value = (-vdir.x, -vdir.y, -vdir.z)
        nt.links.new(geo.outputs["Normal"], dot.inputs[0])
        clamp = nt.nodes.new("ShaderNodeMath"); clamp.operation = 'MAXIMUM'; clamp.inputs[1].default_value = 0.0
        nt.links.new(dot.outputs["Value"], clamp.inputs[0])
        w = nt.nodes.new("ShaderNodeMath"); w.operation = 'POWER'; w.inputs[1].default_value = 2.0
        nt.links.new(clamp.outputs["Value"], w.inputs[0])
        # gate the weight to zero where the face is OUTSIDE this view's frame: CLIP gives alpha 0 there,
        # so a front-facing-but-off-frame face contributes neither colour nor weight (no wrap/garbage bleed)
        we = nt.nodes.new("ShaderNodeMath"); we.operation = 'MULTIPLY'
        nt.links.new(w.outputs["Value"], we.inputs[0])
        nt.links.new(tex.outputs["Alpha"], we.inputs[1])
        # weighted colour = color_i * we
        wc = nt.nodes.new("ShaderNodeVectorMath"); wc.operation = 'SCALE'
        nt.links.new(tex.outputs["Color"], wc.inputs[0])
        nt.links.new(we.outputs["Value"], wc.inputs["Scale"])
        if num_node is None:
            num_node, den_node = wc, we
        else:
            add_c = nt.nodes.new("ShaderNodeVectorMath"); add_c.operation = 'ADD'
            nt.links.new(num_node.outputs[0], add_c.inputs[0])
            nt.links.new(wc.outputs[0], add_c.inputs[1])
            add_w = nt.nodes.new("ShaderNodeMath"); add_w.operation = 'ADD'
            nt.links.new(den_node.outputs["Value"], add_w.inputs[0])
            nt.links.new(we.outputs["Value"], add_w.inputs[1])
            num_node, den_node = add_c, add_w

    # normalized weighted colour = num / max(den, eps)
    den_safe = nt.nodes.new("ShaderNodeMath"); den_safe.operation = 'MAXIMUM'; den_safe.inputs[1].default_value = eps
    nt.links.new(den_node.outputs["Value"], den_safe.inputs[0])
    inv = nt.nodes.new("ShaderNodeMath"); inv.operation = 'DIVIDE'; inv.inputs[0].default_value = 1.0
    nt.links.new(den_safe.outputs["Value"], inv.inputs[1])
    avg = nt.nodes.new("ShaderNodeVectorMath"); avg.operation = 'SCALE'
    nt.links.new(num_node.outputs[0], avg.inputs[0])
    nt.links.new(inv.outputs["Value"], avg.inputs["Scale"])
    # coverage: faces no view sees (den <= eps) -> flat fill
    seen = nt.nodes.new("ShaderNodeMath"); seen.operation = 'GREATER_THAN'; seen.inputs[1].default_value = eps
    nt.links.new(den_node.outputs["Value"], seen.inputs[0])
    mix = nt.nodes.new("ShaderNodeMixRGB")  # TODO(blender>5.x): ShaderNodeMix(data_type='RGBA')
    mix.inputs["Color1"].default_value = fill
    nt.links.new(seen.outputs["Value"], mix.inputs["Fac"])
    nt.links.new(avg.outputs[0], mix.inputs["Color2"])
    nt.links.new(mix.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

    # atlas bake-target node (selected + active), on the smart-project UV
    img = bpy.data.images.new("albedo_mv", width=res, height=res, alpha=False)
    obj.data.uv_layers.active = me.uv_layers[atlas_uv]
    auv = nt.nodes.new("ShaderNodeUVMap"); auv.uv_map = atlas_uv
    atex = nt.nodes.new("ShaderNodeTexImage"); atex.image = img
    nt.links.new(auv.outputs["UV"], atex.inputs["Vector"])
    for n in nt.nodes:
        n.select = False
    atex.select = True
    nt.nodes.active = atex

    # EMIT bake into the atlas (Blender 5.1: EXTEND margin)
    scn.render.engine = 'CYCLES'
    scn.render.bake.margin_type = 'EXTEND'
    bpy.ops.object.bake(type='EMIT', margin=max(4, res // 64))

    # rewire for RENDER: Principled Base Color <- baked atlas
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.6
    auv2 = nt.nodes.new("ShaderNodeUVMap"); auv2.uv_map = atlas_uv
    atex2 = nt.nodes.new("ShaderNodeTexImage"); atex2.image = img
    nt.links.new(auv2.outputs["UV"], atex2.inputs["Vector"])
    nt.links.new(atex2.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    scn.camera = prev_cam
    scn.render.resolution_x, scn.render.resolution_y = prev_res   # don't leak per-view res to the stills
    for cam, cam_d in cams:        # don't leak the temp ring cameras
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_d)
    return img

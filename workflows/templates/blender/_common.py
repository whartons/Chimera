"""Shared bpy helpers for Chimera's headless Blender templates. Each template does:
    import _common as C; p = C.args(); ... ; C.emit({"outputs": [...], "blender_version": ...})
Run only inside `blender --background --python <template> -- <json>`."""
import bpy, sys, os, json, math, glob, mathutils


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
    mix = nt.nodes.new("ShaderNodeMixRGB")
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
    return img

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
    scn.render.image_settings.file_format = 'PNG'
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def render_turntable(scn, obj, out_dir, stem, frames):
    """Spin `obj` 360 over `frames` and encode an MP4 (Blender-bundled FFmpeg). Returns the
    actual .mp4 path (globbed, since Blender appends a frame-range suffix)."""
    obj.rotation_mode = 'XYZ'
    obj.rotation_euler[2] = 0.0
    obj.keyframe_insert("rotation_euler", index=2, frame=1)
    obj.rotation_euler[2] = math.radians(360)
    obj.keyframe_insert("rotation_euler", index=2, frame=frames)
    for fc in obj.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
    scn.frame_start, scn.frame_end = 1, frames
    scn.render.image_settings.file_format = 'FFMPEG'
    scn.render.ffmpeg.format = 'MPEG4'
    scn.render.ffmpeg.codec = 'H264'
    scn.render.filepath = os.path.join(out_dir, stem + "_tt")
    bpy.ops.render.render(animation=True)
    hits = sorted(glob.glob(os.path.join(out_dir, stem + "_tt*.mp4")))
    if not hits:
        raise RuntimeError("turntable produced no .mp4 (check Blender FFmpeg support)")
    return hits[-1]

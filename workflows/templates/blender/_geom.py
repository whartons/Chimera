"""bpy-free decisions for Chimera's headless Blender templates: camera framing and clipping, OBJ import axes, the
--color project front projection, and which pieces --solid keeps. _common and the templates import it inside
Blender; the test suite imports it on the host (tests/test_blender_geom.py), since CI has no Blender. Plain
sequences in and out, no mathutils."""
import math


def obj_import_axes(head: str) -> dict:
    """wm.obj_import axis arguments for an OBJ whose first bytes are `head`. FreeCAD writes OBJ in its own Z-up
    axes, but the importer assumes Y-up, which stood a 24 x 24 x 30 mm FreeCAD tube on its side: 24 x 30 x 24
    (2026-10-25). Any other OBJ keeps the importer's Y-up default."""
    if "created by freecad" in head.lower():
        return {"forward_axis": "Y", "up_axis": "Z"}
    return {}


def clip_range(radius):
    """Camera (clip_start, clip_end) for an object of bounding `radius`: Blender's fixed 0.1-1000 cut the near side
    off a ring-camera view of a 0.03 m mesh and the floor off behind a mm-scale CAD part."""
    r = max(float(radius), 1e-6)
    return r * 0.001, r * 1000.0


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def frame_distance(points, center, toward_cam, right, up, tan_x, tan_y):
    """How far from `center` (along the unit `toward_cam`) a camera must sit for every point to be in frame, given
    the frame's half-angle tangents. Points nearer the camera need more distance."""
    need = 0.0
    for v in points:
        p = (v[0] - center[0], v[1] - center[1], v[2] - center[2])
        closer = _dot(p, toward_cam)
        need = max(need, abs(_dot(p, right)) / tan_x + closer, abs(_dot(p, up)) / tan_y + closer)
    return need


def turntable_points(corners, axis_xy, n=32):
    """Points around the bounding cylinder of `corners` about the vertical axis through `axis_xy`: every pose of a
    turntable spin stays inside it. Framing the corners at rotation 0 cropped a mesh long along Y at ~105 and 285
    degrees (2026-10-25). The polygon circumscribes the circle, so poses between its points stay inside too."""
    ax, ay = float(axis_xy[0]), float(axis_xy[1])
    rho = max(math.hypot(c[0] - ax, c[1] - ay) for c in corners) / math.cos(math.pi / n)
    zs = (min(c[2] for c in corners), max(c[2] for c in corners))
    return [(ax + rho * math.cos(2 * math.pi * k / n), ay + rho * math.sin(2 * math.pi * k / n), z)
            for k in range(n) for z in zs]


def front_uv(xmin, xmax, zmin, zmax, aspect):
    """(su, ou, sv, ov) mapping a mesh's front (x across, z up, seen from -Y) onto an image of width/height
    `aspect`: u = x * su + ou, v = z * sv + ov. The mesh fits inside the image, centred, with square pixels."""
    w, h = max(xmax - xmin, 1e-9), max(zmax - zmin, 1e-9)
    span = max(h, w / aspect)                      # world height the image covers; its width is span * aspect
    su, sv = 1.0 / (span * aspect), 1.0 / span
    return su, 0.5 - (xmin + xmax) / 2 * su, sv, 0.5 - (zmin + zmax) / 2 * sv


def keep_pieces(face_counts, speck_frac):
    """Indices of the pieces --solid keeps: every one with at least `speck_frac` of the largest piece's faces.
    Keeping only the largest dropped a real second body, like a separate plaque, without a word (2026-10-25)."""
    if not face_counts:
        return []
    floor = speck_frac * max(face_counts)
    return [i for i, n in enumerate(face_counts) if n >= floor]

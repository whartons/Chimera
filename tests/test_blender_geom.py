"""workflows/templates/blender/_geom.py: the bpy-free decisions behind the Blender templates (camera framing and
clipping, OBJ axes, front projection, which pieces --solid keeps), tested on the host since CI has no Blender."""
from __future__ import annotations
import ast
import importlib.util
import math
from pathlib import Path

import pytest

BLENDER = Path(__file__).resolve().parents[1] / "workflows" / "templates" / "blender"
_spec = importlib.util.spec_from_file_location("chimera_blender_geom", BLENDER / "_geom.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)


def _calls_in(template, func, callee):
    """True when `func` in the template's source calls `callee` (by name, e.g. G.clip_range)."""
    tree = ast.parse((BLENDER / template).read_text(encoding="utf-8"))
    body = tree if func is None else next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                                          and n.name == func)
    return any(isinstance(n, ast.Call) and ast.unparse(n.func).endswith(callee) for n in ast.walk(body))


# --- a FreeCAD OBJ is Z-up (2026-10-25: a 24 x 24 x 30 mm tube came into Blender on its side, 24 x 30 x 24) ---

def test_a_freecad_obj_imports_z_up_and_any_other_obj_keeps_the_default():
    assert G.obj_import_axes("# Created by FreeCAD <https://www.freecad.org>\nv 12 0 30\n") == {
        "forward_axis": "Y", "up_axis": "Z"}
    assert G.obj_import_axes("# Blender 5.2.2\nmtllib m.mtl\no Cube\n") == {}
    assert G.obj_import_axes("") == {}
    assert _calls_in("_common.py", "import_mesh", "obj_import_axes")


# --- the ring cameras' clip range follows the object (a 40 mm ball lost its near side to the 0.1 m default) ---

@pytest.mark.parametrize("radius", [0.02, 0.05, 1.0, 400.0])
def test_the_clip_range_holds_a_ring_camera_view_of_any_size(radius):
    start, end = G.clip_range(radius)
    # _ring_camera sits 3 radii out: the near side is 2 radii away, the far side 4
    assert start < 2 * radius * 0.5 and end > 4 * radius * 2


def test_both_cameras_use_the_scaled_clip_range():
    assert _calls_in("_common.py", "_ring_camera", "clip_range")
    assert _calls_in("_common.py", "frame_object", "clip_range")


# --- a turntable frames every pose, not just rotation 0 ---

def _camera_basis():
    toward = (0.7, -1.0, 0.5)
    n = math.sqrt(sum(c * c for c in toward))
    toward = tuple(c / n for c in toward)
    right = (-toward[1], toward[0], 0.0)                       # (-toward) x Z, normalized
    n = math.hypot(*right)
    right = (right[0] / n, right[1] / n, 0.0)
    up = (right[1] * -toward[2] - 0 * -toward[1], 0 * -toward[0] - right[0] * -toward[2],
          right[0] * -toward[1] - right[1] * -toward[0])       # right x (-toward)
    return toward, right, up


def _crops(dist, corners, toward, right, up, tan):
    """Worst over 0-360 deg turntable poses: how far outside the frame a corner lands (> 1 = cropped)."""
    worst = 0.0
    for deg in range(0, 360, 3):
        a = math.radians(deg)
        for x, y, z in corners:
            p = (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a), z)
            depth = dist - sum(p[i] * toward[i] for i in range(3))
            for axis in (right, up):
                worst = max(worst, abs(sum(p[i] * axis[i] for i in range(3))) / (depth * tan))
    return worst


def test_a_turntable_of_a_long_mesh_stays_in_frame():
    corners = [(x, y, z) for x in (-0.5, 0.5) for y in (-2.0, 2.0) for z in (-0.5, 0.5)]     # long along Y
    toward, right, up = _camera_basis()
    tan = 36.0 / 2 / 70                                                      # 70 mm lens, square frame
    still = G.frame_distance(corners, (0, 0, 0), toward, right, up, tan, tan)
    assert _crops(still, corners, toward, right, up, tan) > 1.0              # rotation 0 only: cropped mid-spin
    spin = G.frame_distance(G.turntable_points(corners, (0.0, 0.0)), (0, 0, 0), toward, right, up, tan, tan)
    assert _crops(spin, corners, toward, right, up, tan) <= 1.0
    assert spin < 1.6 * still                                                 # no wilder than it must be


def test_the_spinning_templates_frame_for_the_spin():
    tree = ast.parse((BLENDER / "_common.py").read_text(encoding="utf-8"))
    frame = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "frame_object")
    assert "turntable" in [a.arg for a in frame.args.args + frame.args.kwonlyargs]
    for template in ("mesh_render.py", "mesh_eval.py", "mesh_finalize.py"):     # turntable / orbit stills
        call = next(n for n in ast.walk(ast.parse((BLENDER / template).read_text(encoding="utf-8")))
                    if isinstance(n, ast.Call) and ast.unparse(n.func) == "C.frame_object")
        assert any(k.arg == "turntable" for k in call.keywords), template


# --- --color project: a front projection of the image onto the mesh's silhouette ---

@pytest.mark.parametrize("bounds, aspect", [((-1, 1, 0, 4), 1.0), ((-4, 4, 0, 1), 2.0), ((-3, 3, 0, 1), 0.5)])
def test_the_front_projection_fits_the_mesh_inside_the_image(bounds, aspect):
    xmin, xmax, zmin, zmax = bounds
    su, ou, sv, ov = G.front_uv(xmin, xmax, zmin, zmax, aspect)
    us, vs = sorted((xmin * su + ou, xmax * su + ou)), sorted((zmin * sv + ov, zmax * sv + ov))
    assert all(-1e-9 <= t <= 1 + 1e-9 for t in us + vs)                      # the whole mesh lands on the image
    assert math.isclose(us[1] - us[0], 1.0) or math.isclose(vs[1] - vs[0], 1.0)   # and fills one side of it
    assert math.isclose((us[0] + us[1]) / 2, 0.5) and math.isclose((vs[0] + vs[1]) / 2, 0.5)
    # square pixels: a mesh unit spans the same number of image pixels across as up
    assert math.isclose(su * aspect, sv)


def test_project_wires_the_projection_into_the_texture():
    src = (BLENDER / "mesh_finish.py").read_text(encoding="utf-8")
    assert _calls_in("mesh_finish.py", None, "front_uv")
    assert 'tex.inputs["Vector"]' in src


# --- --solid keeps every real body, drops only specks ---

def test_solid_drops_only_specks():
    assert G.keep_pieces([120_000, 40, 9_000, 3], 0.01) == [0, 2]            # a figure + its separate plaque
    assert G.keep_pieces([5], 0.01) == [0]
    assert G.keep_pieces([], 0.01) == []
    assert G.keep_pieces([1000, 1000], 0.01) == [0, 1]


# --- Phase 4a projects a non-square concept at its own aspect ---

def test_bake_albedo_projects_at_the_concept_aspect():
    tree = ast.parse((BLENDER / "_common.py").read_text(encoding="utf-8"))
    bake = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "bake_albedo")
    src = ast.unparse(bake)
    assert "scn.render.resolution_x, scn.render.resolution_y = " in src and "concept.size" in src

"""Solidify: a thin double-sided AI mesh (TRELLIS.2-style sheet) becomes one solid, leaks included."""
import math

import pytest

np = pytest.importorskip("numpy")      # the [print] extra
pytest.importorskip("scipy")
pytest.importorskip("skimage")
from scripts.brandkit import printcheck as PC  # noqa: E402
from scripts.brandkit import solidify as S  # noqa: E402


def sphere(r, n_lat=48, n_lon=96, inward=False, hole_deg=0.0):
    """UV-sphere triangles (outward), optionally inward-facing, optionally with a round hole of
    `hole_deg` half-angle at the north pole."""
    th = np.linspace(0, np.pi, n_lat + 1)
    ph = np.linspace(0, 2 * np.pi, n_lon + 1)
    P = np.stack([np.sin(th)[:, None] * np.cos(ph)[None], np.sin(th)[:, None] * np.sin(ph)[None],
                  np.cos(th)[:, None] * np.ones_like(ph)[None]], -1) * r
    tris = []
    for i in range(n_lat):
        if math.degrees(th[i + 1]) <= hole_deg:
            continue
        for j in range(n_lon):
            a, b, c, d = P[i, j], P[i + 1, j], P[i + 1, j + 1], P[i, j + 1]
            tris += [(a, b, c), (a, c, d)]
    t = np.array(tris)
    t = t[np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) > 1e-9]   # pole slivers
    return t[:, ::-1] if inward else t


def sheet(r=20.0, thickness=0.6, hole_deg=0.0):
    """A TRELLIS.2-like sheet: an outer surface and an inner one `thickness` below it, both closed around the
    body's empty cavity (optionally leaking through a hole at the top)."""
    return np.concatenate([sphere(r, hole_deg=hole_deg), sphere(r - thickness, inward=True, hole_deg=hole_deg)])


def test_a_sheet_is_hollow_before_solidify():
    assert PC.check(sheet())["verdict"] == "HOLLOW"


def test_solidify_turns_a_sheet_into_one_solid_of_the_outer_size():
    out, info = S.solidify(sheet(), vox=0.5)
    r = PC.check(out)
    assert r["verdict"] == "SOLID" and r["bad_edges"] == 0 and r["pieces"] == 1
    ball = 4 / 3 * math.pi * 20.0 ** 3 / 1000.0
    assert r["volume_cm3"] == pytest.approx(ball, rel=0.04)      # the outer skin, not the inner one
    assert info["volume_cm3"] == pytest.approx(r["volume_cm3"], rel=0.01)


def test_a_leak_too_wide_for_the_smallest_closing_radius_leaves_it_hollow():
    out, info = S.solidify(sheet(hole_deg=12.0), vox=0.5, close_mm=1.0)    # ~7.8 mm hole, 1 mm closing
    assert PC.check(out)["verdict"] == "HOLLOW"


def test_auto_close_picks_the_smallest_radius_that_seals_the_leak():
    out, info = S.solidify(sheet(hole_deg=12.0), vox=0.5)     # ~7.8 mm hole: the first radii leak
    assert PC.check(out)["verdict"] == "SOLID"
    radii = sorted(info["solid_cm3_by_radius"])
    assert info["close_mm"] > radii[0]                      # the smallest radius leaked, so it was skipped
    smaller = [r for r in radii if r < info["close_mm"]]
    assert all(info["solid_cm3_by_radius"][r] < 0.97 * max(info["solid_cm3_by_radius"].values()) for r in smaller)


def test_voxel_size_follows_the_print_size():
    assert S.auto_voxel_mm(228.6) == pytest.approx(0.3)
    assert S.auto_voxel_mm(60) == pytest.approx(0.3)            # floor: finer than a 0.4 mm nozzle is wasted
    assert S.auto_voxel_mm(500) == pytest.approx(500 / 762, rel=1e-6)


def test_solidify_file_round_trips_through_stl(tmp_path):
    src = PC.write_stl(tmp_path / "raw.stl", sheet())
    info = S.solidify_file(src, tmp_path / "solid.stl", vox=0.5)
    assert PC.check_file(tmp_path / "solid.stl")["verdict"] == "SOLID"
    assert info["close_mm"] > 0


# solid volume (cm3) by closing radius (mm), measured on real TRELLIS.2 models at 0.3 mm voxels
_CURVES = {
    "trophy 01, leak seals at 1.6": ({1.2: 418, 1.6: 759, 2.0: 761, 2.4: 763, 3.2: 767, 4.0: 772}, 1.6),
    "trophy 05, leak seals at 2.0": ({1.2: 209, 1.6: 212, 2.0: 969, 2.4: 974, 3.2: 979, 4.0: 984}, 2.0),
    "trophy 08, leak seals at 2.0": ({1.2: 326, 1.6: 328, 2.0: 1087, 2.4: 1089, 3.2: 1093, 4.0: 1100}, 2.0),
    # after the seal at 1.6 the volume keeps creeping up (+2-9 % a step) as bigger radii web concave gaps
    # (cape against body); "within 97 % of the largest" chased that creep to 4.0 and over-closed
    "caped figure, seal at 1.6 then creep": ({1.2: 175.7, 1.6: 269.4, 2.0: 274.6, 2.4: 298.3, 3.2: 309.9, 4.0: 323.7}, 1.6),
    "no leak (Hunyuan3D, already solid)": ({1.2: 850.8, 1.6: 851.0, 2.0: 852.0, 2.4: 853.1, 3.2: 855.0, 4.0: 858.0}, 1.2),
}


@pytest.mark.parametrize("name", list(_CURVES))
def test_the_closing_radius_is_the_one_right_after_the_last_big_jump(name):
    curve, want = _CURVES[name]
    radii = sorted(curve)
    assert S.pick_close_radius(radii, [curve[r] for r in radii]) == want

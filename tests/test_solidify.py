"""Solidify: a thin double-sided AI mesh (TRELLIS.2-style sheet) becomes one solid, leaks included."""
import json
import math

import pytest

np = pytest.importorskip("numpy")      # the [print] extra
pytest.importorskip("scipy")
pytest.importorskip("skimage")
from scripts.brandkit import printcheck as PC  # noqa: E402
from scripts.brandkit import solidify as S  # noqa: E402
from tests.meshes import box, sheet, slot_is_open, slotted_block  # noqa: E402


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
    # below 228.6 mm it keeps shrinking, so the closing radii (in voxels) shrink with the print like the sheet and
    # its leaks do; a 0.3 mm floor kept them at 1.2-4 mm and webbed a miniature's slots shut (2026-10-25)
    assert S.auto_voxel_mm(60) == pytest.approx(60 / 762)
    assert S.auto_voxel_mm(10) == pytest.approx(S.MIN_VOXEL_MM)    # the floor: a tiny part stays cheap
    assert S.auto_voxel_mm(500) == pytest.approx(500 / 762, rel=1e-6)


def test_a_slot_in_a_small_print_stays_open(tmp_path, monkeypatch):
    # a 40 mm part with a 2 mm slot: a 0.3 mm voxel's smallest closing radius (1.2 mm) webbed the slot shut
    monkeypatch.setattr(S, "MAX_VOXELS", 4_000_000)        # keeps the test quick; the voxel still comes out ~0.19 mm
    src = PC.write_stl(tmp_path / "u.stl", slotted_block())
    info = S.solidify_file(src, tmp_path / "solid.stl")
    assert info["voxel_mm"] < 0.25
    assert slot_is_open(PC.read_stl(tmp_path / "solid.stl"))


def test_solidify_file_round_trips_through_stl(tmp_path):
    src = PC.write_stl(tmp_path / "raw.stl", sheet())
    info = S.solidify_file(src, tmp_path / "solid.stl", vox=0.5)
    assert PC.check_file(tmp_path / "solid.stl")["verdict"] == "SOLID"
    assert info["close_mm"] > 0
    # the info goes into the sidecar, which holds no absolute paths: "output" was the temp file's full path
    assert str(tmp_path) not in json.dumps(info) and "output" not in info


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


@pytest.mark.parametrize("tris", [np.zeros((0, 3, 3)), np.array([[[0, 0, 0], [1, 1, 1], [2, 2, 2]]], float)],
                         ids=["empty", "all degenerate"])
def test_no_triangles_is_a_clear_error(tris, tmp_path):
    # numpy's "zero-size array to reduction operation minimum" reached the user
    with pytest.raises(ValueError, match="no triangles"):
        S.solidify(tris, vox=0.5)
    with pytest.raises(ValueError, match="no triangles"):
        S.solidify_file(PC.write_stl(tmp_path / "raw.stl", tris), tmp_path / "solid.stl")


def test_an_open_flat_face_has_no_volume_to_fill():
    # a flat square "succeeded" as a 67 mm sheet with 1332 open edges
    square = np.array([[[0, 0, 0], [50, 0, 0], [50, 50, 0]], [[0, 0, 0], [50, 50, 0], [0, 50, 0]]], float)
    with pytest.raises(ValueError, match="no closed volume"):
        S.solidify(square, vox=0.5)


def test_big_triangles_are_sampled_all_over():
    # a CAD-like 100 x 100 x 10 mm slab in 12 triangles: a 64-step cap on the subdivision dotted each face every
    # ~2 mm, so the flat top came out dimpled (0.28 mm) and the closed volume swung 96-106 cm3 by radius
    out, info = S.solidify(box((0, 0, 0), (100, 100, 10)), vox=0.5)
    v = out.reshape(-1, 3)
    top = v[(v[:, 0] > 20) & (v[:, 0] < 80) & (v[:, 1] > 20) & (v[:, 1] < 80) & (v[:, 2] > 5), 2]
    assert np.abs(top - top.mean()).max() < 0.05
    vols = list(info["solid_cm3_by_radius"].values())
    assert max(vols) / min(vols) < 1.02
    assert info["close_mm"] == min(info["solid_cm3_by_radius"])


def test_sampling_a_huge_face_comes_in_batches():
    tris = box((0, 0, 0), (100, 100, 10))
    batches = list(S._sample(tris, 0.25, chunk=50_000))
    assert len(batches) > 1 and all(len(b[0]) <= 50_000 + 200_000 for b in batches)
    pts, ids, w, bary = (np.concatenate(x) for x in zip(*batches, strict=True))
    assert np.allclose(np.bincount(ids, weights=w), 1.0)                  # each face's weights sum to 1
    assert np.allclose((tris[ids] * bary[:, :, None]).sum(1), pts)        # bary is in the face's own corner order
    for f in range(len(tris)):                                            # every face sampled to the step
        assert (ids == f).sum() >= 0.5 * (np.linalg.norm(np.cross(tris[f, 1] - tris[f, 0], tris[f, 2] - tris[f, 0]))
                                          / 0.25 ** 2)


# --- memory: a compact 228.6 mm print (a bust, a vase) got an 800^3 grid, ~27 GB at ~53 B a voxel (2026-10-25) ---

def test_a_compact_print_gets_a_grid_under_the_cap():
    for size in ((228.6, 228.6, 228.6), (400.0, 380.0, 300.0)):
        vox = S.voxel_for_size(size)
        assert math.prod(S.grid_shape(size, vox)) <= S.MAX_VOXELS
    assert S.voxel_for_size((100.0, 80.0, 228.6)) == pytest.approx(0.3)      # the proven trophy setting stays


def test_solidify_file_coarsens_the_voxel_to_fit_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "MAX_VOXELS", 2_000_000)
    src = PC.write_stl(tmp_path / "raw.stl", box((0, 0, 0), (228.6, 228.6, 228.6)))
    info = S.solidify_file(src, tmp_path / "solid.stl")
    assert info["voxel_mm"] > 0.3
    assert math.prod(S.grid_shape((228.6,) * 3, info["voxel_mm"])) <= 2_000_000
    assert info["volume_cm3"] == pytest.approx(228.6 ** 3 / 1000, rel=0.03)


@pytest.mark.parametrize("r", [1.0, 1.2 / 0.3, 16 / 3, 20 / 3, 8.0, 40 / 3, 2.5])
def test_the_capped_distance_transform_matches_scipy_at_the_threshold(r):
    from scipy import ndimage
    free = np.random.default_rng(int(r * 100)).random((41, 37, 33)) > 0.997
    d = S._sq_dist(free, r)
    assert np.array_equal(d <= S._within_sq(r), ndimage.distance_transform_edt(~free) <= r)


def test_the_normal_splat_accumulates_in_float32_with_the_trilinear_weights():
    rng = np.random.default_rng(3)
    shape = (9, 8, 7)
    g = rng.random((500, 3)) * (np.array(shape) - 2)
    wn = rng.normal(size=(500, 3))
    strides = np.array([shape[1] * shape[2], shape[2], 1])
    field = [np.zeros(math.prod(shape), np.float32) for _ in range(3)]
    S._splat(field, g, wn, strides)
    ref = np.zeros((3, math.prod(shape)))
    g0 = np.floor(g).astype(int)
    fr = g - g0
    for corner in np.ndindex(2, 2, 2):
        wt = np.prod([fr[:, k] if corner[k] else 1 - fr[:, k] for k in range(3)], axis=0)
        for c in range(3):
            np.add.at(ref[c], (g0 + corner) @ strides, wn[:, c] * wt)
    assert all(f.dtype == np.float32 for f in field)
    assert np.allclose(np.stack(field), ref, atol=1e-5)

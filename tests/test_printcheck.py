"""Printability check for STL files: size in mm, closed manifold, pieces, volume, solid vs hollow."""
import pytest

np = pytest.importorskip("numpy")      # the [print] extra (numpy + scipy)
pytest.importorskip("scipy")
from scripts.brandkit import printcheck as PC  # noqa: E402


def box(lo, hi, inward=False):
    """12 triangles of an axis-aligned box, wound outward (or inward, for a cavity wall)."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    t = v[np.array(f)]
    return t[:, ::-1] if inward else t


def test_stl_roundtrip(tmp_path):
    tris = box((0, 0, 0), (10, 20, 30))
    p = PC.write_stl(tmp_path / "b.stl", tris)
    back = PC.read_stl(p)
    assert back.shape == (12, 3, 3) and np.allclose(back, tris)


def test_read_stl_rejects_a_file_that_is_not_binary_stl(tmp_path):
    p = tmp_path / "a.stl"
    p.write_text("solid ascii\nendsolid ascii\n")
    with pytest.raises(ValueError, match="binary STL"):
        PC.read_stl(p)


def test_a_solid_box_is_solid_closed_one_piece_with_its_volume():
    r = PC.check(box((0, 0, 0), (40, 40, 60)))
    assert r["verdict"] == "SOLID"
    assert r["bad_edges"] == 0 and r["pieces"] == 1
    assert r["size"] == pytest.approx([40, 40, 60])
    assert r["volume_cm3"] == pytest.approx(96.0)
    assert not r["units_warning"]


def test_a_thin_walled_shell_is_hollow():
    # what Blender's voxel remesh makes of a TRELLIS.2 sheet: 2 mm walls around an empty cavity
    shell = np.concatenate([box((0, 0, 0), (40, 40, 60)), box((2, 2, 2), (38, 38, 58), inward=True)])
    r = PC.check(shell)
    assert r["verdict"] == "HOLLOW"
    assert r["inside_share"] < 0.25
    assert r["bad_edges"] == 0          # closed and manifold, yet still not printable as a solid


def test_a_model_in_metres_is_flagged_as_tiny():
    # Blender units are metres; a slicer reads STL numbers as mm, so 0.23 loads as 0.23 mm
    r = PC.check(box((0, 0, 0), (0.1, 0.1, 0.2286)))
    assert r["units_warning"]


def test_an_open_box_reports_bad_edges():
    r = PC.check(box((0, 0, 0), (10, 10, 10))[:-2])     # drop one face
    assert r["bad_edges"] > 0


def test_report_names_the_verdict_and_the_fix_for_hollow():
    shell = np.concatenate([box((0, 0, 0), (40, 40, 60)), box((2, 2, 2), (38, 38, 58), inward=True)])
    text = PC.format_report(PC.check(shell))
    assert "HOLLOW" in text and "--solid" in text

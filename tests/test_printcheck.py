"""Printability check for STL files: size in mm, closed manifold, pieces, volume, solid vs hollow."""
import pytest

np = pytest.importorskip("numpy")      # the [print] extra (numpy + scipy)
pytest.importorskip("scipy")
from scripts.brandkit import printcheck as PC  # noqa: E402
from tests.meshes import box, cup, sheet, tube  # noqa: E402


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


def test_an_stl_with_no_triangles_is_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match="no triangles"):
        PC.check_file(PC.write_stl(tmp_path / "empty.stl", np.zeros((0, 3, 3))))


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


# hollow means an empty space the outside can't reach. Rays that are mostly air called every open container HOLLOW
# (a clean cup, 8 % inside) and told the user to run --solid; a tube's bore made it UNCLEAR (2026-10-25)
def test_an_open_cup_is_solid_not_hollow():
    r = PC.check(cup())
    assert r["bad_edges"] == 0 and r["pieces"] == 1
    assert r["verdict"] == "SOLID"


def test_a_tube_with_a_through_bore_is_solid():
    assert PC.check(tube())["verdict"] == "SOLID"


def test_a_sheet_that_leaks_into_its_cavity_is_still_hollow():
    # TRELLIS.2 sheets often leak into the body: a small opening doesn't make the cavity part of the outside
    assert PC.check(sheet(hole_deg=12.0))["verdict"] == "HOLLOW"


def test_a_closed_sheet_is_hollow():
    assert PC.check(sheet())["verdict"] == "HOLLOW"

import pytest
Image = pytest.importorskip("PIL.Image")
from scripts.brandkit.montage import contact_sheet


def test_contact_sheet_2x2_dimensions(tmp_path):
    paths = []
    for i in range(4):
        p = tmp_path / f"v{i}.png"
        Image.new("RGB", (64, 48), (i * 10, 0, 0)).save(str(p))
        paths.append(p)
    out = contact_sheet(paths, tmp_path / "sheet.png", cols=2)
    assert out.exists()
    with Image.open(str(out)) as im:
        assert im.size == (128, 96)  # 2 cols * 64w, 2 rows * 48h


def test_contact_sheet_creates_parent_dir(tmp_path):
    src = tmp_path / "v0.png"
    Image.new("RGB", (10, 10)).save(str(src))
    out = contact_sheet([src], tmp_path / "nested" / "sheet.png", cols=2)
    assert out.exists()


def test_contact_sheet_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        contact_sheet([], tmp_path / "sheet.png")

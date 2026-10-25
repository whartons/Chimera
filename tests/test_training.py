import pytest
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.training import scan_dataset, build_config, TrainingError

def _brand(tmp_path, with_caption=True):
    (tmp_path / "training").mkdir()
    (tmp_path / "lora").mkdir()
    (tmp_path / "brand.yaml").write_text("name: B\nstyle: x\n")
    img = tmp_path / "training" / "a.png"; img.write_bytes(b"PNG")
    if with_caption:
        (tmp_path / "training" / "a.txt").write_text("a product photo")
    return tmp_path

def test_scan_dataset_pairs_images_and_captions(tmp_path):
    b = _brand(tmp_path)
    pairs = scan_dataset(b / "training")
    assert pairs == [(b / "training" / "a.png", "a product photo")]

def test_scan_dataset_errors_when_empty(tmp_path):
    (tmp_path / "training").mkdir()
    with pytest.raises(TrainingError):
        scan_dataset(tmp_path / "training")

def test_build_config_has_paths_and_base_model(tmp_path):
    b = _brand(tmp_path)
    m = load_manifest(b / "brand.yaml")
    cfg = build_config(brand="B", manifest=m, steps=100, backend="ai-toolkit")
    assert cfg["backend"] == "ai-toolkit"
    assert cfg["steps"] == 100
    # repo-relative, portable, no machine-specific absolute paths
    assert cfg["dataset_dir"] == "brands/B/training"
    assert cfg["output_dir"] == "brands/B/lora"
    assert cfg["base_model"] == m.defaults.model


def test_scan_dataset_reads_a_caption_saved_in_the_windows_code_page(tmp_path):
    # a caption saved as "ANSI" by Notepad (cp1252) raised an uncaught UnicodeDecodeError
    b = _brand(tmp_path, with_caption=False)
    (b / "training" / "a.txt").write_bytes("a café sign".encode("cp1252"))
    assert scan_dataset(b / "training")[0][1] == "a café sign"


def test_scan_dataset_reads_a_utf8_caption_with_a_bom(tmp_path):
    b = _brand(tmp_path, with_caption=False)
    (b / "training" / "a.txt").write_text("a café sign", encoding="utf-8-sig")
    assert scan_dataset(b / "training")[0][1] == "a café sign"


def test_scan_dataset_never_fails_on_a_caption_it_cannot_decode(tmp_path):
    b = _brand(tmp_path, with_caption=False)
    (b / "training" / "a.txt").write_bytes(b"a \x81\x8d sign")   # bytes cp1252 leaves undefined
    assert scan_dataset(b / "training")[0][1].startswith("a ")

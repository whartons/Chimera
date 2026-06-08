from __future__ import annotations
import pytest
from scripts.brandkit.scaffold import new_brand, lint_brand, print_lint


def _template(repo_root):
    """Build a minimal hermetic brands/_template/ so new_brand tests don't touch the real repo."""
    tpl = repo_root / "brands" / "_template"
    (tpl / "logos").mkdir(parents=True)
    (tpl / "products").mkdir()
    (tpl / "brand.yaml").write_text(
        'name: "Your Brand"\n'
        'style: "placeholder"\n'
        'defaults: { model: "flux2_dev_fp8mixed.safetensors" }\n'
        'logo: { default: null }\n',
        encoding="utf-8",
    )
    (tpl / "logos" / ".keep").write_text("", encoding="utf-8")
    return tpl


def _write_brand(repo_root, name, yaml_text):
    bdir = repo_root / "brands" / name
    bdir.mkdir(parents=True)
    (bdir / "brand.yaml").write_text(yaml_text, encoding="utf-8")
    return bdir


# --- new_brand -------------------------------------------------------------

def test_new_brand_copies_template_and_seeds_name(tmp_path):
    _template(tmp_path)
    dest = new_brand(tmp_path, "acme")
    assert dest == tmp_path / "brands" / "acme"
    assert dest.is_dir()
    # a template subfolder came across
    assert (dest / "logos").is_dir()
    assert (dest / "logos" / ".keep").exists()
    # name was seeded
    text = (dest / "brand.yaml").read_text(encoding="utf-8")
    assert 'name: "acme"' in text
    assert "Your Brand" not in text
    # the rest of the YAML survived the re.sub (regex only touches the name: line)
    assert 'style: "placeholder"' in text


def test_new_brand_cleans_up_on_seed_failure(tmp_path):
    # Build a template whose brand.yaml is a directory so read_text() raises during seeding.
    tpl = tmp_path / "brands" / "_template"
    (tpl / "brand.yaml").mkdir(parents=True)  # a dir, not a file -> read_text() fails
    with pytest.raises(Exception):
        new_brand(tmp_path, "halfbaked")
    # the partially-copied dest must be removed
    assert not (tmp_path / "brands" / "halfbaked").exists()


def test_new_brand_refuses_existing_dest(tmp_path):
    _template(tmp_path)
    (tmp_path / "brands" / "dup").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        new_brand(tmp_path, "dup")


@pytest.mark.parametrize("bad", ["a/b", "../evil", "a\\b", ""])
def test_new_brand_rejects_unsafe_names(tmp_path, bad):
    _template(tmp_path)
    with pytest.raises(ValueError):
        new_brand(tmp_path, bad)


def test_new_brand_missing_template_raises(tmp_path):
    # no _template created
    with pytest.raises(FileNotFoundError):
        new_brand(tmp_path, "acme")


# --- lint_brand ------------------------------------------------------------

def test_lint_good_brand_no_fail(tmp_path):
    _write_brand(tmp_path, "good",
                 'name: "Good Brand"\n'
                 'defaults: { model: z_image_turbo_nvfp4.safetensors }\n'
                 'logo: { default: null }\n')
    results = lint_brand(tmp_path, "good")
    assert any(lvl == "ok" and "loaded" in msg for lvl, msg in results)
    assert not any(lvl == "fail" for lvl, _ in results)


def test_lint_missing_logo_file_fails(tmp_path):
    _write_brand(tmp_path, "logobrand",
                 'name: "Logo Brand"\n'
                 'defaults: { model: z_image_turbo_nvfp4.safetensors }\n'
                 'logo: { default: "logos/primary.png" }\n')
    results = lint_brand(tmp_path, "logobrand")
    fails = [msg for lvl, msg in results if lvl == "fail"]
    assert fails and any("logo" in m.lower() for m in fails)


def test_lint_present_logo_file_ok(tmp_path):
    bdir = _write_brand(tmp_path, "logobrand",
                        'name: "Logo Brand"\n'
                        'defaults: { model: z_image_turbo_nvfp4.safetensors }\n'
                        'logo: { default: "logos/primary.png" }\n')
    (bdir / "logos").mkdir()
    (bdir / "logos" / "primary.png").write_bytes(b"PNG")
    results = lint_brand(tmp_path, "logobrand")
    assert not any(lvl == "fail" for lvl, _ in results)
    assert any(lvl == "ok" and "logo.default present" in msg for lvl, msg in results)


def test_lint_malformed_yaml_single_fail(tmp_path):
    _write_brand(tmp_path, "bad", "{}\n")  # no name -> ManifestError
    results = lint_brand(tmp_path, "bad")
    assert len(results) == 1
    assert results[0][0] == "fail"


def test_lint_warns_placeholder_name(tmp_path):
    _write_brand(tmp_path, "ph",
                 'name: "Your Brand"\n'
                 'defaults: { model: z_image_turbo_nvfp4.safetensors }\n')
    results = lint_brand(tmp_path, "ph")
    assert any(lvl == "warn" and "placeholder" in msg.lower() for lvl, msg in results)


def test_lint_warns_unknown_model_family(tmp_path):
    _write_brand(tmp_path, "sd",
                 'name: "SD Brand"\n'
                 'defaults: { model: sd15.ckpt }\n')
    results = lint_brand(tmp_path, "sd")
    assert any(lvl == "warn" and "sd15.ckpt" in msg for lvl, msg in results)


def test_lint_warns_watermark_without_logo(tmp_path):
    _write_brand(tmp_path, "wm",
                 'name: "WM Brand"\n'
                 'defaults: { model: z_image_turbo_nvfp4.safetensors }\n'
                 'logo: { default: null }\n'
                 'watermark: { enabled_default: true }\n')
    results = lint_brand(tmp_path, "wm")
    assert any(lvl == "warn" and "watermark" in msg.lower() for lvl, msg in results)


# --- print_lint ------------------------------------------------------------

def test_print_lint_returns_fail_count(capsys):
    results = [("ok", "loaded"), ("fail", "boom one"), ("warn", "careful"), ("fail", "boom two")]
    fails = print_lint("somebrand", results)
    assert fails == 2
    out = capsys.readouterr().out
    assert "somebrand" in out
    assert "[FAIL]" in out

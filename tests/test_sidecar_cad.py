from scripts.brandkit.sidecar import build_cad_meta, SCHEMA_VERSION


def test_cad_meta_primitive():
    m = build_cad_meta(mode="primitive", shape="tube", brand="acme", seed=5, template="primitive.py",
                       params={"radius": 10.0, "inner_radius": 6.0, "height": 30.0, "formats": ["step", "stl"]},
                       outputs=["acme_primitive_5.step", "acme_primitive_5.stl"], source=None,
                       timestamp="2026-06-14T09:00:00", freecad_version="1.1.1", pipeline_git_sha="abc123")
    assert m["schema"] == SCHEMA_VERSION and m["kind"] == "cad" and m["modality"] == "cad"
    assert m["mode"] == "primitive" and m["shape"] == "tube" and m["seed"] == 5
    assert m["template"] == "primitive.py" and m["source"] is None
    assert m["outputs"] == ["acme_primitive_5.step", "acme_primitive_5.stl"]
    assert m["provenance"]["freecad_version"] == "1.1.1"
    assert m["provenance"]["pipeline_git_sha"] == "abc123"
    assert len(m["provenance"]["params_signature"]) == 16


def test_cad_meta_convert_omits_absent_provenance():
    m = build_cad_meta(mode="convert", shape=None, brand=None, seed=1, template="convert.py",
                       params={"formats": ["stl"]}, outputs=["convert_1.stl"], source="part.step",
                       timestamp="t")
    assert m["shape"] is None and m["source"] == "part.step" and m["brand"] is None
    assert "freecad_version" not in m["provenance"]
    assert "pipeline_git_sha" not in m["provenance"]

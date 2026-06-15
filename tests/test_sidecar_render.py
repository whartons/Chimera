from scripts.brandkit.sidecar import build_render_meta, SCHEMA_VERSION


def test_render_meta_shape():
    m = build_render_meta(mode="mesh", brand="acme", seed=7, template="mesh_render.py",
                          params={"samples": 96, "res": [1080, 1080], "turntable": True},
                          outputs=["acme_mesh_7.png", "acme_mesh_7.mp4"], source="rover.glb",
                          timestamp="2026-06-13T12:00:00", blender_version="5.1.2",
                          pipeline_git_sha="abc123")
    assert m["schema"] == SCHEMA_VERSION and m["kind"] == "render" and m["modality"] == "render"
    assert m["mode"] == "mesh" and m["brand"] == "acme" and m["seed"] == 7
    assert m["template"] == "mesh_render.py" and m["source"] == "rover.glb"
    assert m["outputs"] == ["acme_mesh_7.png", "acme_mesh_7.mp4"]
    assert m["provenance"]["blender_version"] == "5.1.2"
    assert m["provenance"]["pipeline_git_sha"] == "abc123"
    assert len(m["provenance"]["params_signature"]) == 16


def test_render_meta_omits_absent_provenance():
    m = build_render_meta(mode="finish", brand=None, seed=1, template="mesh_finish.py",
                          params={}, outputs=["render_finish_1.glb"], source="m.glb",
                          timestamp="t")
    assert "blender_version" not in m["provenance"]
    assert "pipeline_git_sha" not in m["provenance"]
    assert m["brand"] is None

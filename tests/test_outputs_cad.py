from scripts.brandkit.outputs import media_subdir


def test_cad_extensions_route_to_3d():
    for ext in (".step", ".stp", ".iges", ".igs", ".brep"):
        assert media_subdir(ext) == "3d"


def test_existing_3d_and_image_routing_unchanged():
    assert media_subdir(".stl") == "3d"
    assert media_subdir(".glb") == "3d"
    assert media_subdir(".png") == "images"
    assert media_subdir(".xyz") == ""

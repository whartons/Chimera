import struct, json
from pathlib import Path
import pytest
from scripts.brandkit.mesh import read_glb_mesh, write_obj, write_stl, convert


def _minimal_glb(path):
    """A valid 1-triangle glTF-2.0 GLB (3 vec3 positions + 3 uint32 indices)."""
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    bin_data = b"".join(struct.pack("<3f", *v) for v in verts) + struct.pack("<3I", 0, 1, 2)
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(bin_data)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 12},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
    }
    jb = json.dumps(gltf).encode()
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bb = bin_data + b"\x00" * ((4 - len(bin_data) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(bb)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<I4s", len(jb), b"JSON") + jb
    out += struct.pack("<I4s", len(bb), b"BIN\x00") + bb
    Path(path).write_bytes(out)


def test_read_glb_mesh(tmp_path):
    p = tmp_path / "m.glb"; _minimal_glb(p)
    verts, faces = read_glb_mesh(p)
    assert len(verts) == 3 and tuple(verts[1]) == (1.0, 0.0, 0.0)
    assert faces == [(0, 1, 2)]


def test_convert_to_stl(tmp_path):
    p = tmp_path / "m.glb"; _minimal_glb(p)
    stl = convert(p, "stl")
    assert stl.suffix == ".stl" and stl.exists()
    data = stl.read_bytes()
    assert struct.unpack_from("<I", data, 80)[0] == 1        # 1 facet
    assert len(data) == 84 + 50                              # 80 header + 4 count + 1*(50)


def test_convert_to_obj(tmp_path):
    p = tmp_path / "m.glb"; _minimal_glb(p)
    obj = convert(p, "obj")
    lines = obj.read_text().splitlines()
    assert len([l for l in lines if l.startswith("v ")]) == 3
    assert "f 1 2 3" in lines                                # OBJ is 1-indexed


def test_convert_glb_is_noop(tmp_path):
    p = tmp_path / "m.glb"; _minimal_glb(p)
    assert convert(p, "glb") == p and convert(p, None) == p


def test_convert_unsupported_format_raises(tmp_path):
    p = tmp_path / "m.glb"; _minimal_glb(p)
    with pytest.raises(ValueError):
        convert(p, "fbx")


def test_write_helpers_directly(tmp_path):
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    faces = [(0, 1, 2)]
    stl = write_stl(verts, faces, tmp_path / "x.stl")
    assert stl.read_bytes()[80:84] == struct.pack("<I", 1)
    obj = write_obj(verts, faces, tmp_path / "x.obj")
    assert "f 1 2 3" in obj.read_text().splitlines()

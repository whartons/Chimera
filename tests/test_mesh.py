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


def _assemble_glb(gltf, bin_data, path):
    """Pack an arbitrary gltf dict + binary buffer into a GLB container (for malformed fixtures)."""
    jb = json.dumps(gltf).encode()
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bb = bin_data + b"\x00" * ((4 - len(bin_data) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(bb)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<I4s", len(jb), b"JSON") + jb
    out += struct.pack("<I4s", len(bb), b"BIN\x00") + bb
    Path(path).write_bytes(out)


def test_read_glb_non_indexed_raises(tmp_path):
    # a legal-glTF non-indexed mesh (no "indices") must fail with a clear message, not a bare KeyError
    bin_data = b"".join(struct.pack("<3f", *v) for v in [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}  # no "indices"
    p = tmp_path / "m.glb"; _assemble_glb(gltf, bin_data, p)
    with pytest.raises(ValueError, match="indexed"):
        read_glb_mesh(p)


def test_read_glb_missing_position_raises(tmp_path):
    bin_data = struct.pack("<3I", 0, 1, 2)
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 12}],
            "accessors": [{"bufferView": 0, "componentType": 5125, "count": 3, "type": "SCALAR"}],
            "meshes": [{"primitives": [{"attributes": {}, "indices": 0}]}]}  # no POSITION
    p = tmp_path / "m.glb"; _assemble_glb(gltf, bin_data, p)
    with pytest.raises(ValueError, match="POSITION"):
        read_glb_mesh(p)


def test_read_glb_bad_componenttype_raises(tmp_path):
    bin_data = b"".join(struct.pack("<3f", *v) for v in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]) \
        + struct.pack("<3I", 0, 1, 2)
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                            {"buffer": 0, "byteOffset": 36, "byteLength": 12}],
            "accessors": [{"bufferView": 0, "componentType": 9999, "count": 3, "type": "VEC3"},
                          {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
    p = tmp_path / "m.glb"; _assemble_glb(gltf, bin_data, p)
    with pytest.raises(ValueError, match="componentType"):
        read_glb_mesh(p)


def test_read_glb_no_meshes_raises(tmp_path):
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4}],
            "bufferViews": [], "accessors": [], "meshes": []}
    p = tmp_path / "m.glb"; _assemble_glb(gltf, b"\x00\x00\x00\x00", p)
    with pytest.raises(ValueError, match="no meshes"):
        read_glb_mesh(p)


def test_read_glb_truncated_accessor_raises(tmp_path):
    # an accessor claiming more vertices than the BIN chunk holds must fail loudly (the array.array
    # path would otherwise silently clamp and fabricate a malformed vertex) — clear error, not garbage
    bin_data = b"".join(struct.pack("<3f", *v) for v in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]) \
        + struct.pack("<3I", 0, 1, 2)
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                            {"buffer": 0, "byteOffset": 36, "byteLength": 12}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 99, "type": "VEC3"},  # claims 99
                          {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
    p = tmp_path / "m.glb"; _assemble_glb(gltf, bin_data, p)
    with pytest.raises(ValueError, match="past the"):
        read_glb_mesh(p)


def test_read_glb_uint16_indices(tmp_path):
    # exercise the array.array path for a non-4-byte component (UNSIGNED_SHORT indices)
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    bin_data = b"".join(struct.pack("<3f", *v) for v in verts) + struct.pack("<3H", 0, 1, 2)
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                            {"buffer": 0, "byteOffset": 36, "byteLength": 6}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                          {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
    p = tmp_path / "m.glb"; _assemble_glb(gltf, bin_data, p)
    v, faces = read_glb_mesh(p)
    assert len(v) == 3 and tuple(v[1]) == (1.0, 0.0, 0.0)
    assert faces == [(0, 1, 2)]


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



def test_a_multi_part_glb_is_refused_not_cut_to_its_first_part(tmp_path):
    import pytest
    from scripts.brandkit.mesh import convert
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    bin_data = b"".join(struct.pack("<3f", *v) for v in verts) + struct.pack("<3I", 0, 1, 2)
    prim = {"attributes": {"POSITION": 0}, "indices": 1}
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                            {"buffer": 0, "byteOffset": 36, "byteLength": 12}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                          {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"}],
            "meshes": [{"primitives": [prim]}, {"primitives": [prim]}]}
    p = tmp_path / "two.glb"
    _assemble_glb(gltf, bin_data, p)
    with pytest.raises(ValueError, match="2 mesh parts"):
        convert(p, "stl")



# --- glTF is +Y up, STL is +Z up in every slicer (2026-10-25 review) ------------------------------------
def _upright_glb(path):
    """A one-triangle GLB standing 2 units tall along glTF's up axis (+Y), facing glTF's front (+Z)."""
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
    bin_data = b"".join(struct.pack("<3f", *v) for v in verts) + struct.pack("<3I", 0, 1, 2)
    gltf = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(bin_data)}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36},
                            {"buffer": 0, "byteOffset": 36, "byteLength": 12}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                          {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
    _assemble_glb(gltf, bin_data, path)


def _stl_facets(path):
    data = Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    return [(struct.unpack_from("<3f", data, 84 + i * 50), [struct.unpack_from("<3f", data, 84 + i * 50 + 12 + j * 12)
                                                           for j in range(3)]) for i in range(n)]


def test_an_stl_from_a_glb_stands_up_in_a_slicer(tmp_path):
    # convert copied glTF's Y-up coordinates straight into STL, so `3d --format stl` lay on its back while
    # `render --mode finish --formats stl` (Blender converts) stood up
    p = tmp_path / "m.glb"
    _upright_glb(p)
    [(normal, tri)] = _stl_facets(convert(p, "stl"))
    assert [v[2] for v in tri] == [0.0, 0.0, 2.0]            # the 2-unit height is now Z
    assert all(v[1] == 0.0 for v in tri)
    assert normal == pytest.approx((0.0, -1.0, 0.0))         # glTF's front (+Z) is -Y in Z-up: still outward
    a, b, c = tri                                            # and the winding agrees with the stored normal
    u, w = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
    cross = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    assert sum(cross[i] * normal[i] for i in range(3)) > 0


def test_an_obj_from_a_glb_stays_y_up(tmp_path):
    p = tmp_path / "m.glb"
    _upright_glb(p)
    v = [line.split()[1:] for line in convert(p, "obj").read_text().splitlines() if line.startswith("v ")]
    assert [float(x[1]) for x in v] == [0.0, 0.0, 2.0]       # OBJ is Y-up by convention: unchanged

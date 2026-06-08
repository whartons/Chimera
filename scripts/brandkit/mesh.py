"""Convert a (shape-only) GLB mesh to STL or OBJ host-side — no external deps. ComfyUI's only
3D save node (SaveGLB) writes GLB; Hunyuan3D meshes are POSITION + indices only, which STL/OBJ
(the geometry formats for 3D printing / CAD) carry exactly. Parses the glTF-2.0 binary directly."""
from __future__ import annotations
import struct, json
from pathlib import Path

# glTF componentType -> (struct code, byte size)
_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
              5125: ("I", 4), 5126: ("f", 4)}
_TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb_mesh(path):
    """Return (vertices, faces) from the first primitive of a GLB: vertices = list of (x,y,z)
    floats, faces = list of (i,j,k) vertex-index triples."""
    data = Path(path).read_bytes()
    magic, _ver, _len = struct.unpack("<4sII", data[:12])
    if magic != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    g = bin_chunk = None
    off = 12
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<I4s", data, off)
        chunk = data[off + 8:off + 8 + clen]
        if ctype == b"JSON":
            g = json.loads(chunk)
        elif ctype.rstrip(b"\x00") == b"BIN":
            bin_chunk = chunk
        off += 8 + clen
    if g is None or bin_chunk is None:
        raise ValueError("GLB missing JSON or BIN chunk")
    bvs, accs = g["bufferViews"], g["accessors"]

    def read_accessor(idx):
        a = accs[idx]
        bv = bvs[a["bufferView"]]
        comp, size = _COMPONENT[a["componentType"]]
        n = _TYPE_COUNT[a["type"]]
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        count = a["count"]
        stride = bv.get("byteStride")
        if stride and stride != size * n:  # interleaved — read element by element
            return [struct.unpack_from("<" + comp * n, bin_chunk, base + i * stride)
                    for i in range(count)]
        flat = struct.unpack_from("<" + comp * (n * count), bin_chunk, base)  # one bulk read
        if n == 1:
            return list(flat)
        return [flat[i * n:(i + 1) * n] for i in range(count)]

    prim = g["meshes"][0]["primitives"][0]
    verts = read_accessor(prim["attributes"]["POSITION"])
    flat_idx = read_accessor(prim["indices"])
    faces = [(flat_idx[i], flat_idx[i + 1], flat_idx[i + 2])
             for i in range(0, len(flat_idx) - 2, 3)]
    return verts, faces


def write_obj(verts, faces, path):
    """Wavefront OBJ (1-indexed faces). Geometry only — no materials/UVs."""
    lines = [f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in verts]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(path)


def write_stl(verts, faces, path):
    """Binary STL (per-facet normals computed). Geometry only — the 3D-printing format."""
    out = bytearray()
    out += b"chimera hunyuan3d mesh".ljust(80, b" ")
    out += struct.pack("<I", len(faces))
    for a, b, c in faces:
        va, vb, vc = verts[a], verts[b], verts[c]
        ux, uy, uz = vb[0] - va[0], vb[1] - va[1], vb[2] - va[2]
        wx, wy, wz = vc[0] - va[0], vc[1] - va[1], vc[2] - va[2]
        nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
        ln = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        out += struct.pack("<3f", nx / ln, ny / ln, nz / ln)
        out += struct.pack("<9f", *va, *vb, *vc)
        out += struct.pack("<H", 0)
    Path(path).write_bytes(out)
    return Path(path)


def convert(glb_path, fmt):
    """Convert a GLB to `fmt` ('glb'|'stl'|'obj'); returns the resulting path (sibling, swapped
    extension). 'glb' is a no-op (returns the input path unchanged)."""
    glb_path = Path(glb_path)
    fmt = (fmt or "glb").lower()
    if fmt == "glb":
        return glb_path
    if fmt not in ("stl", "obj"):
        raise ValueError(f"unsupported 3d format {fmt!r} (expected glb|stl|obj)")
    verts, faces = read_glb_mesh(glb_path)
    dest = glb_path.with_suffix("." + fmt)
    return write_stl(verts, faces, dest) if fmt == "stl" else write_obj(verts, faces, dest)

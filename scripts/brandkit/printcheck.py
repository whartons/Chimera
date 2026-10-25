"""Is an STL ready to slice? Size (STL has no units: every slicer reads the numbers as millimetres), a closed
manifold surface, the number of separate pieces, the volume, and SOLID vs HOLLOW.

The hollow test fires horizontal rays through the model (front to back and side to side, at several heights) and
pairs the surface crossings into inside runs. The empty gaps between runs only count against the model when they are
sealed: hardly any direction from a gap's middle reaches the outside without hitting the surface. A hollow shell
(what a voxel remesh of a TRELLIS.2 sheet gives) is inside only for its thin walls around a sealed cavity, even when
it leaks a little; a cup's or a tube's empty middle opens to the outside, so it doesn't count, and they're solid.
Needs numpy + scipy (the [print] extra); imported lazily by the render CLI."""
from __future__ import annotations
import struct
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

_REC = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
TINY_MM = 10.0             # a printable model under 10 mm on its longest side is almost always a units mistake
GRID_CELLS = 256           # surface grid for the sealed-gap test: the longest side in cells
OPEN_SHARE = 0.05          # a gap whose middle sees the outside in more directions than this is open (a cup's middle
                           # ~12 %, a tube's bore ~12 %, a sheet's cavity behind a leak well under 1 %)


def read_stl(path) -> np.ndarray:
    """Binary STL -> (N, 3, 3) float64 triangles."""
    data = Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else -1
    if n < 0 or len(data) != 84 + 50 * n:
        raise ValueError(f"{path} is not a binary STL (or it is truncated)")
    return np.frombuffer(data, dtype=_REC, count=n, offset=84)["v"].astype(np.float64)


def write_stl(path, tris, header=b"chimera") -> Path:
    """(N, 3, 3) triangles -> binary STL with per-facet normals."""
    tris = np.asarray(tris, dtype=np.float32)
    nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(tris), dtype=_REC)
    rec["n"], rec["v"] = nrm, tris
    with open(path, "wb") as f:
        f.write(header[:80].ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        f.write(rec.tobytes())
    return Path(path)


def _crossings(orig, d, v0, e1, e2):
    """Moller-Trumbore against every triangle: sorted distances where the ray crosses the surface."""
    p = np.cross(d, e2)
    det = (e1 * p).sum(1)
    ok = np.abs(det) > 1e-12
    inv = 1.0 / np.where(ok, det, 1.0)
    s = orig - v0
    u = (s * p).sum(1) * inv
    q = np.cross(s, e1)
    v = (q * d).sum(1) * inv
    t = (e2 * q).sum(1) * inv
    return np.sort(t[ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)])


def _surface_points(tris, step):
    """Points at most `step` apart over every triangle (corners included)."""
    out = [tris.reshape(-1, 3)]
    n = np.ceil(np.max(np.linalg.norm(tris[:, [1, 2, 0]] - tris, axis=2), axis=1) / step).astype(int)
    for k in np.unique(n[n > 1]):
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
        keep = i + j <= k
        a, b = i[keep] / k, j[keep] / k
        t = tris[n == k]
        out.append((t[:, None, 0] * (1 - a - b)[None, :, None] + t[:, None, 1] * a[None, :, None]
                    + t[:, None, 2] * b[None, :, None]).reshape(-1, 3))
    return np.concatenate(out)


def _surface_grid(tris, lo, size):
    """The surface as a voxel grid, one cell thicker so rays can't slip between diagonal cells: (grid, cell, pad)."""
    cell = max(float(size.max()) / GRID_CELLS, 1e-6)
    pad = 2
    shape = np.ceil(size / cell).astype(int) + 1 + 2 * pad
    idx = np.floor((_surface_points(tris, cell / 2) - lo) / cell).astype(int) + pad
    grid = np.zeros(tuple(shape), bool)
    grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return ndimage.binary_dilation(grid), cell, pad


def _fibonacci_dirs(n=96):
    i = np.arange(n) + 0.5
    polar, turn = np.arccos(1 - 2 * i / n), np.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(turn) * np.sin(polar), np.sin(turn) * np.sin(polar), np.cos(polar)], 1)


_DIRS = _fibonacci_dirs()


def _open_share(grid, p):
    """Share of directions from grid point `p` that leave the grid before they hit the surface."""
    shape = np.array(grid.shape)
    steps = np.arange(1, 2 * int(np.linalg.norm(shape)) + 2) * 0.5
    q = p[None, None, :] + _DIRS[:, None, :] * steps[None, :, None]
    inside = np.all((q >= 0) & (q <= shape - 1), axis=2)
    qi = np.clip(np.floor(q).astype(int), 0, shape - 1)
    hit = grid[qi[..., 0], qi[..., 1], qi[..., 2]] & inside
    first_hit = np.where(hit.any(1), hit.argmax(1), np.inf)
    first_out = np.where((~inside).any(1), (~inside).argmax(1), np.inf)
    return float((first_out < first_hit).mean())


def check(tris) -> dict:
    """Printability report for (N, 3, 3) triangles (see module docstring). JSON-serializable."""
    tris = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    if not len(tris):        # numpy's "zero-size array to reduction operation" reached the user (2026-10-25)
        raise ValueError("the STL has no triangles")
    pts = tris.reshape(-1, 3)
    lo, hi = pts.min(0), pts.max(0)
    size = hi - lo
    # closed + manifold: after welding identical corners, every edge belongs to exactly two triangles
    _, vid = np.unique(pts.astype(np.float32), axis=0, return_inverse=True)
    vid = vid.reshape(-1, 3)
    e = np.sort(np.concatenate([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]]), axis=1)
    n_v = int(vid.max()) + 1
    _, cnt = np.unique(e[:, 0] * n_v + e[:, 1], return_counts=True)
    pieces = int(connected_components(coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n_v, n_v)),
                                      directed=False)[0])
    vol = float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6.0)
    # solid vs hollow
    v0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    jitter = np.array([0.000123, 0.000271, 0.000347]) * max(float(size.max()), 1e-9)   # miss shared edges
    grid, cell, pad = _surface_grid(tris, lo, size)
    shares, runs = [], []
    for hz in (0.2, 0.35, 0.5, 0.65, 0.8):
        for axis in (0, 1):                       # rays along +Y and along +X
            other = 1 - axis
            for g in (0.35, 0.45, 0.5, 0.55, 0.65):
                o = lo.copy()
                o[axis] = lo[axis] + g * size[axis]
                o[other] = lo[other] - 0.05 * size[other] - 1.0
                o[2] = lo[2] + hz * size[2]
                d = np.zeros(3)
                d[other] = 1.0
                o = o + jitter
                t = _crossings(o, d, v0, e1, e2)
                if len(t) < 2 or len(t) % 2:
                    continue                      # missed the model, or grazed an edge
                inside = t[1::2] - t[0::2]
                # a gap between two inside runs is a cavity only when it's sealed off from the outside: a
                # cup's middle or a tube's bore made a clean solid read HOLLOW / UNCLEAR (2026-10-25)
                sealed = sum(b - a for a, b in zip(t[1:-1:2], t[2::2], strict=True)
                             if _open_share(grid, (o + d * (a + b) / 2 - lo) / cell + pad) < OPEN_SHARE)
                shares.append(float(inside.sum() / (inside.sum() + sealed)))
                runs.extend(inside.tolist())
    share = float(np.median(shares)) if shares else None
    if share is None:
        verdict = "UNCLEAR"
    elif share >= 0.5:
        verdict = "SOLID"
    elif share < 0.25:
        verdict = "HOLLOW"
    else:
        verdict = "UNCLEAR"
    return {"triangles": int(len(tris)), "size": [round(float(s), 3) for s in size],
            "units_warning": bool(size.max() < TINY_MM), "bad_edges": int((cnt != 2).sum()),
            "pieces": pieces, "volume_cm3": round(abs(vol) / 1000.0, 3), "inward": vol < 0,
            "inside_share": None if share is None else round(share, 3),
            "median_inside_run": round(float(np.median(runs)), 3) if runs else None,
            "rays": len(shares), "verdict": verdict}


def check_file(path) -> dict:
    return check(read_stl(path))


def format_report(r: dict, name: str = "") -> str:
    """Human summary of check(); names the fix for each problem."""
    x, y, z = r["size"]
    lines = [f"print check{(' ' + name) if name else ''}: {x:.1f} x {y:.1f} x {z:.1f} mm, "
             f"{r['volume_cm3']:.1f} cm3, {r['pieces']} piece(s), verdict {r['verdict']}"]
    if r["units_warning"]:
        lines.append(f"  units: the longest side is {max(r['size']):.3f}, which a slicer reads as mm; the file is "
                     "probably in metres. Re-export with --scale-mm <size>")
    if r["bad_edges"]:
        lines.append(f"  not closed: {r['bad_edges']} edges are not shared by exactly two triangles")
    if r["pieces"] > 1:
        lines.append(f"  {r['pieces']} separate pieces (a single print expects 1)")
    if r["verdict"] == "HOLLOW":
        lines.append(f"  hollow: rays through the model are only {r['inside_share']:.0%} material (thin walls around "
                     "a sealed, empty cavity). AI meshes like TRELLIS.2 need --solid, not --watertight")
    elif r["verdict"] == "UNCLEAR":
        lines.append("  solid-vs-hollow unclear: look at a cut-away view before printing")
    return "\n".join(lines)

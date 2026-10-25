"""Rebuild a thin, double-sided AI mesh as one printable solid.

TRELLIS.2 and Pixal3D output a paper-thin sheet (an outer and an inner surface ~0.6 mm apart at trophy size) with
layers stacked inside it (a shirt over the body), not a solid. A voxel remesh turns that into a hollow shell. This:
  1. voxelizes every triangle, closes gaps (dilation by a radius r), flood-fills the outside -> a robust solid;
     r is picked automatically: a leak into the body cavity leaves it hollow, so sealing it shows up as a big
     jump in solid volume; r is the radius right after the last such jump (bigger radii only web concave gaps
     shut, a few % a step), or the smallest radius when nothing jumps;
  2. keeps only the OUTER skin: triangles whose front lies outside that solid (the sheet's inner side and buried
     layers go);
  3. splats the skin's area-weighted normals (Phong-interpolated, creases kept) onto the grid and solves a Poisson
     equation with FFTs for an inside/outside indicator, then marching cubes + light Taubin smoothing.
The global solve bridges the seams where layers meet; every per-voxel inside/outside rule we tried left artefacts
(contour rings, specks, serrated seams). Distances are in voxels and the voxel is 1/762 of the longest side (down to
0.05 mm), so the settings proven on a 228.6 mm trophy at 0.3 mm (close 1.2-4 mm, splat 0.35 mm) scale with the
print. A compact print gets a coarser voxel, so the grid stays under MAX_VOXELS (~16 B a voxel at the peak, about
2 GB). Input and output are in mm. Needs numpy, scipy and
scikit-image (the [print] extra); a couple of minutes on the CPU for a 230 mm figure."""
from __future__ import annotations
import math

import numpy as np
from scipy import fft, ndimage, sparse
from skimage import measure

from .printcheck import read_stl, write_stl

MIN_VOXEL_MM = 0.05                      # a resin printer's pixel; below ~38 mm the distances stop shrinking
VOXELS_PER_LONGEST_SIDE = 762            # 228.6 mm -> 0.3 mm, the proven setting
MAX_VOXELS = 120_000_000                 # ~2 GB at the peak (~16 B a voxel); a compact print gets a coarser voxel
CLOSE_RADII_VOX = (4.0, 16 / 3, 20 / 3, 8.0, 32 / 3, 40 / 3)   # 1.2 .. 4.0 mm at 0.3 mm voxels
SIGMA_VOX = 0.35 / 0.3                   # normal splat width
FRONT_VOX = 0.5 / 0.3                    # how far in front of a face to test "outside"
PAD_VOX = 16                             # empty border (the FFT is periodic)
LEAK_JUMP = 1.2                          # a sealed leak adds 50-470 % solid in one step; webbing gaps adds 2-9 %
CHUNK_POINTS = 2_000_000                 # surface samples per batch
NO_VOLUME = ("no closed volume to fill: the mesh is an open surface (a flat face or a single-sided sheet), so it has "
             "no inside. --solid needs a closed surface or a double-sided sheet")


def pick_close_radius(radii, volumes):
    """The closing radius from the solid volume each candidate radius gives (ascending radii): the one right
    after the last big jump (a leak sealing), else the smallest (no leak). Choosing "within 97 % of the largest"
    over-closed a model whose volume kept creeping up after the seal (2026-10)."""
    pick = radii[0]
    for i in range(1, len(radii)):
        before, after = volumes[i - 1], volumes[i]
        if (before <= 0 < after) or (before > 0 and after / before >= LEAK_JUMP):
            pick = radii[i]
    return pick


def auto_voxel_mm(longest_mm: float) -> float:
    """Voxel size for a print whose longest side is `longest_mm`: 1/762 of it, so every distance in voxels scales
    with the print, as the sheet's thickness and its leaks do. A 0.3 mm floor kept the closing radii at 1.2-4 mm
    on any print, which webbed a 2 mm slot shut on a 40 mm miniature (2026-10-25)."""
    return max(MIN_VOXEL_MM, float(longest_mm) / VOXELS_PER_LONGEST_SIDE)


def grid_shape(size_mm, vox) -> tuple:
    """The FFT-friendly grid for a model of bounding size `size_mm` (x, y, z) at `vox` mm, padding included."""
    span = np.asarray(size_mm, dtype=np.float64) + 2 * PAD_VOX * vox
    return tuple(fft.next_fast_len(int(s), real=True) for s in np.ceil(span / vox).astype(int) + 1)


def voxel_for_size(size_mm) -> float:
    """auto_voxel_mm for the longest side, coarsened until the grid holds at most MAX_VOXELS. The voxel followed
    the longest side only, so a compact 228.6 mm print (a bust, a vase) got an 800^3 grid: ~27 GB (2026-10-25)."""
    size = np.asarray(size_mm, dtype=np.float64)
    vox = auto_voxel_mm(size.max())
    while (n := math.prod(grid_shape(size, vox))) > MAX_VOXELS:
        vox *= max((n / MAX_VOXELS) ** (1 / 3), 1.01)
    return vox


def _within_sq(r) -> int:
    """The largest squared voxel distance d with sqrt(d) <= r: what a float `distance <= r` test keeps."""
    m = int(math.floor(r * r))
    while math.sqrt(m + 1) <= r:
        m += 1
    while m > 0 and math.sqrt(m) > r:
        m -= 1
    return m


def _sq_dist(free, r):
    """Squared distance in voxels from every voxel to the nearest `free` one, exact up to r and capped just above
    it: a `<= r` / `> r` test on it matches scipy's distance_transform_edt at ~6 B a voxel, where the EDT's int32
    feature transform and float64 temporaries took ~50 (2026-10-25). A separable min over the offsets |k| <= r,
    one axis at a time."""
    cap = _within_sq(r) + 1
    dt = np.uint16 if 2 * cap < 2 ** 16 else np.uint32
    d = np.where(free, dt(0), dt(cap))
    for ax in range(3):
        src = np.moveaxis(d, ax, 0)
        out = src.copy()
        for k in range(1, int(r) + 1):
            kk = dt(k * k)
            np.minimum(out[:-k], src[k:] + kk, out=out[:-k])
            np.minimum(out[k:], src[:-k] + kk, out=out[k:])
        np.minimum(out, dt(cap), out=out)
        d = np.moveaxis(out, 0, ax)
        del src, out
    return d


def _closed(near_sq, r):
    """The closing at radius r (voxels) from the squared distance to the surface: dilate, fill the enclosed
    cavities, erode."""
    m = _within_sq(r)
    outside = ndimage.binary_fill_holes(near_sq <= m)
    np.logical_not(outside, out=outside)
    return _sq_dist(outside, r) > m


def _splat(field, g, wn, strides):
    """Add the vectors `wn` (P, 3) at grid coordinates `g` (P, 3) trilinearly into `field` (three flat float32
    grids). Each corner's shares are summed per touched voxel first, so the temporaries are the size of the samples:
    float64 grids and a whole-grid bincount per corner were most of the peak memory (2026-10-25)."""
    g0 = np.floor(g).astype(np.int64)
    fr = g - g0
    base, inv = np.unique(g0 @ strides, return_inverse=True)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                wt = ((fr[:, 0] if dx else 1 - fr[:, 0]) * (fr[:, 1] if dy else 1 - fr[:, 1])
                      * (fr[:, 2] if dz else 1 - fr[:, 2]))
                at = base + (dx * strides[0] + dy * strides[1] + dz)
                for c in range(3):
                    field[c][at] += np.bincount(inv, weights=wn[:, c] * wt, minlength=len(base))


def _sample(tris, step, chunk=None):
    """Points on every triangle, at most `step` apart along the two edges at the corner opposite its longest
    edge, in batches of about `chunk` points: (points, triangle ids, per-point weights summing to 1 per triangle,
    barycentric coordinates in the triangle's own corner order). The subdivision was capped at 64, so a big CAD or
    decimated face was dotted every few voxels: a dimpled flat face and a fake leak (2026-10-25). Splitting each
    edge on its own keeps a long thin sliver to a row of points instead of a 64^2 grid; the batches keep memory
    flat."""
    chunk = chunk or CHUNK_POINTS
    o = (np.argmax(np.linalg.norm(tris[:, [1, 2, 0]] - tris, axis=2), axis=1) + 2) % 3
    rows = np.arange(len(tris))
    a = tris[rows, o]
    ab, ac = tris[rows, (o + 1) % 3] - a, tris[rows, (o + 2) % 3] - a
    nu = np.maximum(np.ceil(np.linalg.norm(ab, axis=1) / step), 1).astype(np.int64)
    nv = np.maximum(np.ceil(np.linalg.norm(ac, axis=1) / step), 1).astype(np.int64)
    pairs, group = np.unique(np.stack([nu, nv], axis=1), axis=0, return_inverse=True)
    group = group.ravel()
    order = np.argsort(group, kind="stable")
    bounds = np.searchsorted(group[order], np.arange(len(pairs) + 1))
    buf, size = [], 0
    for g, (n_u, n_v) in enumerate(pairs):
        i, j = np.meshgrid(np.arange(n_u + 1), np.arange(n_v + 1), indexing="ij")
        keep = i * n_v + j * n_u <= n_u * n_v                 # i/n_u + j/n_v <= 1, exactly
        u, v = i[keep] / n_u, j[keep] / n_v
        lattice = np.stack([1.0 - u - v, u, v], axis=1)       # weights of corners o, o+1, o+2
        sel_all = order[bounds[g]:bounds[g + 1]]
        for s in range(0, len(sel_all), max(1, chunk // len(u))):
            sel = sel_all[s:s + max(1, chunk // len(u))]
            p = a[sel, None] + ab[sel, None] * u[None, :, None] + ac[sel, None] * v[None, :, None]
            ids = np.repeat(sel, len(u))
            bary = np.empty((len(ids), 3))
            k = np.arange(len(ids))
            for c in range(3):
                bary[k, (o[ids] + c) % 3] = np.tile(lattice[:, c], len(sel))
            buf.append((p.reshape(-1, 3), ids, np.full(len(ids), 1.0 / len(u)), bary))
            size += len(ids)
            if size >= chunk:
                yield tuple(np.concatenate(x) for x in zip(*buf, strict=True))
                buf, size = [], 0
    if buf:
        yield tuple(np.concatenate(x) for x in zip(*buf, strict=True))


def solidify(tris, *, vox, close_mm=None, smooth_normals=True, crease_deg=35.0, taubin=6):
    """(N, 3, 3) triangles in mm -> (M, 3, 3) triangles of one closed solid, plus an info dict (close_mm,
    solid_cm3_by_radius, skin_faces, volume_cm3, voxel_mm). `close_mm` fixes the closing radius instead of
    choosing it."""
    tris = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    cr = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    a2 = np.linalg.norm(cr, axis=1)
    ok = a2 > 1e-12
    if not ok.any():         # numpy's "zero-size array to reduction operation" reached the user (2026-10-25)
        raise ValueError("no triangles to solidify: the mesh is empty or every face has zero area")
    tris, fn, area = tris[ok], cr[ok] / a2[ok, None], 0.5 * a2[ok]
    lo = tris.reshape(-1, 3).min(axis=0) - PAD_VOX * vox
    shape = grid_shape(np.ptp(tris.reshape(-1, 3), axis=0), vox)

    def vox_of(p):
        return np.clip(np.floor((p - lo) / vox).astype(np.int64), 0, np.array(shape) - 1)

    # 1. a robust solid from every triangle; pick the closing radius
    surf = np.zeros(shape, dtype=bool)
    for pts, _, _, _ in _sample(tris, vox * 0.5):
        iv = vox_of(pts)
        surf[iv[:, 0], iv[:, 1], iv[:, 2]] = True
    del iv, pts
    radii = [close_mm / vox] if close_mm else list(CLOSE_RADII_VOX)
    near = _sq_dist(surf, max(radii))           # squared distance to the surface: every radius's dilation
    del surf
    solid_vox = []
    for rr in radii:
        inside = _closed(near, rr)
        solid_vox.append(int(inside.sum()))
    r = pick_close_radius(radii, solid_vox)
    if r != radii[-1]:
        inside = _closed(near, r)
    del near
    if not inside.any():
        raise ValueError(NO_VOLUME)
    # voxels of the solid, to orient the indicator (a sample: the old argmax of a float depth map cost 4 B a voxel)
    inner = np.flatnonzero(inside.ravel()[::997]) * 997
    if not len(inner):
        inner = np.flatnonzero(inside)

    # 2. the outer skin: faces whose front is outside the solid
    probe = vox_of(tris.mean(axis=1) + fn * FRONT_VOX * vox)
    outer = ~inside[probe[:, 0], probe[:, 1], probe[:, 2]]
    del inside
    skin, skin_n, skin_a = tris[outer], fn[outer], area[outer]
    if not len(skin):
        raise ValueError("no outer surface found (is the mesh empty or inside out?)")

    # 3. Poisson reconstruction from the skin's oriented samples
    corner = None
    if smooth_normals:
        _, vid = np.unique(np.round(skin.reshape(-1, 3) / 1e-4).astype(np.int64), axis=0, return_inverse=True)
        vid = vid.reshape(-1, 3)
        # vertex normals weighted by each face's corner angle, not its area: at a box corner the big top face
        # outweighed the sides, so no crease was seen and Phong normals tilted across the whole face, doming a
        # flat CAD face 0.25 mm (2026-10-25); on an even AI mesh the two weightings agree
        e1 = np.roll(skin, -1, axis=1) - skin
        e2 = np.roll(skin, 1, axis=1) - skin
        ang = np.arccos(np.clip((e1 * e2).sum(-1) / np.maximum(np.linalg.norm(e1, axis=-1)
                                                              * np.linalg.norm(e2, axis=-1), 1e-12), -1, 1))
        del e1, e2
        vn = np.zeros((vid.max() + 1, 3))
        for k in range(3):
            np.add.at(vn, vid[:, k], skin_n * ang[:, k, None])
        vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
        corner = vn[vid]
        crease = (corner * skin_n[:, None, :]).sum(-1) < np.cos(np.radians(crease_deg))
        corner = np.where(crease[..., None], skin_n[:, None, :], corner)
    strides = np.array([shape[1] * shape[2], shape[2], 1])
    field = [np.zeros(math.prod(shape), dtype=np.float32) for _ in range(3)]
    for pts, pid, w, bary in _sample(skin, vox * 0.5):
        if corner is None:
            nrm = skin_n[pid]
        else:
            nrm = (corner[pid] * bary[:, :, None]).sum(1)
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        _splat(field, (pts - lo) / vox, nrm * (skin_a[pid] * w)[:, None], strides)
    del nrm
    # the Poisson solve in float32/complex64, in place where it can be: one component's spectrum at a time
    kx = (2 * np.pi * fft.fftfreq(shape[0], d=vox)).astype(np.float32)[:, None, None]
    ky = (2 * np.pi * fft.fftfreq(shape[1], d=vox)).astype(np.float32)[None, :, None]
    kz = (2 * np.pi * fft.rfftfreq(shape[2], d=vox)).astype(np.float32)[None, None, :]
    div = None
    for c, kc in enumerate((kx, ky, kz)):
        f = fft.rfftn(field[c].reshape(shape), workers=-1)
        field[c] = None
        f *= (1j * kc).astype(np.complex64)
        if div is None:
            div = f
        else:
            div += f
        del f
    k2 = kx ** 2 + ky ** 2 + kz ** 2
    gauss = k2 * np.float32(-0.5 * (SIGMA_VOX * vox) ** 2)
    np.exp(gauss, out=gauss)
    div *= gauss                                           # chi_hat = div * gauss / -k2
    del gauss
    k2[0, 0, 0] = 1.0
    div /= k2
    np.negative(div, out=div)
    div[0, 0, 0] = 0
    del k2
    chi = fft.irfftn(div, s=shape, workers=-1, overwrite_x=True)
    del div
    at_skin = wsum = 0.0                                   # iso: chi's area-weighted mean on the skin
    for pts, pid, w, _ in _sample(skin, vox * 0.5):
        wt = skin_a[pid] * w
        at_skin += float(ndimage.map_coordinates(chi, ((pts - lo) / vox).T, order=1, mode="nearest") @ wt)
        wsum += float(wt.sum())
    iso = at_skin / wsum
    if float(chi.ravel()[inner].mean()) < iso:             # make "inside" the high side
        np.negative(chi, out=chi)
        iso = -iso
    verts, faces, _, _ = measure.marching_cubes(chi, level=iso, spacing=(vox, vox, vox))
    del chi
    # an open surface has no inside: the indicator never separates one, and the level set runs off the grid (a
    # flat square came back as a 67 mm sheet with 1332 open edges and no error, 2026-10-25)
    if (verts.min(axis=0) < vox).any() or (verts.max(axis=0) > (np.array(shape) - 2) * vox).any():
        raise ValueError(NO_VOLUME)
    verts += lo
    if taubin:
        # Taubin (lambda/mu) smoothing evens out the last voxel steps without shrinking the figure
        nv = len(verts)
        ij = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        adj = sparse.coo_matrix((np.ones(len(ij)), (ij[:, 0], ij[:, 1])), shape=(nv, nv)).tocsr()
        adj = ((adj + adj.T) > 0).astype(np.float64)
        avg = sparse.diags(1.0 / np.maximum(np.asarray(adj.sum(axis=1)).ravel(), 1)) @ adj
        for _ in range(taubin):
            verts = verts + 0.5 * (avg @ verts - verts)
            verts = verts - 0.53 * (avg @ verts - verts)
    out = verts[faces]
    vol = float(np.einsum("ij,ij->i", out[:, 0], np.cross(out[:, 1], out[:, 2])).sum() / 6.0)
    if vol < 0:                                            # wind the faces outward
        out, vol = out[:, ::-1], -vol
    info = {"voxel_mm": round(vox, 4), "close_mm": round(r * vox, 3),
            "solid_cm3_by_radius": {round(rr * vox, 3): round(v * vox ** 3 / 1000.0, 3)
                                    for rr, v in zip(radii, solid_vox, strict=True)},
            "skin_faces": int(outer.sum()), "input_faces": int(len(tris)), "faces": int(len(out)),
            "volume_cm3": round(vol / 1000.0, 3)}
    return out, info


def solidify_file(src, dst, *, vox=None, close_mm=None, **kw) -> dict:
    """STL (mm) -> solid STL (mm). The voxel size follows the model's size (voxel_for_size) unless `vox` is
    given."""
    tris = read_stl(src)
    if vox is None and len(tris):
        vox = voxel_for_size(np.ptp(tris.reshape(-1, 3), axis=0))
    out, info = solidify(tris, vox=vox, close_mm=close_mm, **kw)
    write_stl(dst, out, header=b"chimera solidify (mm)")
    # no "output" path: the info lands in the sidecar, and the temp file's full path broke its no-local-paths
    # rule and named the user's home folder (2026-10-25)
    return info

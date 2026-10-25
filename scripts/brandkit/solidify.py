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
(contour rings, specks, serrated seams). Distances are in voxels, so the settings proven on a 228.6 mm trophy at
0.3 mm (close 1.2-4 mm, splat 0.35 mm) scale with the print. Input and output are in mm. Needs numpy, scipy and
scikit-image (the [print] extra); about 3 minutes and a few GB of RAM for a 230 mm figure at 0.3 mm."""
from __future__ import annotations
from pathlib import Path

import numpy as np
from scipy import fft, ndimage, sparse
from skimage import measure

from .printcheck import read_stl, write_stl

MIN_VOXEL_MM = 0.3                       # finer than a 0.4 mm nozzle buys nothing
VOXELS_PER_LONGEST_SIDE = 762            # 228.6 mm -> 0.3 mm, the proven setting
CLOSE_RADII_VOX = (4.0, 16 / 3, 20 / 3, 8.0, 32 / 3, 40 / 3)   # 1.2 .. 4.0 mm at 0.3 mm voxels
SIGMA_VOX = 0.35 / 0.3                   # normal splat width
FRONT_VOX = 0.5 / 0.3                    # how far in front of a face to test "outside"
PAD_VOX = 16                             # empty border (the FFT is periodic)
LEAK_JUMP = 1.2                          # a sealed leak adds 50-470 % solid in one step; webbing gaps adds 2-9 %


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
    """Voxel size for a print whose longest side is `longest_mm`."""
    return max(MIN_VOXEL_MM, float(longest_mm) / VOXELS_PER_LONGEST_SIDE)


def _sample(tris, step):
    """Points on every triangle spaced <= step; their triangle ids, per-point weights (summing to 1 per
    triangle) and barycentric coordinates."""
    e = np.stack([np.linalg.norm(tris[:, 1] - tris[:, 0], axis=1), np.linalg.norm(tris[:, 2] - tris[:, 1], axis=1),
                  np.linalg.norm(tris[:, 0] - tris[:, 2], axis=1)], axis=1).max(axis=1)
    n_sub = np.clip(np.ceil(e / step).astype(int), 1, 64)
    pts, ids, wts, bary = [], [], [], []
    for n in np.unique(n_sub):
        sel = np.nonzero(n_sub == n)[0]
        t = tris[sel]
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = (i + j) <= n
        u, v = i[keep] / n, j[keep] / n
        w = 1.0 - u - v
        p = t[:, None, 0] * w[None, :, None] + t[:, None, 1] * u[None, :, None] + t[:, None, 2] * v[None, :, None]
        pts.append(p.reshape(-1, 3))
        ids.append(np.repeat(sel, len(u)))
        wts.append(np.full(len(sel) * len(u), 1.0 / len(u)))
        bary.append(np.tile(np.stack([w, u, v], axis=1), (len(sel), 1)))
    return np.concatenate(pts), np.concatenate(ids), np.concatenate(wts), np.concatenate(bary)


def solidify(tris, *, vox, close_mm=None, smooth_normals=True, crease_deg=35.0, taubin=6):
    """(N, 3, 3) triangles in mm -> (M, 3, 3) triangles of one closed solid, plus an info dict (close_mm,
    solid_cm3_by_radius, skin_faces, volume_cm3, voxel_mm). `close_mm` fixes the closing radius instead of
    choosing it."""
    tris = np.asarray(tris, dtype=np.float64)
    cr = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    a2 = np.linalg.norm(cr, axis=1)
    ok = a2 > 1e-12
    tris, fn, area = tris[ok], cr[ok] / a2[ok, None], 0.5 * a2[ok]
    lo = tris.reshape(-1, 3).min(axis=0) - PAD_VOX * vox
    hi = tris.reshape(-1, 3).max(axis=0) + PAD_VOX * vox
    shape = tuple(fft.next_fast_len(int(s), real=True) for s in np.ceil((hi - lo) / vox).astype(int) + 1)

    def vox_of(p):
        return np.clip(np.floor((p - lo) / vox).astype(np.int64), 0, np.array(shape) - 1)

    # 1. a robust solid from every triangle; pick the closing radius
    pts, _, _, _ = _sample(tris, vox * 0.5)
    iv = vox_of(pts)
    surf = np.zeros(shape, dtype=bool)
    surf[iv[:, 0], iv[:, 1], iv[:, 2]] = True
    del iv, pts
    dist = ndimage.distance_transform_edt(~surf).astype(np.float32)
    del surf
    radii = [close_mm / vox] if close_mm else list(CLOSE_RADII_VOX)
    solid_vox = []
    for r in radii:
        d = ndimage.distance_transform_edt(ndimage.binary_fill_holes(dist <= r))
        solid_vox.append(int((d > r).sum()))
        del d
    r = pick_close_radius(radii, solid_vox)
    depth = ndimage.distance_transform_edt(ndimage.binary_fill_holes(dist <= r)).astype(np.float32)
    del dist
    inside = depth > r
    deep = np.unravel_index(int(np.argmax(depth)), shape)     # the most interior voxel, to orient the indicator
    del depth

    # 2. the outer skin: faces whose front is outside the solid
    probe = vox_of(tris.mean(axis=1) + fn * FRONT_VOX * vox)
    outer = ~inside[probe[:, 0], probe[:, 1], probe[:, 2]]
    del inside
    skin, skin_n, skin_a = tris[outer], fn[outer], area[outer]
    if not len(skin):
        raise ValueError("no outer surface found (is the mesh empty or inside out?)")

    # 3. Poisson reconstruction from the skin's oriented samples
    pts, pid, w, bary = _sample(skin, vox * 0.5)
    if smooth_normals:
        _, vid = np.unique(np.round(skin.reshape(-1, 3) / 1e-4).astype(np.int64), axis=0, return_inverse=True)
        vid = vid.reshape(-1, 3)
        vn = np.zeros((vid.max() + 1, 3))
        for k in range(3):
            np.add.at(vn, vid[:, k], skin_n * skin_a[:, None])
        vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
        corner = vn[vid]
        crease = (corner * skin_n[:, None, :]).sum(-1) < np.cos(np.radians(crease_deg))
        corner = np.where(crease[..., None], skin_n[:, None, :], corner)
        nrm = (corner[pid] * bary[:, :, None]).sum(1)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    else:
        nrm = skin_n[pid]
    wn = nrm * (skin_a[pid] * w)[:, None]
    g = (pts - lo) / vox
    g0 = np.floor(g).astype(np.int64)
    fr = g - g0
    flat_n = int(np.prod(shape))
    strides = np.array([shape[1] * shape[2], shape[2], 1])
    field = [np.zeros(flat_n) for _ in range(3)]
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                wt = ((fr[:, 0] if dx else 1 - fr[:, 0]) * (fr[:, 1] if dy else 1 - fr[:, 1])
                      * (fr[:, 2] if dz else 1 - fr[:, 2]))
                idx = (g0 + np.array([dx, dy, dz])) @ strides
                for c in range(3):
                    field[c] += np.bincount(idx, weights=wn[:, c] * wt, minlength=flat_n)
    field = [f.reshape(shape).astype(np.float32) for f in field]
    del g0, fr, wn
    kx = 2 * np.pi * fft.fftfreq(shape[0], d=vox)[:, None, None]
    ky = 2 * np.pi * fft.fftfreq(shape[1], d=vox)[None, :, None]
    kz = 2 * np.pi * fft.rfftfreq(shape[2], d=vox)[None, None, :]
    k2 = (kx ** 2 + ky ** 2 + kz ** 2).astype(np.float32)
    div = np.zeros((shape[0], shape[1], shape[2] // 2 + 1), dtype=np.complex64)
    for c, kc in enumerate((kx, ky, kz)):
        div += (1j * kc).astype(np.complex64) * fft.rfftn(field[c], workers=-1)
        field[c] = None
    gauss = np.exp(-0.5 * (SIGMA_VOX * vox) ** 2 * k2).astype(np.float32)
    k2[0, 0, 0] = 1.0
    chi_hat = div * gauss / (-k2)
    chi_hat[0, 0, 0] = 0
    del div, gauss, k2
    chi = fft.irfftn(chi_hat, s=shape, workers=-1).astype(np.float32)
    del chi_hat
    iso = float(np.average(ndimage.map_coordinates(chi, ((pts - lo) / vox).T, order=1, mode="nearest"),
                           weights=skin_a[pid] * w))
    if chi[deep] < iso:                                    # make "inside" the high side
        chi, iso = -chi, -iso
    verts, faces, _, _ = measure.marching_cubes(chi, level=iso, spacing=(vox, vox, vox))
    del chi
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
    """STL (mm) -> solid STL (mm). The voxel size follows the model's longest side unless `vox` is given."""
    tris = read_stl(src)
    if vox is None:
        pts = tris.reshape(-1, 3)
        vox = auto_voxel_mm(float((pts.max(0) - pts.min(0)).max()))
    out, info = solidify(tris, vox=vox, close_mm=close_mm, **kw)
    write_stl(dst, out, header=b"chimera solidify (mm)")
    info["output"] = str(Path(dst))
    return info

"""Triangle meshes for the print tests ((N, 3, 3) arrays in mm). Import after pytest.importorskip("numpy")."""
import math

import numpy as np


def box(lo, hi, inward=False):
    """12 triangles of an axis-aligned box, wound outward (or inward, for a cavity wall)."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    t = v[np.array(f)]
    return t[:, ::-1] if inward else t


def sphere(r, n_lat=48, n_lon=96, inward=False, hole_deg=0.0):
    """UV-sphere triangles (outward), optionally inward-facing, optionally with a round hole of
    `hole_deg` half-angle at the north pole."""
    th = np.linspace(0, np.pi, n_lat + 1)
    ph = np.linspace(0, 2 * np.pi, n_lon + 1)
    P = np.stack([np.sin(th)[:, None] * np.cos(ph)[None], np.sin(th)[:, None] * np.sin(ph)[None],
                  np.cos(th)[:, None] * np.ones_like(ph)[None]], -1) * r
    tris = []
    for i in range(n_lat):
        if math.degrees(th[i + 1]) <= hole_deg:
            continue
        for j in range(n_lon):
            a, b, c, d = P[i, j], P[i + 1, j], P[i + 1, j + 1], P[i, j + 1]
            tris += [(a, b, c), (a, c, d)]
    t = np.array(tris)
    t = t[np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) > 1e-9]   # pole slivers
    return t[:, ::-1] if inward else t


def sheet(r=20.0, thickness=0.6, hole_deg=0.0):
    """A TRELLIS.2-like sheet: an outer surface and an inner one `thickness` below it, both closed around the
    body's empty cavity (optionally leaking through a hole at the top)."""
    return np.concatenate([sphere(r, hole_deg=hole_deg), sphere(r - thickness, inward=True, hole_deg=hole_deg)])


def _ring(r_out, r_in, z_bottom, z_top, n=96, floor=None):
    """A closed annular solid (outer wall, inner wall, top and bottom rings), or with `floor` (a height) a cup:
    the bore is closed at that height instead of running through."""
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    b = np.roll(a, -1)

    def p(r, t, z):
        return [r * math.cos(t), r * math.sin(t), z]
    tris = []
    for t0, t1 in zip(a, b, strict=True):
        tris += [[p(r_out, t0, z_bottom), p(r_out, t1, z_bottom), p(r_out, t1, z_top)],
                 [p(r_out, t0, z_bottom), p(r_out, t1, z_top), p(r_out, t0, z_top)]]              # outer wall
        z_in = z_bottom if floor is None else floor
        tris += [[p(r_in, t0, z_in), p(r_in, t1, z_top), p(r_in, t1, z_in)],
                 [p(r_in, t0, z_in), p(r_in, t0, z_top), p(r_in, t1, z_top)]]                     # inner wall
        tris += [[p(r_out, t0, z_top), p(r_out, t1, z_top), p(r_in, t1, z_top)],
                 [p(r_out, t0, z_top), p(r_in, t1, z_top), p(r_in, t0, z_top)]]                   # top ring
        if floor is None:
            tris += [[p(r_out, t0, z_bottom), p(r_in, t1, z_bottom), p(r_out, t1, z_bottom)],
                     [p(r_out, t0, z_bottom), p(r_in, t0, z_bottom), p(r_in, t1, z_bottom)]]      # bottom ring
        else:
            tris += [[[0, 0, z_bottom], p(r_out, t1, z_bottom), p(r_out, t0, z_bottom)],         # base
                     [[0, 0, floor], p(r_in, t0, floor), p(r_in, t1, floor)]]                      # inner floor
    return np.array(tris, float)


def tube(r_out=12.0, r_in=8.0, height=30.0):
    """A solid tube with a through bore (the CAD module's `cad --shape tube` example)."""
    return _ring(r_out, r_in, 0.0, height)


def cup(r=40.0, height=90.0, wall=3.0, base=4.0):
    """A solid, open-topped cup: 3 mm walls on a 4 mm base."""
    return _ring(r, r - wall, 0.0, height, floor=base)


def slotted_block(scale=1.0):
    """A U-block: two 19 mm prongs on a 40 x 10 x 4 mm base with a 2 mm slot between them (all x `scale`)."""
    parts = [box((0, 0, 0), (40, 10, 4)), box((0, 0, 4), (19, 10, 30)), box((21, 0, 4), (40, 10, 30))]
    return np.concatenate(parts) * scale


def slot_is_open(tris, scale=1.0):
    """True when a ray through the middle of slotted_block's slot meets no surface."""
    o = np.array([20.0 * scale, -5.0, 17.0 * scale]) + 1e-3
    v0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    p = np.cross([0.0, 1.0, 0.0], e2)
    det = (e1 * p).sum(1)
    ok = np.abs(det) > 1e-12
    inv = 1.0 / np.where(ok, det, 1.0)
    s = o - v0
    u = (s * p).sum(1) * inv
    q = np.cross(s, e1)
    v = (q * [0.0, 1.0, 0.0]).sum(1) * inv
    t = (e2 * q).sum(1) * inv
    return not np.any(ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0))

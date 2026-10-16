# Shrouded turbofan-style fan rotor: 18 twisted, lofted blades (pitch 55 deg at the root -> 25 deg at the
# tip), a hub, a spinner cone and a tip shroud ring, fused into one solid, stood upright facing the
# render camera. Millimetres. Run: `chimera cad --mode script --script modules/cad/examples/turbofan.py`.
# ruff: noqa: F821  (`App` and `Part` are injected by the cad runner, see script_exec.py)
import math

N = 18                 # blades
HUB_R, HUB_H = 18.0, 16.0
R_ROOT, R_TIP = 15.0, 62.0          # blade roots sink 3 mm into the hub so the fuse is clean
CHORD_ROOT, CHORD_TIP = 15.0, 26.0  # wider at the tip, like a turbofan
T = 1.8                             # blade thickness
PITCH_ROOT, PITCH_TIP = 55.0, 25.0  # twist along the span
Z_MID = HUB_H / 2.0


def section(r, chord, pitch_deg):
    """A thin rectangular blade section in the plane x = r, centred at z = Z_MID, pitched about the
    radial (x) axis."""
    a = math.radians(pitch_deg)
    pts = []
    for (u, v) in ((-chord / 2, -T / 2), (chord / 2, -T / 2), (chord / 2, T / 2), (-chord / 2, T / 2)):
        y = u * math.cos(a) - v * math.sin(a)
        z = u * math.sin(a) + v * math.cos(a)
        pts.append(App.Vector(r, y, Z_MID + z))
    return Part.makePolygon(pts + [pts[0]])


sections = []
for k in range(5):                  # five stations so the twist reads as a smooth curve
    f = k / 4.0
    sections.append(section(R_ROOT + f * (R_TIP - R_ROOT),
                            CHORD_ROOT + f * (CHORD_TIP - CHORD_ROOT),
                            PITCH_ROOT + f * (PITCH_TIP - PITCH_ROOT)))
blade = Part.makeLoft(sections, True, False)

rotor = Part.makeCylinder(HUB_R, HUB_H)
for i in range(N):
    b = blade.copy()
    b.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), i * 360.0 / N)
    rotor = rotor.fuse(b)

spinner = Part.makeCone(HUB_R, 0.0, 20.0, App.Vector(0, 0, HUB_H))
rotor = rotor.fuse(spinner).removeSplitter()
shroud = Part.makeCylinder(R_TIP + 3.0, HUB_H).cut(Part.makeCylinder(R_TIP - 0.5, HUB_H))
rotor = rotor.fuse(shroud).removeSplitter()
bore = Part.makeCylinder(3.0, HUB_H + 2.0, App.Vector(0, 0, -1.0))
rotor = rotor.cut(bore)
rotor.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 90)   # stand it up: the spinner faces -Y, the camera side
RESULT = [rotor]

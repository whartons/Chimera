"""Shared FreeCAD helpers for Chimera's headless `cad` templates. Each template does:
    import _common as C; p = C.args(); ...; C.emit({"outputs": [...]})
Run only inside `FreeCADCmd <template.py> <params.json>` (FreeCAD's bundled Python 3.11).
FreeCADCmd exposes script args as sys.argv=[exe, script, params_json_path] — no `--` separator,
so the params file path is the LAST argv entry."""
import sys, os, json
import FreeCAD as App
import Part
import Mesh


def args() -> dict:
    """Parse the JSON params file whose path is the last sys.argv entry."""
    with open(sys.argv[-1], encoding="utf-8") as fh:
        return json.load(fh)


def emit(manifest: dict):
    """Print the one-line result manifest the host runner parses."""
    manifest.setdefault("freecad_version", ".".join(str(x) for x in App.Version()[:3]))
    print("@@CHIMERA_MANIFEST@@ " + json.dumps(manifest))


def export_shapes(objs, out_dir, stem, formats) -> list:
    """Export the given FreeCAD objects to each requested format. step/stp -> Part.export (BREP);
    stl/obj -> Mesh.export (extension-driven tessellation of a Part::Feature, or a Mesh::Feature
    passed straight through). Returns absolute output paths. Unknown format -> ValueError."""
    paths = []
    for fmt in formats:
        f = fmt.lower()
        if f in ("step", "stp"):
            path = os.path.join(out_dir, stem + ".step")
            Part.export(objs, path)
        elif f in ("stl", "obj"):
            path = os.path.join(out_dir, stem + "." + f)
            Mesh.export(objs, path)
        else:
            raise ValueError("unsupported export format: " + str(fmt))
        paths.append(os.path.abspath(path))
    return paths

"""Shared FreeCAD helpers for Chimera's headless `cad` templates. Each template does:
    import _common as C; p = C.args(); ...; C.emit({"outputs": [...]})
Run inside `FreeCADCmd <template.py>` (FreeCAD's bundled Python 3.11); the host runner passes the
params-file path via the $CHIMERA_CAD_PARAMS env var (NOT a CLI arg — FreeCAD 1.1.x would try to OPEN
a trailing file as a document). C.args() reads that env var, falling back to the last sys.argv entry."""
import sys, os, json
import FreeCAD as App
import Part
import Mesh


def args() -> dict:
    """Parse the JSON params file. Path from $CHIMERA_CAD_PARAMS (the host runner sets it — passing it as
    a CLI arg makes FreeCAD 1.1.x try to OPEN it as a document); falls back to the last sys.argv entry
    for a manual `FreeCADCmd <template> <params.json>` invocation."""
    path = os.environ.get("CHIMERA_CAD_PARAMS") or sys.argv[-1]
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def emit(manifest: dict):
    """Print the one-line result manifest the host runner parses."""
    manifest.setdefault("freecad_version", ".".join(str(x) for x in App.Version()[:3]))
    print("@@CHIMERA_MANIFEST@@ " + json.dumps(manifest))


def export_shapes(objs, out_dir, stem, formats) -> list:
    """Export the given FreeCAD document objects to each requested format. step/stp -> Part.export
    (BREP). stl/obj -> tessellate each Part shape via MeshPart (headless `Mesh.export` does NOT mesh a
    Part::Feature — it raises "None of the objects can be exported to a mesh file"), pass Mesh::Feature
    meshes through, merge into one mesh and write by extension. Returns absolute paths; unknown -> ValueError."""
    paths = []
    for fmt in formats:
        f = fmt.lower()
        if f in ("step", "stp"):
            path = os.path.join(out_dir, stem + ".step")
            Part.export(objs, path)
        elif f in ("stl", "obj"):
            import MeshPart
            path = os.path.join(out_dir, stem + "." + f)
            combined = Mesh.Mesh()
            for o in objs:
                if o.isDerivedFrom("Mesh::Feature"):
                    combined.addMesh(o.Mesh)
                elif getattr(o, "Shape", None) is not None:
                    combined.addMesh(MeshPart.meshFromShape(
                        Shape=o.Shape, LinearDeflection=0.1, AngularDeflection=0.5))
                else:
                    raise ValueError(f"object {o.Name} has no Shape/Mesh to export to {f}")
            combined.write(path)
        else:
            raise ValueError("unsupported export format: " + str(fmt))
        paths.append(os.path.abspath(path))
    return paths

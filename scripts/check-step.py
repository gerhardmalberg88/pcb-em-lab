"""Check the FreeCAD-to-Gmsh file handoff, including dimensional units."""
import gmsh
gmsh.initialize()
try:
    gmsh.option.setString('Geometry.OCCTargetUnit','MM')
    solids=gmsh.model.occ.importShapes('/work/freecad-smoke.step')
    volume=sum(gmsh.model.occ.getMass(d,t) for d,t in solids if d==3)
    assert abs(volume-6)<1e-8,volume
    print('FreeCAD STEP -> Gmsh OCCT: 6 cubic millimetres verified')
finally:gmsh.finalize()

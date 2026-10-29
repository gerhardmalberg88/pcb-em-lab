import FreeCAD
import Part
shape=Part.makeBox(1,2,3)
assert abs(shape.Volume-6)<1e-10
shape.exportStep('/work/freecad-smoke.step')
print('FreeCAD Python/OCCT STEP export passed:',FreeCAD.Version())

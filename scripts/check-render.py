from paraview.simple import Sphere,Show,GetActiveViewOrCreate,Render,SaveScreenshot,SaveState
from pathlib import Path
sphere=Sphere()
view=GetActiveViewOrCreate('RenderView');Show(sphere,view)
view.ViewSize=[640,480];view.ResetCamera();Render(view)
SaveScreenshot('/work/render-smoke.png',view)
SaveState('/work/render-smoke.pvsm')
assert Path('/work/render-smoke.png').stat().st_size>1000
print('ParaView pvpython headless rendering and state save passed')

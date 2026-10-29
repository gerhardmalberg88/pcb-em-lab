"""Run with pvpython; save the same state that the GUI can reopen."""
import json
from pathlib import Path
import sys
from paraview.simple import (PVDReader, Show, GetActiveViewOrCreate, Render,
                            SaveScreenshot, SaveState, ColorBy, XMLUnstructuredGridReader, Slice, Calculator, Hide,
                            Text, GetColorTransferFunction, GetScalarBar)

root=Path(sys.argv[1]);files=sorted((root/'solve').rglob('*.pvd'))
if not files:raise RuntimeError('Solver produced no PVD fields to render')
record=root/'postprocess/winding-fields.json'
winding_records=json.loads(record.read_text()) if record.exists() else []
windings=[root/'postprocess'/x['file'] for x in winding_records]
reader=XMLUnstructuredGridReader(FileName=[str(windings[0])]) if windings else PVDReader(FileName=str(files[0]))
reader.UpdatePipeline()
geometry=json.loads((root/'mesh/geometry.json').read_text())
magnetic=geometry.get('analysis') in ('magnetostatic','magnetic-driven')
view=GetActiveViewOrCreate('RenderView');view.ViewSize=[1200,800]
time_step=None
if geometry['dimension']==2:
    report=json.loads((root/'postprocess/report.json').read_text())
    candidates=report.get('differential_candidates',[])
    if candidates:
        time_step=float(candidates[0]['m'])-1
        reader.UpdatePipeline(time=time_step);view.ViewTime=time_step
visible=reader;slice_info=None
if geometry['dimension']==3:
    bounds=reader.GetDataInformation().GetBounds()
    center=[(bounds[i*2]+bounds[i*2+1])/2 for i in range(3)]
    normal=[0,1,0] if magnetic else [0,0,1]
    if not magnetic and geometry.get('ports'):
        center[2]=min(p[2] for port in geometry['ports'] for p in port['endpoints_mm'])+.05
    visible=Slice(Input=reader);visible.SliceType='Plane'
    visible.SliceType.Origin=center;visible.SliceType.Normal=normal
    visible.UpdatePipeline()
    outline=Show(reader,view);outline.Representation='Outline';outline.SetScalarColoring(None,0)
    slice_info={'origin_mm':center,'normal':normal}
display=Show(visible,view)
if slice_info:
    distance=2.5*max(bounds[i*2+1]-bounds[i*2] for i in range(3))
    view.CameraFocalPoint=center
    view.CameraPosition=[center[i]+distance*normal[i] for i in range(3)]
    view.CameraViewUp=[0,0,1] if magnetic else [0,1,0]
    view.CameraParallelProjection=1
view.ResetCamera()
arrays=list(reader.PointData.keys())
preferred=('B','B_real','A','E','E_real') if magnetic else ('E','E_real','B','B_real','V','A')
field=next((x for x in preferred if x in arrays),arrays[0] if arrays else None)
if field and field.endswith('_real') and field[:-5]+'_imag' in arrays:
    base=field[:-5]
    magnitude=Calculator(Input=visible);magnitude.ResultArrayName=base+'_magnitude'
    magnitude.Function=f'sqrt(mag({base}_real)^2+mag({base}_imag)^2)'
    magnitude.UpdatePipeline();Hide(visible,view);display=Show(magnitude,view)
    field=magnitude.ResultArrayName
if field:
    ColorBy(display,('POINTS',field));display.RescaleTransferFunctionToDataRange(True,False)
    display.SetScalarBarVisibility(view,True)
    base=field.split('_')[0]
    units={'E':'V/m','B':'T','H':'A/m','A':'T m','V':'V'}
    bar=GetScalarBar(GetColorTransferFunction(field),view)
    bar.Title=f'|{base}| ({units[base]})' if base in units else field
    bar.ComponentTitle=''
label=Text()
if winding_records:
    info=winding_records[0]
    normalization=f"{geometry.get('component','')}: {info['winding']}, 1 A"
    if 'frequency_hz' in info:normalization+=f" peak, {info['frequency_hz']:g} Hz"
    else:normalization+=' static'
elif geometry['dimension']==2:
    normalization=f'BoundaryMode, mode {int(time_step)+1 if time_step is not None else 1}; modal field normalization'
else:
    normalization='Driven: first port excitation; other ports reference-terminated'
label.Text=normalization
label_view=Show(label,view);label_view.WindowLocation='Upper Left Corner';label_view.FontSize=14
Render()
dest=root/'postprocess';dest.mkdir(exist_ok=True)
SaveScreenshot(str(dest/'fields-domain.png'),view)
if geometry['dimension']==2:
    conductors=[s for s in geometry['segments'] if s[1] in geometry['pair']]
    low=min(s[2] for s in conductors);high=max(s[3] for s in conductors)
    center=[(low+high)/2,geometry['voltage_path'][0][1],0]
    view.CameraFocalPoint=center;view.CameraPosition=[center[0],center[1],10]
    view.CameraViewUp=[0,1,0];view.CameraParallelProjection=1
    view.CameraParallelScale=max(high-low,.5)
elif magnetic:
    view.CameraParallelScale/=2.5
elif geometry.get('region_mm'):
    xmin,ymin,xmax,ymax=geometry['region_mm']
    center=[(xmin+xmax)/2,(ymin+ymax)/2,slice_info['origin_mm'][2]]
    view.CameraFocalPoint=center;view.CameraPosition=[center[0],center[1],center[2]+distance]
    view.CameraParallelScale=.575*max(ymax-ymin,(xmax-xmin)/1.5)
Render()
SaveScreenshot(str(dest/'fields.png'),view)
SaveState(str(dest/'view.pvsm'))
(dest/'render.json').write_text(json.dumps({'source':str(windings[0] if windings else files[0]),
    'field':field,'available_arrays':arrays,'slice':slice_info,'time_step':time_step,
    'normalization':normalization,
    'winding_field_files':[str(p) for p in windings]},indent=2)+'\n')

"""pvpython: reconstruct linear one-ampere winding fields from turn excitations."""
import csv
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import numpy as np
from vtkmodules.vtkIOXML import vtkXMLPUnstructuredGridReader,vtkXMLUnstructuredGridReader,vtkXMLUnstructuredGridWriter
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid
from vtkmodules.util.numpy_support import vtk_to_numpy,numpy_to_vtk

root=Path(sys.argv[1]);geometry=json.loads((root/'mesh/geometry.json').read_text())
analysis=geometry.get('analysis')
if analysis not in ('magnetostatic','magnetic-driven'):raise SystemExit(0)
ports=geometry['turn_ports'];count=len(ports)
dest=root/'postprocess';dest.mkdir(exist_ok=True);records=[]


def read(path):
    reader=vtkXMLPUnstructuredGridReader() if path.suffix=='.pvtu' else vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(path));reader.Update()
    grid=vtkUnstructuredGrid();grid.DeepCopy(reader.GetOutput());return grid


def check_meshes(grids):
    first=grids[0];points=vtk_to_numpy(first.GetPoints().GetData())
    for grid in grids:
        if grid.GetNumberOfPoints()!=first.GetNumberOfPoints() or grid.GetNumberOfCells()!=first.GetNumberOfCells():
            raise RuntimeError('Turn snapshots use different meshes')
        if not np.allclose(vtk_to_numpy(grid.GetPoints().GetData()),points,rtol=0,atol=1e-12):
            raise RuntimeError('Turn snapshot point ordering differs')


def combine(grids,weights,path):
    output=vtkUnstructuredGrid();output.DeepCopy(grids[0])
    output.GetPointData().Initialize();output.GetCellData().Initialize();fields=[]
    for name in ('A','B','H','E','J_s'):
        arrays=[grid.GetPointData().GetArray(name) for grid in grids]
        complex_field=arrays[0] is None
        if complex_field:
            real=[grid.GetPointData().GetArray(name+'_real') for grid in grids]
            imag=[grid.GetPointData().GetArray(name+'_imag') for grid in grids]
            if all(a is None for a in real+imag):continue
            if any(a is None for a in real+imag):raise RuntimeError('Inconsistent complex field arrays between turns')
            data=[vtk_to_numpy(r)+1j*vtk_to_numpy(i) for r,i in zip(real,imag)]
        else:
            if any(a is None for a in arrays):raise RuntimeError('Inconsistent field arrays between turns')
            data=[vtk_to_numpy(a) for a in arrays]
        summed=sum(weight*array for weight,array in zip(weights,data))
        fields.append(name)
        parts=[(name+'_real',summed.real),(name+'_imag',summed.imag)] if complex_field else [(name,summed)]
        for label,array in parts:
            result=numpy_to_vtk(np.ascontiguousarray(array),deep=True);result.SetName(label)
            output.GetPointData().AddArray(result)
    if not fields:raise RuntimeError('No linear vector fields found in magnetic snapshots')
    writer=vtkXMLUnstructuredGridWriter();writer.SetFileName(str(path));writer.SetInputData(output)
    if not writer.Write():raise RuntimeError(f'Could not write {path}')
    return fields


if analysis=='magnetostatic':
    with (root/'solve/fields/terminal-I.csv').open() as stream:rows=list(csv.reader(stream))
    headings=[heading.strip() for heading in rows[0]]
    current_column=headings.index('I_inc[i] (A)')
    currents={int(float(row[0])):float(row[current_column]) for row in rows[1:] if row}
    if set(currents)!=set(range(1,count+1)) or any(not np.isfinite(x) or x==0 for x in currents.values()):
        raise RuntimeError('Expected a finite nonzero excitation current for each turn')
    candidates=[]
    for pvd in (root/'solve').rglob('*.pvd'):
        # Exclude Palace's additional error-indicator snapshot at step 99.
        datasets=[x for x in ET.parse(pvd).findall('.//DataSet') if float(x.attrib['timestep']) in range(count)]
        if len(datasets)!=count or {float(x.attrib['timestep']) for x in datasets}!=set(range(count)):continue
        paths=[pvd.parent/x.attrib['file'] for x in sorted(datasets,key=lambda x:float(x.attrib['timestep']))]
        first=read(paths[0])
        if first.GetNumberOfCells():candidates.append((first.GetNumberOfCells(),paths,first))
    if not candidates:raise RuntimeError('Expected one saved field snapshot per current terminal')
    _,paths,first=max(candidates,key=lambda x:x[0])
    grids=[first]+[read(path) for path in paths[1:]];check_meshes(grids)
    for index,name in enumerate(geometry['windings'],1):
        weights=[p['sign']/currents[p['index']] if p['winding']==name else 0 for p in ports]
        path=dest/f'winding-{index}-{re.sub("[^a-zA-Z0-9_-]","-",name)}.vtu'
        fields=combine(grids,weights,path)
        records.append({'winding':name,'current_A':1,'snapshot_weights':weights,
                        'snapshot_currents_A':currents,'file':path.name,'fields':fields})
else:
    normalizations=json.loads((dest/'driven-winding-weights.json').read_text())
    collections={name:[] for name in geometry['windings']}
    for frequency_index,normalization in enumerate(normalizations):
        frequency=normalization['frequency_hz'];grids=[]
        for excitation in range(1,count+1):
            candidates=[]
            for pvd in (root/'solve'/f'excitation-{excitation}').rglob('*.pvd'):
                for dataset in ET.parse(pvd).findall('.//DataSet'):
                    if np.isclose(float(dataset.attrib['timestep'])*1e9,frequency,rtol=1e-9,atol=1e-6):
                        grid=read(pvd.parent/dataset.attrib['file'])
                        if grid.GetNumberOfCells():candidates.append(grid)
            if not candidates:raise RuntimeError(f'No field snapshot for excitation {excitation} at {frequency:g} Hz')
            grids.append(max(candidates,key=lambda grid:grid.GetNumberOfCells()))
        check_meshes(grids)
        weights=np.asarray(normalization['weights_real'])+1j*np.asarray(normalization['weights_imag'])
        for index,name in enumerate(geometry['windings']):
            path=dest/f'winding-{index+1}-{re.sub("[^a-zA-Z0-9_-]","-",name)}-f{frequency_index}.vtu'
            fields=combine(grids,weights[:,index],path)
            records.append({'winding':name,'frequency_hz':frequency,'current_A_peak':1,
                            'other_winding_currents_A':0,'file':path.name,'fields':fields})
            collections[name].append((frequency,path.name))
    for index,(name,frames) in enumerate(collections.items(),1):
        vtk=ET.Element('VTKFile',type='Collection',version='0.1',byte_order='LittleEndian')
        collection=ET.SubElement(vtk,'Collection')
        for frequency,filename in frames:
            ET.SubElement(collection,'DataSet',timestep=str(frequency),group='',part='0',file=filename)
        ET.ElementTree(vtk).write(dest/f'winding-{index}.pvd',encoding='utf-8',xml_declaration=True)
(dest/'winding-fields.json').write_text(json.dumps(records,indent=2)+'\n')
print('Winding field superposition:',[x['winding'] for x in records])

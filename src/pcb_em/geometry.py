"""Gmsh construction in millimetres; topology comes from the saved KiCad copper."""
import json
import math
from collections import defaultdict
from pathlib import Path
from .common import WorkflowError, write_json, positive


def planar_polygons(board, crop=None):
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    groups = defaultdict(list)
    outline = unary_union([Polygon(p["outer"],p["holes"]) for p in board["outline"]])
    region = outline if crop is None else outline.intersection(box(*crop))
    for item in board["copper"]:
        for p in item["polygons"]:
            polygon = Polygon(p["outer"],p["holes"])
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            polygon = polygon.intersection(region)
            if not polygon.is_empty:
                groups[(item["layer"],item["net"])].append(polygon)
    return region, {key: unary_union(values) for key,values in groups.items()}


def parts(shape, kind):
    if shape.is_empty:
        return []
    if shape.geom_type == kind:
        return [shape]
    return [part for g in getattr(shape, "geoms", []) for part in parts(g,kind)]


def configure(gmsh, config):
    fine, coarse, scale = (float(config.get(key, default)) for key, default in
                           [('fine_mm', .04), ('coarse_mm', 2.), ('scale', 1.)])
    if not all(math.isfinite(x) and x > 0 for x in (fine, coarse, scale)) or fine > coarse:
        raise WorkflowError('Mesh sizes and scale must be positive and finite, with fine_mm <= coarse_mm')
    try:
        threads = positive(config.get('threads', 1))
        positive(config.get('order', 2))
    except (ValueError, TypeError) as error:
        raise WorkflowError('Mesh threads and order must be positive integers') from error
    gmsh.initialize()
    if threads>1 and 'OpenMP' not in gmsh.option.getString('General.BuildOptions').split():
        gmsh.finalize()
        raise WorkflowError('This Gmsh build has no OpenMP support; set mesh.threads to 1')
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.option.setString('Geometry.OCCTargetUnit','MM')
    gmsh.option.setNumber("General.NumThreads", threads)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.option.setNumber("Mesh.Binary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeMin", fine)
    gmsh.option.setNumber("Mesh.MeshSizeMax", coarse)
    gmsh.option.setNumber('Mesh.MeshSizeFactor',scale)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
    gmsh.model.add("pcb-em")


def physical(gmsh, dimension, tags, ident, name):
    tags = sorted(set(tags))
    if not tags:
        raise WorkflowError(f"Empty physical group {name}; check geometry and region")
    gmsh.model.addPhysicalGroup(dimension,tags,ident)
    gmsh.model.setPhysicalName(dimension,ident,name)


def material(layer, case):
    overrides = case.get("materials",{})
    if layer["name"].endswith(".Mask"):
        epsilon = overrides.get("soldermask_epsilon_r")
    else:
        epsilon = overrides.get(layer["name"],{}).get("epsilon_r", layer["epsilon_r"])
    if epsilon is None:
        epsilon = overrides.get("substrate_epsilon_r")
    if epsilon is None or float(epsilon) <= 0:
        raise WorkflowError(f"Missing positive permittivity for {layer['name']}")
    return {"Permittivity":float(epsilon),"Permeability":1.0,
            "LossTan":float(overrides.get(layer["name"],{}).get("loss_tangent",layer["loss_tangent"]))}


def linear_settings(case,default_tolerance=1e-8,default_max_iterations=200,estimator_multigrid=False):
    options=case.get('numerics',{})
    tolerance=float(options.get('linear_tolerance',default_tolerance))
    if not math.isfinite(tolerance) or not 0<tolerance<1:
        raise WorkflowError('numerics.linear_tolerance must be between zero and one')
    try:iterations=positive(options.get('max_iterations',default_max_iterations))
    except (ValueError,TypeError) as error:raise WorkflowError('numerics.max_iterations must be a positive integer') from error
    multigrid=options.get('estimator_multigrid',estimator_multigrid)
    if not isinstance(multigrid,bool):raise WorkflowError('numerics.estimator_multigrid must be true or false')
    return {'Tol':tolerance,'MaxIts':iterations,'EstimatorMG':multigrid}


def cross_section(board,case,out):
    import gmsh
    from shapely.geometry import LineString
    region, copper = planar_polygons(board)
    section = case.get("cross_section",{})
    if "line_mm" not in section or len(section["line_mm"]) != 2:
        raise WorkflowError("2D requires cross_section.line_mm: [[x0,y0],[x1,y1]]")
    line = LineString(section["line_mm"])
    length = line.length
    if not length:
        raise WorkflowError("Cross-section endpoints must differ")
    from shapely.geometry import Point
    for hole in board['holes']:
        if line.distance(Point(hole['center'])) < max(hole['drill'])/2:
            raise WorkflowError('2D section crosses a drilled hole; choose a uniform trace section or use 3D')
    if float(case.get('frequency_hz',0)) <= 0:
        raise WorkflowError('BoundaryMode frequency_hz must be positive')
    span = line.intersection(region)
    if not parts(span,"LineString"):
        raise WorkflowError("Cross-section does not intersect the PCB")
    segments=[]
    for (layer,net),shape in copper.items():
        for piece in parts(shape.intersection(line),"LineString"):
            from shapely.geometry import Point
            endpoints=[line.project(Point(piece.coords[0])),line.project(Point(piece.coords[-1]))]
            a,b=sorted(endpoints)
            if b-a>1e-7:
                segments.append((layer,net,a,b))
    pair=section.get("pair",[])
    if len(pair)!=2 or any(not any(x[1]==net for x in segments) for net in pair):
        raise WorkflowError("The cross-section must intersect both named pair conductors")
    mesh=case.get("mesh",{})
    configure(gmsh,mesh)
    try:
        occ=gmsh.model.occ
        top=max(x['z_top_mm'] for x in board['stackup'])
        bottom=min(x['z_bottom_mm'] for x in board['stackup'])
        margin=float(section.get('air_margin_mm',8))
        domain=occ.addRectangle(0,bottom-margin,0,length,top-bottom+2*margin)
        metals=[]
        net_by_tag={}
        layer_lookup={x['name']:x for x in board['stackup'] if x['kind']=='copper'}
        for name,net,a,b in segments:
            layer=layer_lookup[name]
            tag=occ.addRectangle(a,layer['z_bottom_mm'],0,b-a,layer['thickness_mm'])
            metals.append((2,tag));net_by_tag[tag]=net
        layer_surfaces=[]; layer_data=[]
        from shapely.geometry import Point
        for layer in board['stackup']:
            for p in parts(span,'LineString'):
                a,b=sorted([line.project(Point(p.coords[0])),line.project(Point(p.coords[-1]))])
                tag=occ.addRectangle(a,layer['z_bottom_mm'],0,b-a,layer['thickness_mm'])
                layer_surfaces.append((2,tag));layer_data.append(layer)
        # Fragment every region together; maps preserve source material membership.
        all_entities=[(2,domain)]+layer_surfaces+metals
        fragments,maps=occ.fragment([all_entities[0]],all_entities[1:])
        metal_entities={tag for group in maps[1+len(layer_surfaces):] for dim,tag in group if dim==2}
        net_boundaries=defaultdict(set)
        occ.synchronize()
        for group,source in zip(maps[1+len(layer_surfaces):],metals):
            for dim,tag in group:
                if dim==2:
                    net_boundaries[net_by_tag[source[1]]].update(t for d,t in gmsh.model.getBoundary([(2,tag)],oriented=False) if d==1)
        occ.remove([(2,t) for t in metal_entities],recursive=False)
        occ.synchronize()
        materials=[];occupied=set();names={}
        for i,(group,layer) in enumerate(zip(maps[1:1+len(layer_surfaces)],layer_data),2):
            tags={t for d,t in group if d==2}-metal_entities
            if not tags:continue
            physical(gmsh,2,tags,i,layer['name']+f"_{i}")
            props=material(layer,case)
            materials.append({'Attributes':[i],**props});occupied.update(tags);names[str(i)]=layer['name']
        air={t for d,t in maps[0] if d==2}-occupied-metal_entities
        physical(gmsh,2,air,1,'air');materials.append({'Attributes':[1],'Permittivity':1.0,'Permeability':1.0})
        # Copper touching the cropped domain leaves orphan curves after its
        # interior is removed. Export only edges belonging to retained faces;
        # MFEM cannot load boundary elements with no adjacent domain element.
        active_curves={t for face in gmsh.model.getEntities(2)
                       for d,t in gmsh.model.getBoundary([face],oriented=False) if d==1}
        pec=[]
        for index,(net,tags) in enumerate(sorted(net_boundaries.items()),100):
            tags=tags&active_curves
            physical(gmsh,1,tags,index,net or 'unconnected')
            pec.append(index);names[f'boundary:{index}']=net
        # Refine around conductor boundaries, allowing larger elements in remote air.
        distance=gmsh.model.mesh.field.add('Distance')
        gmsh.model.mesh.field.setNumbers(distance,'CurvesList',[t for v in net_boundaries.values() for t in v if t in active_curves])
        threshold=gmsh.model.mesh.field.add('Threshold')
        for key,value in [('InField',distance),('SizeMin',mesh.get('fine_mm',.04)),('SizeMax',mesh.get('coarse_mm',2)),('DistMin',.1),('DistMax',2)]:
            gmsh.model.mesh.field.setNumber(threshold,key,value)
        gmsh.model.mesh.field.setAsBackgroundMesh(threshold)
        gmsh.write(str(out/'geometry.brep'))
        gmsh.model.mesh.generate(2)
        gmsh.write(str(out/'board.msh'))
        locations=[]
        for net in reversed(pair):
            choices=[s for s in segments if s[1]==net]
            if len(choices)!=1:
                raise WorkflowError(f'{net} intersects the cut {len(choices)} times; choose an unambiguous section')
            layer,_,a,b=choices[0]
            z=layer_lookup[layer]['z_bottom_mm' if layer=='B.Cu' else 'z_top_mm']
            locations.append([(a+b)/2,z])
        # Use the facing copper edges so the voltage integration path lies in dielectric.
        first,second=locations
        if abs(first[1]-second[1])>1e-7:
            raise WorkflowError('Initial 2D pair analysis requires the pair on the same layer')
        facing=[]
        for net,other in [(pair[1],second[0]),(pair[0],first[0])]:
            layer,_,a,b=next(s for s in segments if s[1]==net)
            x=b if other>(a+b)/2 else a
            facing.append([x,(layer_lookup[layer]['z_top_mm']+layer_lookup[layer]['z_bottom_mm'])/2])
        facing.reverse()  # Integral runs from declared positive to negative.
        post={'Impedance':[{'Index':1,'VoltagePath':facing,'NSamples':200}]}
        pair_layer=next(s[0] for s in segments if s[1]==pair[0])
        reference=section.get('reference_point_section_mm')
        if reference is None and pair_layer in ('F.Cu','B.Cu'):
            reference=[sum(p[0] for p in locations)/2,top+.5 if pair_layer=='F.Cu' else bottom-.5]
        if reference is not None:
            post['Voltage']=[{'Index':i,'VoltagePath':[p,reference],'NSamples':200}
                             for i,p in enumerate(reversed(locations),1)]
        config={'Problem':{'Type':'BoundaryMode','Output':'postpro','Verbose':1},
            'Model':{'Mesh':'board.msh','L0':.001},'Domains':{'Materials':materials},
            'Boundaries':{'PEC':{'Attributes':pec},'Postprocessing':post},
            'Solver':{'Order':int(mesh.get('order',2)),
                'BoundaryMode':{'Freq':float(case.get('frequency_hz',4e6))/1e9,'N':int(section.get('modes',2)),
                    'Save':int(section.get('modes',2)),'Target':float(section.get('target_index',1.8)),'Tol':1e-8},
                'Linear':linear_settings(case,1e-9,100)}}
        write_json(out/'case.json',config)
        write_json(out/'geometry.json',{'dimension':2,'groups':names,'pair':pair,'segments':segments,
            'voltage_reference_section_mm':reference,
            'voltage_path':facing,'assumptions':case.get('assumptions',[]),'mesh_nodes':len(gmsh.model.mesh.getNodes()[0])})
    finally:
        gmsh.finalize()


def occ_polygon(occ,polygon,z):
    from shapely.geometry.polygon import orient
    polygon=orient(polygon,sign=1.0)
    def loop(coords):
        pts=[occ.addPoint(float(x),float(y),float(z)) for x,y in list(coords)[:-1]]
        return occ.addCurveLoop([occ.addLine(pts[i],pts[(i+1)%len(pts)]) for i in range(len(pts))])
    # OCC's plane-surface constructor reverses inner wires itself. Supply the
    # same orientation for every wire (unlike Shapely's polygon convention).
    tag=occ.addPlaneSurface([loop(polygon.exterior.coords)]+[loop(list(r.coords)[::-1]) for r in polygon.interiors])
    if not math.isclose(occ.getMass(2,tag),polygon.area,rel_tol=1e-7,abs_tol=1e-9):
        raise WorkflowError('CAD polygon area differs from source; check hole orientation and topology')
    return tag


def mesh_case(board_path,case_path,out):
    from .common import read_config
    board=json.loads(Path(board_path).read_text());case=read_config(case_path)
    if case.get('analysis')=='driven' and not case.get('ports'):
        raise WorkflowError('Driven PCB case requires explicit positive/negative ports')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    from .audit import audit_source
    audit_source(board,case,out/'source-audit.json')
    if case['mode']=='2d':
        cross_section(board,case,out)
    elif case.get('analysis') in ('magnetostatic','magnetic-driven'):
        from .magnetics import magnetic_case
        magnetic_case(board,case,out)
    else:
        from .pcb3d import pcb_case
        pcb_case(board,case,out)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('board');p.add_argument('case');p.add_argument('output')
    a=p.parse_args();mesh_case(a.board,a.case,a.output)

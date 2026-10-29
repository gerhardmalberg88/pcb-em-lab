"""Editable linear magnetic models using individually resolved, gapped sheet turns.

Each turn is a port. Series winding inductance is W.T @ L_turn @ W; field
superposition uses the same signed currents. Sheet turns omit pitch and lead
geometry, and are explicitly exploratory approximations of internal windings.
"""
import math
from .common import WorkflowError, write_json, positive
from .geometry import configure, physical, parts, occ_polygon, linear_settings


def magnetic_case(board,case,out):
    import gmsh
    from shapely.geometry import Point, box, LineString
    component=next((x for x in board['components'] if x['ref']==case.get('component')),None)
    if component is None:raise WorkflowError('Magnetics case must name an existing component')
    magnetic=case.get('magnetics',{})
    cores=magnetic.get('cores',[]);windings=magnetic.get('windings',[])
    if not cores or not windings:raise WorkflowError('Supply magnetics.cores and magnetics.windings')
    if not case.get('assumptions'):raise WorkflowError('Internal models require explicit geometry/material assumptions')
    margin=float(magnetic.get('domain_half_size_mm',8))
    if not math.isfinite(margin) or margin<=0:
        raise WorkflowError('magnetics.domain_half_size_mm must be positive and finite')
    for kind,items in [('core',cores),('winding',windings)]:
        names=[item.get('name') for item in items]
        if not all(isinstance(name,str) and name for name in names) or len(set(names))!=len(names):
            raise WorkflowError(f'Each magnetic {kind} needs a unique nonempty name')
        for item in items:
            required=['radius_mm','height_mm','mu_r'] if kind=='core' else ['radius_mm','width_mm','pitch_mm','turns']
            if any(key not in item or not math.isfinite(float(item[key])) or float(item[key])<=0 for key in required):
                raise WorkflowError(f'{kind} {item["name"]}: positive finite values required for {required}')
            center=item.get('center_mm',[])
            if len(center)!=3 or not all(math.isfinite(float(x)) for x in center):
                raise WorkflowError(f'{kind} {item["name"]}: center_mm requires three finite coordinates')
            radial=float(item['radius_mm'])
            if kind=='core':axial=float(item['height_mm'])/2
            else:
                try:turns=positive(item['turns'])
                except (ValueError,TypeError) as error:raise WorkflowError('Winding turns must be a positive integer') from error
                if item.get('sign',1) not in (-1,1):raise WorkflowError('Winding sign must be +1 or -1')
                width=float(item['width_mm']);gap=float(item.get('gap_mm',.15))
                if radial<=width or not 0<gap<2*(radial-width/2):
                    raise WorkflowError('Winding radius must exceed width and gap must be smaller than the inner diameter')
                radial+=width/2;axial=(turns-1)*float(item['pitch_mm'])/2
            if any(abs(float(c))+extent>=margin for c,extent in zip(center,(radial,radial,axial))):
                raise WorkflowError(f'{kind} {item["name"]} must fit strictly inside the magnetic air domain')
    mesh=case.get('mesh',{});configure(gmsh,mesh)
    try:
        occ=gmsh.model.occ
        air=occ.addBox(-margin,-margin,-margin,2*margin,2*margin,2*margin)
        core_entities=[]
        for c in cores:
            x,y,z=c['center_mm'];radius=float(c['radius_mm']);height=float(c['height_mm'])
            core_entities.append((3,occ.addCylinder(x,y,z-height/2,0,0,height,radius)))
        sheets=[];ports=[];metadata=[]
        for wi,winding in enumerate(windings):
            count=int(winding['turns']);radius=float(winding['radius_mm']);width=float(winding['width_mm'])
            if count<1 or radius<=width:raise WorkflowError('Winding needs positive turns and radius larger than width')
            x,y,z=winding['center_mm'];pitch=float(winding['pitch_mm']);gap=float(winding.get('gap_mm',.15))
            for turn in range(count):
                height=z+(turn-(count-1)/2)*pitch
                ring=Point(x,y).buffer(radius+width/2,quad_segs=24).difference(Point(x,y).buffer(radius-width/2,quad_segs=24))
                cut=box(x,y-gap/2,x+radius+width,y+gap/2)
                conductor=ring.difference(cut)
                # Uniform surface current needs a rectangular source sheet.
                # Curved radial edges let a constant Y-directed source leak
                # through its sides, making the static curl-curl RHS incompatible.
                edge=ring.intersection(LineString([(x,y+gap/2),(x+radius+width,y+gap/2)]))
                terminal=box(edge.bounds[0],y-gap/2,edge.bounds[2],y+gap/2)
                for poly in parts(conductor,'Polygon'):sheets.append((2,occ_polygon(occ,poly,height)))
                port_parts=parts(terminal,'Polygon')
                if len(port_parts)!=1:raise WorkflowError('Winding gap did not create one terminal')
                ports.append((2,occ_polygon(occ,port_parts[0],height)))
                metadata.append({'index':len(ports),'winding':winding['name'],'turn':turn+1,
                                 'sign':int(winding.get('sign',1)),'direction':[0,1,0],
                                 'reference_ohms':float(magnetic.get('reference_ohms',50))})
        entities=[(3,air)]+core_entities+sheets+ports
        fragments,maps=occ.fragment([entities[0]],entities[1:]);occ.synchronize()
        occupied=set();materials=[]
        for i,(group,core) in enumerate(zip(maps[1:1+len(cores)],cores),2):
            tags=[t for d,t in group if d==3]
            if occupied.intersection(tags):raise WorkflowError('Magnetic cores overlap; use separate nonoverlapping material regions')
            occupied.update(tags)
            physical(gmsh,3,tags,i,core['name'])
            materials.append({'Attributes':[i],'Permeability':float(core['mu_r']),
                              'Permittivity':float(core.get('epsilon_r',1))})
        air_tags={t for d,t in maps[0] if d==3}-occupied
        physical(gmsh,3,air_tags,1,'air');materials.append({'Attributes':[1],'Permeability':1.,'Permittivity':1.})
        metal={t for group in maps[1+len(cores):1+len(cores)+len(sheets)] for d,t in group if d==2}
        physical(gmsh,2,metal,100,'winding-sheets')
        source_ports=[]
        for i,(group,meta) in enumerate(zip(maps[-len(ports):],metadata),201):
            tags=[t for d,t in group if d==2];physical(gmsh,2,tags,i,f"{meta['winding']}-turn-{meta['turn']}")
            source_ports.append({'Index':meta['index'],'Attributes':[i],'Direction':meta['direction']})
        outer=[]
        for d,t in gmsh.model.getEntities(2):
            b=gmsh.model.getBoundingBox(d,t)
            if any(abs(b[j]+margin)<2e-6 and abs(b[j+3]+margin)<2e-6 or abs(b[j]-margin)<2e-6 and abs(b[j+3]-margin)<2e-6 for j in range(3)):
                outer.append(t)
        physical(gmsh,2,outer,101,'far-boundary')
        gmsh.model.mesh.generate(3);gmsh.write(str(out/'board.msh'))
        driven=case.get('analysis')=='magnetic-driven'
        boundaries={'PEC':{'Attributes':[100,101]}}
        solver={'Order':int(mesh.get('order',2)),'Linear':linear_settings(case,estimator_multigrid=True)}
        if driven:
            boundaries['PEC']={'Attributes':[100]};boundaries['Absorbing']={'Attributes':[101],'Order':1}
            boundaries['LumpedPort']=[dict(p,R=float(magnetic.get('reference_ohms',50)),Excitation=p['Index']==1) for p in source_ports]
            solver['Driven']={'Samples':[{'Type':'Point','Freq':[f/1e9 for f in case.get('frequencies_hz',[1e5,1e6,4e6])],'SaveStep':1}]}
        else:
            boundaries['SurfaceCurrent']=source_ports
            solver['Magnetostatic']={'Save':len(ports),'InactivePorts':'Open'}
        config={'Problem':{'Type':'Driven' if driven else 'Magnetostatic','Output':'postpro','Verbose':1},
                'Model':{'Mesh':'board.msh','L0':.001},'Domains':{'Materials':materials},
                'Boundaries':boundaries,'Solver':solver}
        write_json(out/'case.json',config)
        write_json(out/'geometry.json',{'dimension':3,'analysis':case['analysis'],
            'component':component['ref'],'placement_on_board_mm':component['position'],
            'component_value':component['value'],
            'turn_ports':metadata,'windings':[w['name'] for w in windings],
            'assumptions':case['assumptions'],
            'scope':'isolated internal component model; PCB copper and leads omitted',
            'mesh_nodes':len(gmsh.model.mesh.getNodes()[0])})
    finally:gmsh.finalize()

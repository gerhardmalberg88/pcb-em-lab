"""Board-local 3D fields: copper sheets, plated holes, dielectrics and connector pins."""
import math
from pathlib import Path
from collections import defaultdict
from .common import WorkflowError, write_json
from .geometry import configure, physical, planar_polygons, parts, occ_polygon, material, linear_settings


def pcb_case(board,case,out):
    import gmsh
    from shapely.geometry import Point, Polygon, box, LineString
    from shapely.affinity import rotate
    from shapely.ops import unary_union
    region,copper=planar_polygons(board,case.get('region_mm'))
    if region.is_empty:raise WorkflowError('Configured region does not intersect the board')
    mesh=case.get('mesh',{});configure(gmsh,mesh)
    try:
        occ=gmsh.model.occ
        layer_lookup={x['name']:x for x in board['stackup']}
        top=max(x['z_top_mm'] for x in board['stackup']);bottom=min(x['z_bottom_mm'] for x in board['stackup'])
        hole_shapes=[];holes=[]
        for hole in board['holes']:
            a,b=hole['drill'];radius=min(a,b)/2
            if radius<=0:continue
            x,y=hole['center']
            if abs(a-b)<1e-8:shape=Point(x,y).buffer(radius,quad_segs=12)
            else:
                length=abs(a-b)
                line=LineString([(x-length/2,y),(x+length/2,y)]) if a>b else LineString([(x,y-length/2),(x,y+length/2)])
                shape=rotate(line.buffer(radius,quad_segs=12),-hole['angle_deg'],origin=(x,y))
            if not region.intersects(shape):continue
            if not region.buffer(1e-7).covers(shape):
                raise WorkflowError('The modeled board region cuts a drilled hole; move the crop boundary beyond the complete hole')
            copper_layers={layer['name'] for layer in board['stackup'] if layer['kind']=='copper'}
            if hole['plated'] and set(hole['layers'])!=copper_layers:
                raise WorkflowError('This initial 3D generator supports through holes; blind/buried vias need a depth-resolved drill model before solving')
            hole_shapes.append(shape);holes.append((hole,shape))
        drill_union=unary_union(hole_shapes)
        drilled=region.difference(drill_union)
        components={x['ref']:x for x in board['components']}
        connector_configs=case.get('connectors',[])
        connector_top=max([float(x.get('height_mm',6)) for x in connector_configs]+[0])
        margin=float(case.get('air_margin_mm',3))
        xmin,ymin,xmax,ymax=region.bounds
        air=occ.addBox(xmin-margin,ymin-margin,bottom-margin,xmax-xmin+2*margin,ymax-ymin+2*margin,top-bottom+connector_top+2*margin)
        domains=[];properties=[]
        # Merge adjacent slabs only when their material tensors are identical.
        # Etched space in a copper layer inherits adjacent laminate properties.
        slabs=[]
        laminate=[x for x in board['stackup'] if x['kind']=='dielectric' and not x['name'].endswith('.Mask')]
        for layer in board['stackup']:
            props=material(layer,case)
            if layer['kind']=='copper' and layer['name'] not in case.get('materials',{}):
                nearest=min(laminate,key=lambda x:abs(x['z_top_mm']-layer['z_top_mm']))
                props=material(nearest,case)
            if slabs and slabs[-1]['properties']==props:
                slabs[-1]['bottom']=layer['z_bottom_mm']
            else:slabs.append({'top':layer['z_top_mm'],'bottom':layer['z_bottom_mm'],'properties':props})
        for slab in slabs:
            for polygon in parts(drilled,'Polygon'):
                surface=occ_polygon(occ,polygon,slab['bottom'])
                volume=next((d,t) for d,t in occ.extrude([(2,surface)],0,0,slab['top']-slab['bottom']) if d==3)
                domains.append(volume);properties.append(slab['properties'])
        sheets=[];sheet_nets=[]
        copper_z={}
        for (name,net),shape in copper.items():
            layer=layer_lookup[name];z=(layer['z_top_mm']+layer['z_bottom_mm'])/2
            copper_z[name]=z
            for polygon in parts(shape.difference(drill_union),'Polygon'):
                if polygon.area>1e-9:
                    sheets.append((2,occ_polygon(occ,polygon,z)));sheet_nets.append(net)
        # Plated barrels are thin PEC sheets, not fictitious solid-filled holes.
        for hole,shape in holes:
            if not hole['plated']:continue
            if not hole['layers']:continue
            z0=min(layer_lookup[x]['z_bottom_mm'] for x in hole['layers'])
            z1=max(layer_lookup[x]['z_top_mm'] for x in hole['layers'])
            for polygon in parts(shape,'Polygon'):
                surface=occ_polygon(occ,polygon,z0)
                extruded=occ.extrude([(2,surface)],0,0,z1-z0)
                volumes=[(d,t) for d,t in extruded if d==3]
                walls=[(d,t) for d,t in extruded[1:] if d==2]
                occ.remove(volumes,recursive=False)
                occ.remove([(2,surface),extruded[0]],recursive=False)
                sheets.extend(walls);sheet_nets.extend([hole['net']]*len(walls))
        metal_volumes=[];metal_nets=[];pin_tops={}
        for item in case.get('mechanicals',[]):
            path=(Path('/project')/item['step']).resolve()
            if not path.is_relative_to('/project') or not path.is_file():
                raise WorkflowError(f'Mechanical STEP not found within the project: {item["step"]}')
            objects=occ.importShapes(str(path),highestDimOnly=True)
            if not objects or any(d!=3 for d,t in objects):
                raise WorkflowError('Mechanical STEP must contain closed solids')
            scale=item.get('scale',[1,1,1]);occ.dilate(objects,0,0,0,*scale)
            for axis,angle in zip(((1,0,0),(0,1,0),(0,0,1)),item.get('rotation_xyz_deg',[0,0,0])):
                if angle:occ.rotate(objects,0,0,0,*axis,math.radians(angle))
            occ.translate(objects,*item.get('translation_mm',[0,0,0]))
            for dim,tag in objects:
                bounds=occ.getBoundingBox(dim,tag)
                limits=(xmin-margin,ymin-margin,bottom-margin,xmax+margin,ymax+margin,top+connector_top+margin)
                if any(bounds[j]<limits[j]-1e-6 or bounds[j+3]>limits[j+3]+1e-6 for j in range(3)):
                    raise WorkflowError('Mechanical solid extends outside the air domain; enlarge air_margin_mm or crop it explicitly')
            if item.get('material')=='PEC':
                metal_volumes.extend(objects);metal_nets.extend([item.get('name','mechanical')]*len(objects))
            else:
                if float(item.get('epsilon_r',0))<=0:raise WorkflowError('Mechanical dielectric needs positive epsilon_r')
                domains.extend(objects);properties.extend([{'Permittivity':float(item['epsilon_r']),
                    'Permeability':float(item.get('mu_r',1)),'LossTan':float(item.get('loss_tangent',0))}]*len(objects))
        for settings in connector_configs:
            ref=settings['ref']
            if ref not in components:raise WorkflowError(f'Connector {ref} not found')
            height=float(settings['height_mm']);width=float(settings['pin_width_mm'])
            for pad in components[ref]['pads']:
                x,y=pad['position']
                if not region.covers(Point(x,y)):continue
                z=copper_z.get('F.Cu',-.0175)
                metal_volumes.append((3,occ.addBox(x-width/2,y-width/2,z,width,width,height-z)))
                metal_nets.append(pad['net']);pin_tops[(ref,pad['number'])]=(x,y,height)
                # Explicit ideal solder fill joins through-hole contacts to barrels.
                for hole,shape in holes:
                    if hole.get('ref')==ref and hole.get('number')==pad['number']:
                        for polygon in parts(shape,'Polygon'):
                            surface=occ_polygon(occ,polygon,bottom)
                            volume=next((d,t) for d,t in occ.extrude([(2,surface)],0,0,-bottom) if d==3)
                            metal_volumes.append(volume);metal_nets.append(pad['net'])
        ports=[];port_metadata=[]
        for i,port in enumerate(case.get('ports',[]),1):
            endpoints=[];nets=[]
            for terminal in ('positive','negative'):
                ref,number=port[terminal].split(':',1)
                if ref not in components:raise WorkflowError(f'Port component {ref} not found')
                pads=[p for p in components[ref]['pads'] if p['number']==number]
                if len(pads)!=1:raise WorkflowError(f'Port {ref}:{number} must resolve to one pad')
                pad=pads[0];nets.append(pad['net'])
                expected=port.get(terminal+'_net')
                if expected is not None and pad['net']!=expected:
                    raise WorkflowError(f'Port {i} {terminal} {ref}:{number} is on {pad["net"]}, expected {expected}; review polarity after the PCB change')
                point=port.get(terminal+'_xy_mm')
                if point is not None:
                    copper_shape=copper.get(('F.Cu',pad['net']))
                    if copper_shape is None or not copper_shape.covers(Point(point)):
                        raise WorkflowError(f'Port {i} {terminal} coordinate does not touch {pad["net"]}')
                    endpoints.append((*point,copper_z['F.Cu']))
                else:
                    endpoints.append(pin_tops.get((ref,number),(*pad['position'],copper_z['F.Cu'])))
            p,n=endpoints
            if abs(p[2]-n[2])>1e-6:raise WorkflowError('Port endpoints must share a height')
            dx,dy=n[0]-p[0],n[1]-p[1];length=math.hypot(dx,dy)
            if length<=0:raise WorkflowError('Port endpoints coincide')
            w=float(port.get('width_mm',.12));ux,uy=-dy/length*w/2,dx/length*w/2
            rectangle=Polygon([(p[0]+ux,p[1]+uy),(n[0]+ux,n[1]+uy),(n[0]-ux,n[1]-uy),(p[0]-ux,p[1]-uy)])
            # Remove the conductors' planar footprints from the integration sheet.
            if p[2]>0:
                masks=[]
                for settings in connector_configs:
                    width=float(settings['pin_width_mm'])
                    for x,y,z in pin_tops.values():masks.append(box(x-width/2,y-width/2,x+width/2,y+width/2))
                port_shape=rectangle.difference(unary_union(masks))
            else:
                masks=[shape for (layer,net),shape in copper.items() if layer=='F.Cu']
                port_shape=rectangle.difference(unary_union(masks))
            pieces=parts(port_shape,'Polygon')
            if len(pieces)!=1:raise WorkflowError(f'Port {i} crosses other copper or is disconnected; refine endpoints')
            if not math.isclose(pieces[0].area,pieces[0].minimum_rotated_rectangle.area,rel_tol=1e-6,abs_tol=1e-10):
                raise WorkflowError(f'Port {i} gap is not rectangular; select parallel straight conductor segments or rectangular contacts for the uniform lumped port')
            ports.append((2,occ_polygon(occ,pieces[0],p[2])))
            port_metadata.append({'index':i,'name':port.get('name',f'port-{i}'),
                'positive':port['positive'],'negative':port['negative'],'nets':nets,'endpoints_mm':endpoints,
                'direction':[dx/length,dy/length,0.0],'reference_ohms':float(port.get('reference_ohms',100))})
        if not ports:raise WorkflowError('Driven 3D cases require at least one explicit differential port')
        entries=[(3,air)]+domains+metal_volumes+sheets+ports
        fragments,maps=occ.fragment([entries[0]],entries[1:]);occ.synchronize()
        write_json(out/'fragment-map.json',{'entries':entries,'maps':maps,
            'domains':len(domains),'metal_volumes':len(metal_volumes),
            'sheet_nets':sheet_nets,'metal_nets':metal_nets})
        n_domain=len(domains);n_metals=len(metal_volumes);n_sheets=len(sheets)
        excluded=set();metal_boundaries=set()
        for group in maps[1+n_domain:1+n_domain+n_metals]:
            for dim,tag in group:
                if dim==3:
                    excluded.add(tag)
                    metal_boundaries.update(t for d,t in gmsh.model.getBoundary([(3,tag)],oriented=False) if d==2)
        for group in maps[1+n_domain+n_metals:1+n_domain+n_metals+n_sheets]:
            metal_boundaries.update(t for d,t in group if d==2)
        occ.remove([(3,t) for t in excluded],recursive=False);occ.synchronize()
        active_surfaces=set();embedded_surfaces=set()
        for dim,tag in gmsh.model.getEntities(3):
            active_surfaces.update(t for d,t in gmsh.model.getBoundary([(dim,tag)],oriented=False) if d==2)
            embedded_surfaces.update(t for d,t in gmsh.model.mesh.getEmbedded(dim,tag) if d==2)
        active_surfaces.update(embedded_surfaces)
        metal_boundaries &= active_surfaces
        materials=[];occupied=set();groups={}
        for i,(group,props) in enumerate(zip(maps[1:1+n_domain],properties),2):
            tags={t for d,t in group if d==3}-excluded
            if not tags:continue
            if tags & occupied:raise WorkflowError('Dielectric volumes overlap; fix mechanical placement or material regions')
            physical(gmsh,3,tags,i,f'dielectric-{i}');occupied.update(tags)
            materials.append({'Attributes':[i],**props});groups[str(i)]=f'dielectric-{i}'
        air_tags={t for d,t in maps[0] if d==3}-occupied-excluded
        physical(gmsh,3,air_tags,1,'air');materials.append({'Attributes':[1],'Permittivity':1.,'Permeability':1.})
        port_groups=[]
        for i,(group,metadata) in enumerate(zip(maps[-len(ports):],port_metadata),201):
            tags={t for d,t in group if d==2}
            physical(gmsh,2,tags,i,metadata['name']);metal_boundaries-=tags
            groups[f'boundary:{i}']=metadata['name']
            port_groups.append({'Index':metadata['index'],'Attributes':[i],
                'Direction':metadata['direction'],'R':metadata['reference_ohms'],'Excitation':metadata['index']==1})
        # Keep external metal-solid interfaces separate from two-sided internal
        # copper sheets, as required by Palace's boundary bookkeeping.
        external_metal={t for t in metal_boundaries if t not in embedded_surfaces
                        and len(gmsh.model.getAdjacencies(2,t)[0])==1}
        pec_attributes=[]
        for ident,tags,label in [(100,metal_boundaries-external_metal,'internal-copper'),
                                 (102,external_metal,'external-metal')]:
            if tags:
                physical(gmsh,2,tags,ident,label);pec_attributes.append(ident)
                groups[f'boundary:{ident}']=label
        # Only exterior faces of the air box absorb; cropped board edges retain their material boundary.
        outer=[];extent=(xmin-margin,ymin-margin,bottom-margin,xmax+margin,ymax+margin,top+connector_top+margin)
        for dim,tag in gmsh.model.getEntities(2):
            bounds=gmsh.model.getBoundingBox(dim,tag)
            if any(abs(bounds[j]-extent[j])<2e-6 and abs(bounds[j+3]-extent[j])<2e-6 for j in range(3)) or any(abs(bounds[j]-extent[j+3])<2e-6 and abs(bounds[j+3]-extent[j+3])<2e-6 for j in range(3)):
                outer.append(tag)
        physical(gmsh,2,outer,101,'air-outer')
        groups['boundary:101']='air-outer'
        gmsh.option.setNumber('Mesh.Algorithm3D',10)
        gmsh.write(str(out/'geometry.brep'))
        try:
            gmsh.model.mesh.generate(3)
        except Exception:
            gmsh.write(str(out/'failed-surface.msh'))
            raise
        gmsh.write(str(out/'board.msh'))
        frequencies=case.get('frequencies_hz',[1e6,4e6,10e6])
        config={'Problem':{'Type':'Driven','Output':'postpro','Verbose':1},'Model':{'Mesh':'board.msh','L0':.001},
            'Domains':{'Materials':materials},'Boundaries':{'PEC':{'Attributes':pec_attributes},
                'Absorbing':{'Attributes':[101],'Order':1},'LumpedPort':port_groups},
            'Solver':{'Order':int(mesh.get('order',2)),
                'Driven':{'Samples':[{'Type':'Point','Freq':[float(f)/1e9 for f in frequencies],'SaveStep':1}]},
                'Linear':linear_settings(case,estimator_multigrid=True)}}
        write_json(out/'case.json',config)
        write_json(out/'geometry.json',{'dimension':3,'groups':groups,'ports':port_metadata,
            'region_mm':list(region.bounds),'assumptions':case.get('assumptions',[]),
            'mesh_nodes':len(gmsh.model.mesh.getNodes()[0]),'copper_model':'PEC sheets at saved copper midplanes'})
    finally:gmsh.finalize()

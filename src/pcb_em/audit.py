"""Record source geometry checks without rewriting or repairing the PCB."""
import math
from collections import Counter
from .common import WorkflowError, write_json


def audit_source(board, case, output):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    layers=board['stackup']
    for index,layer in enumerate(layers):
        if not math.isclose(layer['z_top_mm']-layer['z_bottom_mm'],layer['thickness_mm'],abs_tol=1e-9):
            raise WorkflowError(f'Stackup height mismatch for {layer["name"]}')
        if index and not math.isclose(layers[index-1]['z_bottom_mm'],layer['z_top_mm'],abs_tol=1e-9):
            raise WorkflowError(f'Gap or overlap in stackup before {layer["name"]}')
    def shape(polygons):
        return unary_union([Polygon(p['outer'],p['holes']).buffer(0) for p in polygons])
    # A zone-only keepout can intentionally contain pads, tracks and vias.
    relevant={k for keepout in board['keepouts'] for k,v in keepout.get('prohibits',{}).items() if v}
    key_for={'zone':'zone_fills','track':'tracks','via':'vias','pad':'pads'}
    copper={}
    for item in board['copper']:
        kind=key_for[item['kind']]
        if kind in relevant:copper.setdefault((item['layer'],kind),[]).extend(item['polygons'])
    copper={key:shape(polygons) for key,polygons in copper.items()}
    keepouts=[]
    tolerance=float(board['polygon_chord_error_mm'])
    for index,item in enumerate(board['keepouts']):
        area=shape(item['polygons']);interior=area.buffer(-tolerance);intersections=[]
        for layer in item['layers']:
            for kind,prohibited in item.get('prohibits',{}).items():
                source=copper.get((layer,kind))
                if prohibited and source is not None:
                    overlap=area.intersection(source).area
                    if overlap>1e-8:
                        inside=interior.intersection(source).area
                        intersections.append({'layer':layer,'kind':kind,'area_mm2':overlap,
                            'interior_area_mm2':inside,
                            'within_polygon_tolerance':inside<=1e-8})
        keepouts.append({'index':index,'name':item.get('name',''),'area_mm2':area.area,
                         'prohibits':item.get('prohibits',{}),'saved_copper_intersections':intersections})
    components={c['ref']:c for c in board['components']};ports=[]
    for port in case.get('ports',[]):
        terminals={}
        for terminal in ('positive','negative'):
            ref,number=port[terminal].split(':',1)
            pads=[p for p in components.get(ref,{}).get('pads',[]) if p['number']==number]
            if len(pads)!=1:raise WorkflowError(f'{port[terminal]} must resolve to one saved PCB pad')
            pad=pads[0];expected=port.get(terminal+'_net')
            if expected is not None and expected!=pad['net']:
                raise WorkflowError(f'{port[terminal]} is on {pad["net"]}, expected {expected}; review port polarity')
            terminals[terminal]={'pad':port[terminal],'net':pad['net'],'position_mm':pad['position']}
        ports.append({'name':port.get('name',''),**terminals})
    total=sum(l['thickness_mm'] for l in layers)
    report={'source_sha256':board['sha256'],'kicad_version':board['kicad_version'],
        'physical_stackup_thickness_mm':total,'declared_thickness_mm':board.get('declared_thickness_mm'),
        'stackup_heights_contiguous':True,'stackup':layers,
        'copper_items':len(board['copper']),'component_count':len(components),
        'holes_by_kind':dict(Counter(h['kind'] for h in board['holes'])),
        'plated_holes':sum(h['plated'] for h in board['holes']),
        'nonplated_holes':sum(not h['plated'] for h in board['holes']),
        'keepout_edge_tolerance_mm':tolerance,
        'keepouts':keepouts,'ports':ports,'extraction_warnings':board['warnings'],
        'scope':'Saved geometry audit; keepout overlaps are reported without modifying copper. This is not KiCad DRC or isolation qualification.'}
    write_json(output,report)
    return report

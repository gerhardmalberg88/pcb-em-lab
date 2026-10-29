import pytest
gmsh=pytest.importorskip('gmsh')
from shapely.geometry import Point
from pcb_em.geometry import occ_polygon, cross_section


def test_drilled_polygon_preserves_hole_area():
    gmsh.initialize()
    try:
        shape=Point(320,120).buffer(1).difference(Point(320,120).buffer(.45))
        face=occ_polygon(gmsh.model.occ,shape,-.0175)
        assert gmsh.model.occ.getMass(2,face)==pytest.approx(shape.area,rel=1e-8)
    finally:gmsh.finalize()


def test_2d_copper_at_crop_edge_has_no_orphan_boundary_elements(tmp_path):
    def polygon(x0,x1):
        return {'outer':[[x0,0],[x1,0],[x1,2],[x0,2]],'holes':[]}
    layers=[]
    for name,kind,top,bottom in [('F.Cu','copper',0,-.035),
                               ('dielectric 1','dielectric',-.035,-1),
                               ('B.Cu','copper',-1,-1.035)]:
        layers.append(dict(name=name,kind=kind,z_top_mm=top,z_bottom_mm=bottom,
                           thickness_mm=top-bottom,epsilon_r=4,loss_tangent=0))
    board={'outline':[polygon(0,10)],'stackup':layers,'holes':[],
           'copper':[{'layer':layer,'net':net,'polygons':[polygon(a,b)]}
                     for layer,net,a,b in [('F.Cu','GND',0,3),('F.Cu','P',4.5,4.7),
                                          ('F.Cu','N',5,5.2),('B.Cu','GND',0,10)]]}
    case={'cross_section':{'line_mm':[[0,1],[10,1]],'pair':['P','N'],'air_margin_mm':1},
          'frequency_hz':4e6,'mesh':{'fine_mm':.15,'coarse_mm':1}}
    cross_section(board,case,tmp_path)
    lines=(tmp_path/'board.msh').read_text().splitlines()
    start=lines.index('$Elements');count=int(lines[start+1]);edges=set();boundary=[]
    for line in lines[start+2:start+2+count]:
        values=list(map(int,line.split()));kind=values[1];nodes=values[3+values[2]:]
        if kind==2:
            edges.update(tuple(sorted((a,b))) for a,b in zip(nodes,nodes[1:]+nodes[:1]))
        elif kind==1:boundary.append(tuple(sorted(nodes)))
    assert boundary and all(edge in edges for edge in boundary)

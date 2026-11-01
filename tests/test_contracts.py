import json
from pathlib import Path
import pytest
from pcb_em.common import WorkflowError
from pcb_em.runtime import Runtime
from pcb_em.pipeline import load_case, valid_cache, complete_stage, run_case, source_inputs
from pcb_em.build import environment, input_key
from pcb_em.extract import stackup


class SelectionRuntime(Runtime):
    def __init__(self,cpu=True,cuda=False,device=False):
        self.available={'cpu':cpu,'cuda':cuda};self.device=device;self.probes=[]
    def image_exists(self,kind):
        self.probes.append(kind);return self.available[kind]
    def gpu_check(self,count=1):
        self.probes.append('gpu');return self.available['cuda'] and self.device,'device unavailable'


def test_cpu_never_probes_nvidia():
    rt=SelectionRuntime()
    assert rt.select('cpu')[0]=='cpu'
    assert rt.probes==['cpu']


def test_auto_and_explicit_cuda_contract():
    rt=SelectionRuntime(cuda=True)
    assert rt.select('auto')==('cpu','Using CPU: device unavailable')
    with pytest.raises(WorkflowError,match='CUDA requested'):rt.select('cuda')
    rt.device=True
    assert rt.select('auto')[0]=='cuda'


def test_cpu_environment_does_not_request_cuda():
    specs=environment('cpu')['spack']['specs']
    assert len(specs)==1 and '~cuda' in specs[0] and '^cuda' not in specs[0]
    assert 'cuda_arch=80' in environment('cuda','80')['spack']['specs'][0]
    with pytest.raises(WorkflowError):environment('cuda','75; touch /tmp/test')


def test_cache_checks_artifact_content(tmp_path):
    (tmp_path/'result.csv').write_text('1,2\n')
    complete_stage(tmp_path,'abc',{'stage':'solve'})
    assert valid_cache(tmp_path,'abc')
    assert not valid_cache(tmp_path,'new-source-hash')
    (tmp_path/'result.csv').write_text('1,3\n')
    assert not valid_cache(tmp_path,'abc')


def test_build_cache_tracks_dependency_locks(tmp_path):
    data=environment('cpu')
    (tmp_path/'spack.json').write_text(json.dumps(data))
    (tmp_path/'spack.lock').write_text('resolved dependency A')
    initial=input_key('base',data,tmp_path)
    assert input_key('base',data,tmp_path)==initial
    (tmp_path/'spack.lock').write_text('resolved dependency B')
    assert input_key('base',data,tmp_path)!=initial


def test_source_cache_tracks_referenced_models_outside_library_folder(tmp_path):
    design=tmp_path/'design';design.mkdir()
    models=tmp_path/'models';models.mkdir()
    model=models/'package.step';model.write_text('first geometry')
    board=design/'board.kicad_pcb'
    board.write_text('(kicad_pcb (footprint (model "${KIPRJMOD}/../models/package.step")))')
    before=source_inputs(board,tmp_path)
    assert str(model) in before
    model.write_text('revised geometry')
    after=source_inputs(board,tmp_path)
    assert before[str(board)]==after[str(board)] and before[str(model)]!=after[str(model)]


def case_file(tmp_path):
    (tmp_path/'board.kicad_pcb').write_text('saved design')
    p=tmp_path/'case.json'
    p.write_text(json.dumps({'board':'board.kicad_pcb','mode':'2d','analysis':'boundary-mode',
                           'cross_section':{'line_mm':[[0,0],[1,0]],'pair':['p','n']},'output':'results/test',
                           'execution':{'backend':'auto','mpi_ranks':2}}))
    return p


def test_cli_overrides_and_missing_inputs(tmp_path):
    p=case_file(tmp_path)
    case=load_case(p,backend='cuda',ranks=1)[1]
    assert case['execution']['backend']=='cuda' and case['execution']['mpi_ranks']==1
    (tmp_path/'board.kicad_pcb').unlink()
    with pytest.raises(WorkflowError,match='Board not found'):load_case(p)


def test_kicad_stackup_sublayers_and_z_origin():
    with pytest.raises(WorkflowError,match='KiCad Board Setup'):
        stackup('(kicad_pcb (general (thickness 1.6)))')
    layers=stackup('''(stackup (layer "F.Mask" (thickness 0.02))
    (layer "F.Cu" (thickness 0.035))
    (layer "dielectric 1" (type "prepreg") (thickness 0.07) (epsilon_r 4.3)
      addsublayer (thickness 0.12) (epsilon_r 4.4))
    (layer "B.Cu" (thickness 0.035)))''')
    assert len(layers)==5
    assert layers[1]['z_top_mm']==pytest.approx(0)
    assert layers[-1]['z_bottom_mm']==pytest.approx(-.26)
    assert layers[3]['epsilon_r']==4.4


def test_keepout_audit_respects_rule_types_and_polygon_tolerance(tmp_path):
    from pcb_em.audit import audit_source
    def polygon(x0,y0,x1,y1):return {'outer':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],'holes':[]}
    board={'stackup':[{'name':'F.Cu','z_top_mm':0,'z_bottom_mm':-.035,'thickness_mm':.035}],
           'polygon_chord_error_mm':.002,'sha256':'test','kicad_version':'test',
           'components':[],'holes':[],'warnings':[],
           'keepouts':[{'layers':['F.Cu'],'polygons':[polygon(0,0,2,2)],
                        'prohibits':{'zone_fills':True,'tracks':False}}],
           'copper':[{'kind':'zone','layer':'F.Cu','polygons':[polygon(1.999,0,3,2)]},
                     {'kind':'track','layer':'F.Cu','polygons':[polygon(0,0,2,2)]}]}
    r=audit_source(board,{},tmp_path/'audit.json')
    intersections=r['keepouts'][0]['saved_copper_intersections']
    assert len(intersections)==1 and intersections[0]['kind']=='zone_fills'
    assert intersections[0]['within_polygon_tolerance']
    board['copper'][0]['polygons']=[polygon(1,0,3,2)]
    r=audit_source(board,{},tmp_path/'audit.json')
    assert not r['keepouts'][0]['saved_copper_intersections'][0]['within_polygon_tolerance']


def test_solver_failure_never_switches_backend(tmp_path):
    p=case_file(tmp_path)
    class FakeRuntime:
        selected=[];runs=[]
        def image_exists(self,kind):return True
        def image_id(self,kind):return kind+'-immutable-id'
        def select(self,backend,count):self.selected.append(backend);return 'cuda','ready'
        def run(self,kind,command,**kw):
            self.runs.append(kind);out=kw['output']
            if 'pcb_em.extract' in command:(out/'extract/board.json').write_text('{}')
            elif 'pcb_em.geometry' in command:
                (out/'mesh/board.msh').write_text('mesh')
                (out/'mesh/case.json').write_text(json.dumps({'Problem':{'Type':'BoundaryMode'},'Model':{},'Solver':{}}))
            else:raise WorkflowError('numerical failure')
    rt=FakeRuntime()
    with pytest.raises(WorkflowError,match='numerical failure'):
        run_case(p,backend='auto',ranks=1,stage='solve',runtime=rt)
    assert rt.selected==['auto'] and rt.runs==['tools','tools','cuda']
    assert not (tmp_path/'results/test/solve/stage.json').exists()
    provenance=json.loads((tmp_path/'results/test/provenance.json').read_text())
    assert provenance['status']=='failed' and provenance['last_stage']=='mesh'
    assert provenance['backend']=='cuda' and provenance['error']=='numerical failure'
    assert (tmp_path/'board.kicad_pcb').read_text()=='saved design'

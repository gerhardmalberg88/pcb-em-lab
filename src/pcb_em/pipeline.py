"""Stage orchestration, content-based caching and source preservation."""
import copy
import json
import os
import re
import shutil
import time
from pathlib import Path
from .common import ROOT, WorkflowError, digest, fingerprint, read_config, write_json, positive
from .runtime import Runtime

STAGES=('extract','mesh','solve','postprocess')


def verify_solver_log(path):
    # Palace can emit a convergence warning and still return zero. Such a run
    # must not become a successful cached simulation or trigger CPU fallback.
    text=Path(path).read_text(errors='replace').lower()
    if 'linear solver did not converge' in text:
        raise WorkflowError(f'Palace reported a nonconverged linear solve; inspect {path}')


def load_case(path,mode=None,backend=None,ranks=None,threads=None,gpus=None):
    path=Path(path).resolve();case=read_config(path)
    if mode:case['mode']=mode
    if case.get('mode') not in ('2d','3d'):raise WorkflowError('Case mode must be 2d or 3d')
    analysis=case.setdefault('analysis','boundary-mode' if case['mode']=='2d' else 'driven')
    if analysis not in ('boundary-mode','driven','magnetostatic','magnetic-driven'):
        raise WorkflowError('analysis must be boundary-mode, driven, magnetostatic or magnetic-driven')
    if (case['mode']=='2d') != (analysis=='boundary-mode'):
        raise WorkflowError('BoundaryMode requires mode 2d; PCB Driven and internal magnetics require mode 3d')
    if not isinstance(case.get('board'),str):raise WorkflowError('Case must name a board path')
    board=(path.parent/case['board']).resolve()
    project=(path.parent/case.get('project_root','.')).resolve()
    if not board.is_relative_to(project):raise WorkflowError('Board must be inside project_root')
    if not board.is_file():raise WorkflowError(f'Board not found: {board}')
    out=(path.parent/case.get('output',f'results/{path.stem}')).resolve()
    if out==project or out==board.parent or project.is_relative_to(out):
        raise WorkflowError('Output must be a dedicated results directory, not a source root')
    execution=dict(case.get('execution',{}))
    execution['backend']=backend or execution.get('backend','auto')
    if execution['backend'] not in ('auto','cpu','cuda'):raise WorkflowError('execution.backend must be auto, cpu or cuda')
    for key,value,default in [('mpi_ranks',ranks,None),('threads_per_rank',threads,1),('gpu_count',gpus,1)]:
        if value is None and execution.get(key,default) is None:
            execution.pop(key,None)
            continue
        try:execution[key]=positive(value if value is not None else execution.get(key,default))
        except (ValueError,TypeError) as error:raise WorkflowError(f'execution.{key} must be a positive integer') from error
    case['execution']=execution
    exports=case.get('exports',{})
    if not isinstance(exports,dict) or not isinstance(exports.get('step',False),bool):
        raise WorkflowError('exports.step must be true or false')
    return path,case,board,project,out


def source_inputs(board,project_root=None):
    inputs={str(board):digest(board)}
    project=board.with_suffix('.kicad_pro')
    if project.exists():inputs[str(project)]=digest(project)
    # Follow referenced local models, including paths outside a conventional
    # library directory. System-library versions are covered by the tools image.
    project_root=Path(project_root or board.parent).resolve()
    for token in re.findall(r'\(model\s+("(?:\\.|[^"\\])*"|[^\s()]+)',board.read_text()):
        raw=json.loads(token) if token.startswith('"') else token
        p=Path(os.path.expandvars(raw.replace('${KIPRJMOD}',str(board.parent))))
        if not p.is_absolute():p=board.parent/p
        p=p.resolve()
        if p.is_relative_to(project_root) and p.is_file():inputs[str(p)]=digest(p)
    return inputs


def valid_cache(folder,key):
    manifest=folder/'stage.json'
    if not manifest.exists():return False
    try:
        data=json.loads(manifest.read_text())
        return data['key']==key and bool(data['artifacts']) and all(
            (folder/name).is_file() and digest(folder/name)==expected
            for name,expected in data['artifacts'].items())
    except (OSError,KeyError,ValueError):return False


def complete_stage(folder,key,metadata):
    files={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*')
           if p.is_file() and p.name not in ('stage.json','stage.log')}
    if not files:raise WorkflowError('Stage produced no artifacts')
    write_json(folder/'stage.json',{'key':key,'artifacts':files,**metadata})


def run_case(path,*,mode=None,backend=None,ranks=None,threads=None,gpus=None,stage='all',force=False,runtime=None):
    path,case,board,project,out=load_case(path,mode,backend,ranks,threads,gpus)
    runtime=runtime or Runtime()
    if not runtime.image_exists('tools'):raise WorkflowError('Tools image missing; run pcb-em build --profile tools')
    out.mkdir(parents=True,exist_ok=True)
    source=source_inputs(board,project)
    for item in case.get('mechanicals',[]):
        asset=(project/item['step']).resolve()
        if not asset.is_relative_to(project) or not asset.is_file():
            raise WorkflowError(f'Mechanical STEP must exist inside project_root: {item["step"]}')
        source[str(asset)]=digest(asset)
    implementation={str(p.relative_to(ROOT)):digest(p)
                    for directory in ('src','scripts') for p in (ROOT/directory).rglob('*.py')}
    physical=copy.deepcopy(case)
    for key in ('execution','output','board','project_root'):physical.pop(key,None)
    relative_source={str(Path(p).relative_to(project)):h for p,h in source.items()}
    current={'source':relative_source,'physical':physical,
             'tools_image':runtime.image_id('tools')}
    write_json(out/'case.resolved.json',case)
    required=STAGES if stage=='all' else STAGES[:STAGES.index(stage)+1]
    selected=None
    previous=None
    provenance={'case':str(path),'source':source,'configuration':case,
        'implementation':implementation,'tools_image':current['tools_image'],
        'backend':None,'solver_image':None,'last_stage':None,
        'requested_stage':stage,'status':'running','started_unix':time.time()}
    write_json(out/'provenance.json',provenance)
    try:
        for name in required:
            folder=out/name;folder.mkdir(exist_ok=True)
            parameters=dict(current,stage=name,previous=previous)
            if name=='extract':
                parameters.pop('physical')
                parameters['exports']=case.get('exports',{})
            shared=['common.py','runtime.py','pipeline.py']
            modules={'extract':['extract.py'],'mesh':['geometry.py','pcb3d.py','magnetics.py','audit.py'],
                     'solve':[],'postprocess':['postprocess.py']}
            files=['src/pcb_em/'+p for p in shared+modules[name]]
            if name=='postprocess':files+=['scripts/render.py','scripts/winding-fields.py']
            parameters['implementation']={p:implementation[p] for p in files}
            if name in ('solve','postprocess'):
                if selected is None:
                    selected,reason=runtime.select(case['execution']['backend'],case['execution']['gpu_count'])
                    print(reason,flush=True)
                    effective=dict(backend=selected,
                        mpi_ranks=case['execution'].get('mpi_ranks',1 if selected=='cuda' else 2),
                        threads_per_rank=case['execution']['threads_per_rank'],
                        gpu_count=case['execution']['gpu_count'] if selected=='cuda' else 0)
                    provenance.update(backend=selected,solver_image=runtime.image_id(selected),effective_execution=effective)
                parameters.update(execution=provenance['effective_execution'],selected=selected,solver_image=runtime.image_id(selected))
            key=fingerprint(parameters)
            if not force and valid_cache(folder,key):
                print(f'{name}: cached {key[:12]}',flush=True);previous=key
                provenance['last_stage']=name
                write_json(out/'provenance.json',provenance)
                continue
            print(f'{name}: running {key[:12]}',flush=True)
            # Only these owned stage folders are replaced; never touch design sources.
            shutil.rmtree(folder)
            folder.mkdir()
            if name=='extract':
                runtime.run('tools',['/usr/bin/python3','-m','pcb_em.extract',
                    '/project/'+str(board.relative_to(project)),'/work/extract/board.json'],
                    project=project,output=out,log=folder/'stage.log')
                if case.get('exports',{}).get('step',False):
                    runtime.run('tools',['kicad-cli','pcb','export','step','--force',
                        '--no-components','--include-tracks','--include-pads','--include-zones',
                        '--include-inner-copper','--no-extra-pad-thickness','--user-origin','0x0mm',
                        '--output','/work/extract/board.step',
                        '/project/'+str(board.relative_to(project))],
                        project=project,output=out,log=folder/'stage.log')
                    write_json(folder/'step-export.json',{
                        'file':'board.step','units':'mm','origin':'KiCad user origin 0x0mm',
                        'scope':'KiCad board/copper preview; not the generated EM solver geometry',
                        'components':False})
            elif name=='mesh':
                runtime.run('tools',['pcb-python','-m','pcb_em.geometry','/work/extract/board.json',
                    '/work/case.resolved.json','/work/mesh'],project=project,output=out,log=folder/'stage.log')
            elif name=='solve':
                solve(runtime,selected,case,out,folder)
            else:
                runtime.run('tools',['pcb-python','-m','pcb_em.postprocess','/work'],output=out,log=folder/'stage.log')
                runtime.run('tools',['pvpython','/workflow/scripts/winding-fields.py','/work'],
                            output=out,log=folder/'stage.log')
                runtime.run('tools',['xvfb-run','-a','pvpython','/workflow/scripts/render.py','/work'],
                            output=out,log=folder/'stage.log',env={'LIBGL_ALWAYS_SOFTWARE':'1'})
            changed_code=[p for p in files if not (ROOT/p).is_file() or digest(ROOT/p)!=implementation[p]]
            if changed_code:raise WorkflowError(f'Workflow code changed during {name}; rerun this stage: {changed_code}')
            complete_stage(folder,key,{'stage':name,'backend':selected,'finished_unix':time.time()})
            previous=key
            provenance['last_stage']=name
            write_json(out/'provenance.json',provenance)
        provenance['status']='complete'
    except BaseException as error:
        provenance.update(status='interrupted' if isinstance(error,KeyboardInterrupt) else 'failed',
                          error=str(error))
        raise
    finally:
        changed=[p for p,h in source.items() if not Path(p).is_file() or digest(p)!=h]
        if changed:provenance.update(status='failed',error=f'Source inputs changed during the run: {changed}')
        provenance['finished_unix']=time.time()
        write_json(out/'provenance.json',provenance)
        if changed:raise WorkflowError(provenance['error'])
    print(f'Results: {out}',flush=True)
    return out


def solve(runtime,backend,case,out,folder):
    template=json.loads((out/'mesh/case.json').read_text())
    ports=template.get('Boundaries',{}).get('LumpedPort',[])
    excitations=[p['Index'] for p in ports] if template['Problem']['Type']=='Driven' else [None]
    execution=case['execution'];count=execution['gpu_count'] if backend=='cuda' else 0
    # A GPU run defaults to one MPI rank unless the caller supplies another count.
    ranks=execution.get('mpi_ranks',1 if count else 2)
    if count and ranks>count:
        raise WorkflowError('CUDA MPI ranks exceed gpu_count; set --mpi-ranks 1 for one GPU')
    for excitation in excitations:
        config=copy.deepcopy(template)
        config['Model']['Mesh']='/work/mesh/board.msh'
        suffix=f'excitation-{excitation}' if excitation else 'fields'
        config['Problem']['Output']=f'/work/solve/{suffix}'
        config['Solver']['Device']='GPU' if backend=='cuda' else 'CPU'
        for port in config.get('Boundaries',{}).get('LumpedPort',[]):port['Excitation']=port['Index']==excitation
        target=folder/f'{suffix}.json';write_json(target,config)
        env={'OMP_NUM_THREADS':str(execution['threads_per_rank']),'OPENBLAS_NUM_THREADS':'1'}
        runtime.run(backend,['palace','--dry-run',f'/work/solve/{target.name}'],output=out,
                    gpu_count=count,env=env,log=folder/'stage.log')
        runtime.run(backend,['palace','-np',str(ranks),'-nt',str(execution['threads_per_rank']),
                    f'/work/solve/{target.name}'],output=out,gpu_count=count,env=env,log=folder/'stage.log')
        verify_solver_log(folder/'stage.log')

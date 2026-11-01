"""Repeatable checks with machine-readable evidence, including CPU isolation."""
import json
import time
from .common import ROOT, WorkflowError, call, write_json
from .runtime import Runtime, IMAGES


def doctor(backend='cpu',full=False):
    rt=Runtime();out=ROOT/'results/validation'/backend;out.mkdir(parents=True,exist_ok=True)
    checks=[]
    def check(name,fn):
        try:
            result=fn()
            if hasattr(result,'returncode') and result.returncode:
                raise WorkflowError(result.stderr or result.stdout)
            detail=(result.stdout if hasattr(result,'stdout') else str(result or 'passed'))
            checks.append({'name':name,'passed':True,'detail':detail})
            print(f'PASS {name}',flush=True)
        except (WorkflowError,OSError,ValueError) as error:
            checks.append({'name':name,'passed':False,'detail':str(error)})
            print(f'FAIL {name}: {error}',flush=True)
    check('rootless container runtime',lambda:call([rt.engine,'info'],capture=True))
    selected=None
    try:
        selected,reason=rt.select(backend);print(reason)
    except WorkflowError as error:
        checks.append({'name':'backend selection','passed':False,'detail':str(error)})
    if selected:
        count=1 if selected=='cuda' else 0
        check('Palace version',lambda:rt.run(selected,['palace','--serial','--version'],capture=True,gpu_count=count))
        if selected=='cpu':
            check('CPU image has no GPU device or CUDA dependency',lambda:rt.run('cpu',[
                'python3','/workflow/scripts/check-cpu.py'],capture=True))
    if rt.image_exists('tools'):
        for label,command in [
            ('KiCad CLI',['kicad-cli','version']),
            ('KiCad Python',['/usr/bin/python3','-c','import pcbnew; print(pcbnew.GetBuildVersion())']),
            ('Gmsh and numerical Python',['pcb-python','-c','import gmsh,skrf,numpy,scipy,shapely; gmsh.initialize(); print(gmsh.option.getString("General.Version")); gmsh.finalize()']),
            ('ngspice',['ngspice','--version']),('OpenVAF',['openvaf','--version']),
            ('QucsatorRF',['qucsator_rf','--version']),
            ('FreeCAD Python',['freecadcmd','/workflow/scripts/check-freecad.py']),
            ('FreeCAD to Gmsh STEP units',['pcb-python','/workflow/scripts/check-step.py']),
            ('ParaView headless rendering',['xvfb-run','-a','pvpython','/workflow/scripts/check-render.py']),
        ]:
            check(label,lambda command=command:rt.run('tools',command,output=out,capture=True,
                                                    env={'LIBGL_ALWAYS_SOFTWARE':'1'}))
        if full:
            check('GUI launchers in Xvfb',lambda:rt.run('tools',
                  ['xvfb-run','-a','/usr/bin/python3','/workflow/scripts/check-gui.py'],output=out,capture=True,
                  env={'LIBGL_ALWAYS_SOFTWARE':'1'}))
            check('Touchstone, passive fitting, QucsatorRF, ngspice and Verilog-A',
                  lambda:rt.run('tools',['pcb-python','/workflow/scripts/check-circuits.py'],output=out,capture=True))
    else:checks.append({'name':'tools image','passed':False,'detail':'Run pcb-em build --profile tools'})
    if full and selected:
        if selected=='cuda':
            def memory_failure():
                result=rt.run('cuda',['bash','-c',
                              'ulimit -c 0; exec /usr/local/bin/pcb-em-cuda-memory-check'],
                              capture=True,check=False,gpu_count=1)
                detail=(result.stdout or '')+(result.stderr or '')
                if result.returncode==0 or 'pcb-em: GPU memory exhausted.' not in detail:
                    raise WorkflowError('GPU allocation failure was not reported clearly: '+detail)
                return 'Oversized allocation failed with an explicit GPU-memory error'
            check('GPU allocation failure reporting',memory_failure)
        check('Palace reference examples',lambda:rt.run(selected,
              ['python3','/workflow/scripts/check-palace.py',selected],output=out,capture=True,
              gpu_count=1 if selected=='cuda' else 0,env={'OMP_NUM_THREADS':'1'}))
    write_json(out/'doctor.json',{'checks':checks,'backend':selected,'time_unix':time.time()})
    print(f'Evidence: {out}/doctor.json')
    return 0 if all(c['passed'] for c in checks) else 1

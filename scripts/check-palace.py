"""Run the pinned upstream examples and compare their published reference CSVs."""
import csv
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from pcb_em.pipeline import verify_solver_log

backend=sys.argv[1];base=Path('/opt/palace');work=Path('/work/palace');work.mkdir(exist_ok=True)
checks=[('cpw2d','cpw2d_thin.json','cpw2d/thin','mode-Z.csv'),
        ('cpw','cpw_lumped_uniform.json','cpw/lumped_uniform','port-S.csv'),
        ('rings','rings.json','rings','terminal-M.csv')]
results=[]
def values(path):
    with path.open() as f:
        rows=list(csv.reader(f))
    return [x.strip() for x in rows[0]],[[float(x) for x in row] for row in rows[1:] if row]
def compare(actual,reference,relative=2e-4):
    h,a=values(actual);rh,r=values(reference)
    assert h==rh,(actual,'header mismatch',h,rh)
    assert len(a)==len(r),(actual,'row count mismatch')
    floors=[max(max(abs(row[i]) for row in r)*relative*1e-3,1e-25) for i in range(len(h))]
    worst=0
    for row,ref in zip(a,r):
        assert len(row)==len(ref)
        for label,v,w,absolute in zip(h,row,ref,floors):
            assert math.isfinite(v),(actual,'nonfinite',label)
            difference=abs(v-w)
            if 'deg' in label:
                difference=abs((v-w+180)%360-180);absolute=max(absolute,1e-4)
            if '(dB)' in label:absolute=max(absolute,1e-4)
            tolerance=absolute+relative*abs(w)
            assert difference<=tolerance,(actual,label,v,w,tolerance)
            worst=max(worst,difference/max(abs(w),absolute))
    return worst

for directory,filename,reference,table in checks:
    target=work/directory
    if target.exists():shutil.rmtree(target)
    shutil.copytree(base/'examples'/directory,target)
    text=(target/filename).read_text()
    config=json.loads(re.sub(r'//[^\n]*','',text))
    config['Problem']['Output']=str(target/'results')
    config['Model']['Mesh']=str((target/config['Model']['Mesh']).resolve())
    config['Solver']['Device']='GPU' if backend=='cuda' else 'CPU'
    path=target/'reference.json';path.write_text(json.dumps(config,indent=2))
    with (target/'run.log').open('w') as log:
        subprocess.run(['palace','--dry-run',str(path)],cwd=target,stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['palace','-np','1' if backend=='cuda' else '2','-nt','1',str(path)],
                       cwd=target,stdout=log,stderr=subprocess.STDOUT,check=True)
    verify_solver_log(target/'run.log')
    actual=target/'results'/table
    ref=base/'test/data/regression/ref'/reference/table
    worst=compare(actual,ref)
    item={'case':filename,'table':table,'upstream_max_relative_error':worst}
    if backend=='cuda':
        cpu=Path('/workflow/results/validation/cpu/palace')/directory/'results'/table
        if cpu.exists():item['cpu_cuda_max_relative_error']=compare(actual,cpu)
        else:raise RuntimeError('CPU reference evidence missing; validate CPU first')
    results.append(item)
    (work/'references.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Passed reference',filename,flush=True)

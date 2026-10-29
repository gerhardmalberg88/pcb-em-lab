"""Run inside the CPU solver image without CDI devices."""
import glob
import json
import os
import subprocess
assert not glob.glob('/dev/nvidia*'), 'NVIDIA device unexpectedly visible'
specs=json.loads(subprocess.check_output(['spack','-e','/opt/environment','find','--json'],text=True))
for spec in specs:
    assert spec['name'] not in ('cuda','cudnn','nccl','hip'),spec['name']
    if spec['name']=='palace':assert not spec['parameters'].get('cuda',False)
subprocess.run(['palace','--serial','--version'],check=True,env=dict(os.environ,CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='void'))
print('CPU image: no CUDA package dependency; no NVIDIA device visible.')

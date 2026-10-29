"""Check a generated two-port Touchstone/passive-model handoff in a work copy."""
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import skrf

root=Path(sys.argv[1] if len(sys.argv)>1 else '/work').resolve()
network=skrf.Network(str(root/'network.s2p'))
report=json.loads((root/'report.json').read_text())
if report['fit']['status']!='passive_fit_exported':
    raise RuntimeError(f"No accepted passive fit: {report['fit']}")
reference=float(report['touchstone_reference_ohms'])

def run(command,label):
    result=subprocess.run(command,cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (root/(label+'.log')).write_text(result.stdout)
    if result.returncode or re.search(r'(?m)^ERROR:',result.stdout):
        raise RuntimeError(f'{label} failed: {result.stdout[-2000:]}')

run(['qucsator_rf','-i','qucsatorrf.net','-o','qucsatorrf.dat'],'qucsatorrf-check')
data=(root/'qucsatorrf.dat').read_text()
frequency=np.array([float(x) for x in re.search(r'<indep frequency \d+>(.*?)</indep>',data,re.S)[1].split()])
samples=re.search(r'<dep S\[2,1\] frequency>(.*?)</dep>',data,re.S)[1].split()
actual=np.array([complex(re.sub(r'([+-])j([^j]+)$',r'\1\2j',x)) for x in samples])
expected=network.interpolate(skrf.Frequency.from_f(frequency,unit='Hz')).s[:,1,0]
rf_error=float(np.max(abs(actual-expected)))
if rf_error>1e-3:raise RuntimeError(f'QucsatorRF transfer differs from Touchstone by {rf_error}')

# A matched one-volt Thevenin source gives load voltage S21/2. Offset the
# receiving reference by ten volts to check the differential wrapper's isolation.
(root/'ngspice-check.cir').write_text(f'''Generated passive-model transfer check
.include differential-network.cir
V1 source 0 AC 1
R1 source p1 {reference}
Vreference n2 0 DC 10
X1 p1 0 p2 n2 pcb_em_differential
R2 p2 n2 {reference}
.control
ac lin 41 {network.f[0]} {network.f[-1]}
wrdata ngspice-transfer.dat v(p2,n2)
quit
.endc
.end
''')
run(['ngspice','-b','ngspice-check.cir'],'ngspice-check')
response=np.loadtxt(root/'ngspice-transfer.dat')
expected=network.interpolate(skrf.Frequency.from_f(response[:,0],unit='Hz')).s[:,1,0]/2
spice_error=float(np.max(abs(response[:,1]+1j*response[:,2]-expected)))
if not np.isfinite(response).all() or spice_error>.025:
    raise RuntimeError(f'ngspice fitted transfer error is {spice_error} V')
(root/'handoff-checks.json').write_text(json.dumps({
    'qucsatorrf_max_abs_s21_error':rf_error,
    'ngspice_max_abs_voltage_error_V':spice_error,
    'reference_ohms':reference,'floating_output_reference_V':10,
    'scope':'Circuit handoff within the solved band; physical-model accuracy is separate.'
},indent=2)+'\n')
print('Generated QucsatorRF and floating ngspice handoffs passed')

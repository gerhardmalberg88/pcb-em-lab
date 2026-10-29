"""Exercise file handoffs and compare an OSDI resistor against Ohm's law."""
import json
import re
from pathlib import Path
import subprocess
import numpy as np
import skrf
from pcb_em.postprocess import fit_network

out=Path('/work/circuits');out.mkdir(exist_ok=True)
def run(command,name):
    result=subprocess.run(command,cwd=out,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (out/(name+'.log')).write_text(result.stdout)
    if result.returncode:raise RuntimeError(f'{name} failed; see {out/name}.log: '+result.stdout[-2000:])
    return result.stdout

f=np.geomspace(1e3,1e9,101)
y=1/200+2j*np.pi*f*1e-11
s=np.empty((len(f),2,2),complex)
s[:,0,0]=s[:,1,1]=-50*y/(2+50*y)
s[:,0,1]=s[:,1,0]=2/(2+50*y)
n=skrf.Network(frequency=skrf.Frequency.from_f(f,unit='hz'),s=s,z0=50,name='reference')
n.write_touchstone(filename='reference',dir=str(out))
loaded=skrf.Network(str(out/'reference.s2p'))
assert np.allclose(loaded.s,n.s,rtol=1e-10,atol=1e-12)
fit=fit_network(loaded,out)
assert fit['status']=='passive_fit_exported',fit
(out/'fit.json').write_text(json.dumps(fit,indent=2))
(out/'fit-test.cir').write_text("""Passive fitted network smoke test
.include differential-network.cir
V1 source 0 AC 1
R1 source p1 50
Vreference n2 0 DC 10
X1 p1 0 p2 n2 pcb_em_differential
R2 p2 n2 50
.control
ac dec 10 1k 1G
wrdata fit-response.dat v(p2,n2)
quit
.endc
.end
""")
run(['ngspice','-b','fit-test.cir'],'ngspice-fit')
response=np.loadtxt(out/'fit-response.dat')
assert np.isfinite(response).all() and len(response)>30
expected=1/(2+50*(1/200+2j*np.pi*response[:,0]*1e-11))
assert np.max(abs(response[:,1]+1j*response[:,2]-expected))<.01

(out/'resistor.va').write_text('`include "disciplines.vams"\n'+"""module pcb_em_resistor(p,n);
inout p,n;
electrical p,n;
parameter real resistance=1000 from (0:inf);
analog I(p,n) <+ V(p,n)/resistance;
endmodule
""")
# The pinned 23.5.0 binary crashes in its argument parser when target_cpu is
# supplied. Use its working native default and compile on each execution host;
# generated OSDI files are results, never part of the portable tool images.
run(['openvaf','resistor.va','-o','resistor.osdi'],'openvaf')
assert (out/'resistor.osdi').stat().st_size>0
(out/'osdi-test.cir').write_text("""Compiled Verilog-A resistor validation
V1 p 0 DC 1
N1 p 0 res
.model res pcb_em_resistor resistance=1000
.control
pre_osdi resistor.osdi
op
wrdata osdi-current.dat i(V1)
quit
.endc
.end
""")
run(['ngspice','-b','osdi-test.cir'],'ngspice-osdi')
current=np.loadtxt(out/'osdi-current.dat').ravel()[-1]
assert abs(current+0.001)<1e-9,current

(out/'xspice-test.cir').write_text("""XSPICE gain model validation
V1 input 0 DC 0.25
A1 input output gain_test
.model gain_test gain(gain=2)
.control
op
wrdata xspice-output.dat v(output)
quit
.endc
.end
""")
run(['ngspice','-b','xspice-test.cir'],'ngspice-xspice')
assert abs(np.loadtxt(out/'xspice-output.dat').ravel()[-1]-.5)<1e-9

(out/'rf-test.net').write_text("""# QucsatorRF Touchstone handoff
Pac:P1 p1 gnd Num=1 Z=50 Ohm P=0 dBm f=1 MHz
Pac:P2 p2 gnd Num=2 Z=50 Ohm P=0 dBm f=1 MHz
SPfile:S1 p1 p2 gnd File="reference.s2p" Data="rectangular" Temp=26.85
.SP:SP1 Type="lin" Start=1 MHz Stop=100 MHz Points=11 Noise="no"
""")
run(['qucsator_rf','-i','rf-test.net','-o','rf-test.dat'],'qucsatorrf')
assert (out/'rf-test.dat').stat().st_size>100
rf_data=(out/'rf-test.dat').read_text()
frequency=np.array([float(x) for x in re.search(r'<indep frequency \d+>(.*?)</indep>',rf_data,re.S)[1].split()])
samples=re.search(r'<dep S\[2,1\] frequency>(.*?)</dep>',rf_data,re.S)[1].split()
actual=np.array([complex(re.sub(r'([+-])j([^j]+)$',r'\1\2j',x)) for x in samples])
expected=2/(2+50*(1/200+2j*np.pi*frequency*1e-11))
assert np.max(abs(actual-expected))<.002
(out/'checks.json').write_text(json.dumps({'touchstone':True,'passive_fit':fit,'ngspice':True,
    'openvaf_compilation':True,'openvaf_target':'native; recompile on each host',
    'osdi_current_A':float(current),'xspice':True,'qucsatorrf':True},indent=2)+'\n')
print('Circuit handoff checks passed')

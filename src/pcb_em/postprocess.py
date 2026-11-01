"""Convert Palace's versioned CSV outputs into portable numerical artifacts."""
import csv
import json
import re
import warnings
from pathlib import Path
from .common import WorkflowError, write_json


def table(path):
    with Path(path).open() as stream:
        rows=list(csv.reader(stream))
    if len(rows)<2:raise WorkflowError(f'Empty solver table: {path}')
    header=[x.strip() for x in rows[0]]
    return header,[[float(x.strip()) for x in row] for row in rows[1:] if row]


def assemble_network(solve_dir,port_metadata):
    import numpy as np
    import skrf
    n=len(port_metadata);frequency=None;matrix=None;seen=set()
    for excitation in range(1,n+1):
        header,rows=table(Path(solve_dir)/f'excitation-{excitation}'/'port-S.csv')
        data=np.asarray(rows);freq=data[:,0]*1e9
        if frequency is None:
            frequency=freq;matrix=np.empty((len(freq),n,n),dtype=complex)
        elif not np.allclose(freq,frequency,rtol=1e-12,atol=0):
            raise WorkflowError('Excitation sweeps have different frequency samples')
        for column,label in enumerate(header):
            match=re.fullmatch(r'\|S\[(\d+)\]\[(\d+)\]\| \(dB\)',label)
            if not match:continue
            row,source=map(int,match.groups())
            if source!=excitation or not (1<=row<=n):continue
            phase=f'arg(S[{row}][{source}]) (deg.)'
            if phase not in header:raise WorkflowError(f'Missing phase column {phase}')
            matrix[:,row-1,source-1]=10**(data[:,column]/20)*np.exp(1j*np.deg2rad(data[:,header.index(phase)]))
            seen.add((row,source))
    if len(seen)!=n*n:raise WorkflowError(f'Incomplete S matrix: found {len(seen)} of {n*n} entries')
    if not np.isfinite(matrix).all():raise WorkflowError('S matrix contains non-finite values')
    network=skrf.Network(frequency=skrf.Frequency.from_f(frequency,unit='hz'),s=matrix,
        # A 1-D array is ambiguous when the frequency and port counts match:
        # scikit-rf then interprets it per frequency rather than per port.
        z0=np.tile([p['reference_ohms'] for p in port_metadata],(len(frequency),1)),
        name='pcb-network')
    network.port_names=[p['name'] for p in port_metadata]
    return network


def fit_network(network,out):
    import numpy as np
    import skrf
    for filename in ('network.cir','differential-network.cir'):
        (Path(out)/filename).unlink(missing_ok=True)
    # Never export a fitted transient model without testing/enforcing passivity.
    if len(network.f)<8:
        return {'status':'not_fitted','reason':'At least eight frequency samples are required; add a wider characterized sweep.'}
    # Start with the lowest order: unnecessary poles can turn a passive
    # one-pole RC response into an ill-conditioned, non-passive extrapolation.
    attempts=[];fit=None
    for real,complex_ in ((1,0),(2,1),(2,2),(4,2)):
        candidate=skrf.VectorFitting(network)
        attempt={'real_poles_requested':real,'complex_pairs_requested':complex_}
        try:
            with warnings.catch_warnings(record=True) as notices:
                warnings.simplefilter('always')
                candidate.vector_fit(n_poles_real=real,n_poles_cmplx=complex_,
                                     fit_constant=True,fit_proportional=False)
                if not candidate.is_passive():candidate.passivity_enforce()
                passive=candidate.is_passive()
                error=float(candidate.get_rms_error())
            attempt.update(passive=passive,rms_error=error if np.isfinite(error) else None,
                           warnings=[str(w.message) for w in notices])
            attempts.append(attempt)
            if passive and np.isfinite(error) and error<=.05:
                fit=candidate
                break
        except Exception as error:
            attempt['error']=str(error);attempts.append(attempt)
    if fit is None:
        return {'status':'fit_rejected','reason':'No tested model order passed passivity and RMS-error checks',
                'attempts':attempts}
    try:
        fit.write_spice_subcircuit_s(str(Path(out)/'network.cir'))
        terminals=' '.join(f'p{i} n{i}' for i in range(1,network.nports+1))
        lines=['* Differential ports; no common-mode ground connection is imposed.',
               '.include network.cir',f'.subckt pcb_em_differential {terminals}']
        for i in range(1,network.nports+1):
            lines.extend([f'Emeasure{i} sense{i} 0 p{i} n{i} 1',
                          f'Vmeasure{i} sense{i} internal{i} 0',
                          f'Fport{i} p{i} n{i} Vmeasure{i} 1'])
        lines.extend(['Xnetwork '+' '.join(f'internal{i}' for i in range(1,network.nports+1))+' s_equivalent',
                      '.ends pcb_em_differential'])
        (Path(out)/'differential-network.cir').write_text('\n'.join(lines)+'\n')
        fit.write_npz(str(out))
        return {'status':'passive_fit_exported','rms_error':float(fit.get_rms_error()),'attempts':attempts,
                'scope':'fit over the supplied band; validate transient bandwidth and extrapolation separately'}
    except Exception as error:
        (Path(out)/'network.cir').unlink(missing_ok=True)
        (Path(out)/'differential-network.cir').unlink(missing_ok=True)
        return {'status':'fit_rejected','reason':str(error)}


def series_winding_network(turn_network,geometry):
    import numpy as np
    import skrf
    names=geometry['windings'];ports=geometry['turn_ports']
    weights=np.zeros((len(ports),len(names)))
    metadata=[]
    for port in ports:weights[port['index']-1,names.index(port['winding'])]=port['sign']
    for name in names:
        turns=[p for p in ports if p['winding']==name]
        metadata.append({'name':name,'reference_ohms':turns[0]['reference_ohms'],
                         'signed_turns':[{'index':p['index'],'sign':p['sign']} for p in turns]})
    # I_turn = W I_winding, V_winding = W.T V_turn; ideal series connections.
    impedance=np.einsum('ia,fij,jb->fab',weights,turn_network.z,weights)
    if not np.isfinite(impedance).all():raise WorkflowError('Nonfinite series-winding impedance')
    network=skrf.Network(frequency=turn_network.frequency,z=impedance,
                        z0=[p['reference_ohms'] for p in metadata],name='winding-network')
    network.port_names=names
    return network,metadata


def driven_winding_weights(turn_network,geometry,solve_dir,dest):
    """Find complex drive combinations giving one peak ampere in each winding.

    Palace 0.18.1 port-I reports V/R (the termination branch current). The
    current entering the modeled turn is 2*I_inc - V/R at an excited port and
    -V/R at the other ports, not the port-I column by itself.
    """
    import numpy as np
    names=geometry['windings'];ports=geometry['turn_ports'];n=len(ports)
    connection=np.zeros((n,len(names)))
    for p in ports:connection[p['index']-1,names.index(p['winding'])]=p['sign']
    currents=np.empty((len(turn_network.f),n,n),complex)
    voltages=np.empty_like(currents)
    for j in range(n):
        folder=Path(solve_dir)/f'excitation-{j+1}'
        ih,ir=table(folder/'port-I.csv');vh,vr=table(folder/'port-V.csv')
        ir=np.asarray(ir);vr=np.asarray(vr)
        if not np.allclose(ir[:,0]*1e9,turn_network.f,rtol=1e-12,atol=0) or not np.allclose(vr[:,0],ir[:,0],rtol=1e-12,atol=0):
            raise WorkflowError('Winding current/voltage samples do not match the network')
        for i in range(n):
            currents[:,i,j]=-(ir[:,ih.index(f'Re{{I[{i+1}]}} (A)')]+1j*ir[:,ih.index(f'Im{{I[{i+1}]}} (A)')])
            voltages[:,i,j]=vr[:,vh.index(f'Re{{V[{i+1}]}} (V)')]+1j*vr[:,vh.index(f'Im{{V[{i+1}]}} (V)')]
        currents[:,j,j]+=2*ir[:,ih.index(f'I_inc[{j+1}] (A)')]
    records=[]
    for index,frequency in enumerate(turn_network.f):
        condition=float(np.linalg.cond(currents[index]))
        if not np.isfinite(condition) or condition>1e12:
            raise WorkflowError(f'Ill-conditioned magnetic drive basis at {frequency:g} Hz; unit-current fields cannot be reconstructed')
        weights=np.linalg.solve(currents[index],connection)
        residual=float(np.max(abs(currents[index]@weights-connection)))
        expected=turn_network.z[index]@connection
        actual=voltages[index]@weights
        error=float(np.max(abs(actual-expected)))
        if residual>1e-9 or error>1e-10+1e-6*np.max(abs(expected)):
            raise WorkflowError('Driven winding field weights disagree with terminal network voltages')
        records.append({'frequency_hz':float(frequency),'windings':names,
            'current_A_peak':1,'other_winding_currents_A':0,
            'weights_real':weights.real.tolist(),'weights_imag':weights.imag.tolist(),
            'basis_condition':condition,'current_residual_A':residual,
            'network_voltage_error_V':error})
    write_json(Path(dest)/'driven-winding-weights.json',records)
    return records


def process(out):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out=Path(out);dest=out/'postprocess';dest.mkdir(exist_ok=True)
    geometry=json.loads((out/'mesh/geometry.json').read_text())
    report={'assumptions':geometry.get('assumptions',[]),'status':'exploratory; no engineering acceptance implied'}
    if geometry.get('component'):
        report.update(component=geometry['component'],component_value=geometry.get('component_value'))
    if geometry['dimension']==2:
        header,rows=table(out/'solve/fields/mode-Z.csv')
        report['modes']=[dict(zip(header,row)) for row in rows]
        report['modal_tables']={}
        for path in (out/'solve/fields').glob('mode-*.csv'):
            headings,values=table(path)
            report['modal_tables'][path.name]=[dict(zip(headings,row)) for row in values]
        report['mode_selection']='Inspect the saved fields to identify differential/common modes; mode order alone is not evidence.'
        voltage=out/'solve/fields/mode-V.csv'
        if voltage.exists():
            headings,values=table(voltage);classification=[]
            for row in values:
                data=dict(zip(headings,row))
                vp=complex(data['Re{V[1]} (V)'],data['Im{V[1]} (V)'])
                vn=complex(data['Re{V[2]} (V)'],data['Im{V[2]} (V)'])
                scale=abs(vp)+abs(vn)
                differential=abs(vp-vn)/scale if scale else 0
                common=abs(vp+vn)/scale if scale else 0
                classification.append({'mode':int(row[0]),'differential_voltage_ratio':differential,
                    'common_voltage_ratio':common,'differential_candidate':differential>.95 and common<.3})
            report['mode_classification']=classification
            candidates=[x['mode'] for x in classification if x['differential_candidate']]
            report['differential_candidates']=[m for m in report['modes'] if int(m['m']) in candidates]
            report['classification_scope']='Voltage parity relative to the recorded reference point is a screening test; confirm conductor field patterns and mode continuity under refinement.'
        data=np.asarray(rows)
        fig,ax=plt.subplots();ax.bar(data[:,0],data[:,1]);ax.set(xlabel='Mode index',ylabel=header[1])
        fig.savefig(dest/'modal-impedance.png',dpi=160);plt.close(fig)
    elif geometry.get('analysis')=='magnetostatic':
        header,rows=table(out/'solve/fields/terminal-M.csv')
        inductance=np.asarray(rows)[:,1:]
        names=geometry['windings'];weights=np.zeros((len(geometry['turn_ports']),len(names)))
        expected=(len(geometry['turn_ports']),)*2
        if inductance.shape!=expected or not np.isfinite(inductance).all():
            raise WorkflowError('Invalid or incomplete turn-inductance matrix')
        for port in geometry['turn_ports']:weights[port['index']-1,names.index(port['winding'])]=port['sign']
        combined=weights.T@inductance@weights
        if np.any(np.diag(combined)<=0):
            raise WorkflowError('Nonpositive winding inductance; inspect solver convergence and terminal definitions')
        denominator=np.sqrt(np.outer(np.diag(combined),np.diag(combined)))
        report.update(windings=names,inductance_H=combined.tolist(),coupling=(combined/denominator).tolist(),
            turn_inductance_H=inductance.tolist(),scope=geometry['scope'])
        np.savetxt(dest/'winding-inductance-H.csv',combined,delimiter=',',header=','.join(names))
        fig,ax=plt.subplots();image=ax.imshow(combined*1e6);fig.colorbar(image,ax=ax,label='Inductance (uH)')
        ax.set_xticks(range(len(names)),names,rotation=45);ax.set_yticks(range(len(names)),names)
        fig.tight_layout();fig.savefig(dest/'inductance.png',dpi=160);plt.close(fig)
    else:
        metadata=geometry.get('ports')
        if metadata is None:
            metadata=[{'name':f"{p['winding']}-turn-{p['turn']}",'reference_ohms':p['reference_ohms']} for p in geometry['turn_ports']]
        network=assemble_network(out/'solve',metadata)
        if geometry.get('analysis')=='magnetic-driven':
            network.write_touchstone(filename='turn-network',dir=str(dest),
                                     r_ref=float(metadata[0]['reference_ohms']))
            report['winding_field_normalization']=driven_winding_weights(network,geometry,out/'solve',dest)
            report['turn_ports']=metadata
            network,metadata=series_winding_network(network,geometry)
            report['connection_scope']='Ideal signed series connection of turn ports in impedance coordinates; helical leads and their parasitics are omitted.'
        reference=float(metadata[0]['reference_ohms'])
        network.renormalize(reference)
        report['touchstone_reference_ohms']=reference
        report['reference_convention']='All exported ports renormalized to the first port reference; original solver references remain in ports metadata.'
        network.comments='Port definitions; original solver references are recorded below.\n'+'\n'.join(
            f'Port[{i}]: '+json.dumps(port,sort_keys=True) for i,port in enumerate(metadata,1))
        # Standard Touchstone needs an explicit scalar reference on the option
        # line. write_z0=True emits an HFSS extension with a bare "R" instead;
        # QucsatorRF rejects that file even though scikit-rf can read it back.
        network.write_touchstone(filename='network',dir=str(dest),r_ref=reference)
        rf=['# QucsatorRF handoff: differential wave ports, common real reference impedance.']
        for i in range(1,network.nports+1):
            rf.append(f'Pac:P{i} p{i} gnd Num={i} Z={reference} Ohm P=0 dBm f={network.f[0]} Hz')
        rf.extend(['SPfile:PCB '+' '.join(f'p{i}' for i in range(1,network.nports+1))+
                   f' gnd File="network.s{network.nports}p" Data="rectangular" Temp=26.85',
                   f'.SP:SP1 Type="lin" Start={network.f[0]} Hz Stop={network.f[-1]} Hz Points={len(network.f)} Noise="no"'])
        (dest/'qucsatorrf.net').write_text('\n'.join(rf)+'\n')
        report['ports']=metadata;report['fit']=fit_network(network,dest)
        report['max_singular_value']=float(np.max(np.linalg.svd(network.s,compute_uv=False)))
        report['reciprocity_max_abs_error']=float(np.max(abs(network.s-network.s.transpose(0,2,1))))
        report['passive_at_sampled_frequencies']=report['max_singular_value']<=1+1e-6
        report['passivity_scope']='Sampled S-matrix check; does not establish passivity between samples or outside the solved band.'
        fig,ax=plt.subplots()
        for row in range(network.nports):
            ax.semilogx(network.f,20*np.log10(np.maximum(abs(network.s[:,row,0]),1e-20)),label=f'S{row+1}1')
        ax.set(xlabel='Frequency (Hz)',ylabel='Magnitude (dB)');ax.legend()
        fig.savefig(dest/'s-parameters.png',dpi=160);plt.close(fig)
    write_json(dest/'report.json',report)
    (dest/'README.md').write_text('# Simulation results\n\n'+report['status']+'.\n\n'+
        '\n'.join('- '+x for x in report['assumptions'])+'\n\nSee `report.json`, CSVs and plots. Source and tool hashes are in `../provenance.json`.\n')
    return report


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output');a=p.parse_args();process(a.output)

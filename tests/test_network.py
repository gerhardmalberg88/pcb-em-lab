import json
import numpy as np
import pytest
pytest.importorskip('skrf')
from pcb_em.common import WorkflowError
from pcb_em.postprocess import assemble_network,series_winding_network,driven_winding_weights


def test_complete_excitation_matrix_keeps_order_phase_and_reference(tmp_path):
    for excitation in (1,2):
        folder=tmp_path/f'excitation-{excitation}';folder.mkdir()
        header=['f (GHz)'];values=[.004]
        # Deliberately write output ports in reverse column order.
        for port in (2,1):
            header.extend([f'|S[{port}][{excitation}]| (dB)',f'arg(S[{port}][{excitation}]) (deg.)'])
            values.extend([-20*port,90*excitation])
        (folder/'port-S.csv').write_text(','.join(header)+'\n'+','.join(map(str,values))+'\n')
    metadata=[{'name':'COMH','reference_ohms':100},{'name':'connector','reference_ohms':50}]
    network=assemble_network(tmp_path,metadata)
    assert network.f[0]==pytest.approx(4e6)
    assert network.s[0,0,0]==pytest.approx(.1j)
    assert network.s[0,1,1]==pytest.approx(-.01)
    assert network.port_names==['COMH','connector']
    assert list(network.z0[0])==[100,50]
    (tmp_path/'excitation-2/port-S.csv').write_text('f (GHz)\n0.004\n')
    with pytest.raises(WorkflowError,match='Incomplete S matrix'):
        assemble_network(tmp_path,metadata)


def test_series_winding_preserves_mutual_inductance_and_polarity(tmp_path):
    import skrf
    frequency=1e6
    # Two 1 uH turns with 0.8 uH mutual inductance, each with 0.1 ohm resistance.
    z=np.eye(2)*.1+2j*np.pi*frequency*np.array([[1,.8],[.8,1]])*1e-6
    turns=skrf.Network(f=[frequency],z=z[None,:,:],z0=50)
    geometry={'windings':['coil'],'turn_ports':[
        {'index':i,'winding':'coil','sign':sign,'reference_ohms':100}
        for i,sign in [(1,1),(2,-1)]]}
    network,metadata=series_winding_network(turns,geometry)
    assert network.z[0,0,0]==pytest.approx(.2+2j*np.pi*frequency*.4e-6)
    assert network.port_names==['coil'] and metadata[0]['reference_ohms']==100
    # Palace reports termination branch current V/R; treating that as turn
    # current would produce the wrong field amplitude and phase.
    for source in range(2):
        folder=tmp_path/f'excitation-{source+1}';folder.mkdir()
        voltage=(np.eye(2)+turns.s[0])[:,source]*np.sqrt(50)
        current=voltage/50
        for letter,values,unit in [('I',current,'A'),('V',voltage,'V')]:
            header=['f (GHz)'];row=[frequency/1e9]
            if letter=='I':header.append(f'I_inc[{source+1}] (A)');row.append(1/np.sqrt(50))
            for port,value in enumerate(values,1):
                header.extend([f'Re{{{letter}[{port}]}} ({unit})',f'Im{{{letter}[{port}]}} ({unit})'])
                row.extend([value.real,value.imag])
            (folder/f'port-{letter}.csv').write_text(','.join(header)+'\n'+','.join(map(str,row))+'\n')
    record=driven_winding_weights(turns,geometry,tmp_path,tmp_path)[0]
    weights=np.asarray(record['weights_real'])+1j*np.asarray(record['weights_imag'])
    actual=(np.eye(2)-turns.s[0])/np.sqrt(50)@weights
    assert actual[:,0]==pytest.approx([1,-1])
    assert record['current_residual_A']<1e-12


def test_postprocess_exports_standard_touchstone_reference(tmp_path):
    import skrf
    from pcb_em.postprocess import process
    metadata=[{'name':'input','reference_ohms':100,'positive':'T502:4','negative':'T502:6'},
              {'name':'output','reference_ohms':50,'positive':'J502:2','negative':'J502:1'}]
    (tmp_path/'mesh').mkdir()
    (tmp_path/'mesh/geometry.json').write_text(json.dumps({'dimension':3,'ports':metadata}))
    for excitation in (1,2):
        folder=tmp_path/'solve'/f'excitation-{excitation}';folder.mkdir(parents=True)
        headers=['f (GHz)']
        for port in (1,2):
            headers.extend([f'|S[{port}][{excitation}]| (dB)',f'arg(S[{port}][{excitation}]) (deg.)'])
        rows=[[f,-20,10,-6,-30] for f in (.001,.01)]
        (folder/'port-S.csv').write_text(','.join(headers)+'\n'+
            '\n'.join(','.join(map(str,row)) for row in rows)+'\n')
    expected=assemble_network(tmp_path/'solve',metadata);expected.renormalize(100)
    process(tmp_path)
    path=tmp_path/'postprocess/network.s2p'
    option=next(line for line in path.read_text().splitlines() if line.startswith('#'))
    assert option.split()[-2:]==['R','100.0']
    assert '! Port Impedance' not in path.read_text()
    comments=[line[1:].lstrip() for line in path.read_text().splitlines() if line.startswith('!')]
    definitions=[line for line in comments if line.startswith('Port[') and ': {' in line]
    exported_ports=[json.loads(line.split(': ',1)[1]) for line in definitions]
    assert exported_ports==metadata
    actual=skrf.Network(str(path))
    assert actual.z0==pytest.approx(np.full((2,2),100))
    assert actual.s==pytest.approx(expected.s)

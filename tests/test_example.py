"""Standalone case and optional STEP export contracts, without solver images."""
import json
from pathlib import Path

import pytest

from pcb_em.common import ROOT, WorkflowError
from pcb_em.pipeline import load_case, run_case


@pytest.mark.parametrize('name', ['case.yaml', 'driven.yaml'])
def test_example_has_only_repository_inputs(name):
    path, case, board, project, out = load_case(ROOT/'examples/differential-pair'/name)
    assert board.is_relative_to(ROOT/'examples') and board.is_file()
    assert project == path.parent
    assert out.is_relative_to(ROOT/'results/examples')
    assert case['execution']['backend'] == 'cpu'
    assert case['exports']['step'] is True
    assert '${KIPRJMOD}' not in board.read_text()
    assert '(model ' not in board.read_text()


def test_step_export_participates_in_cache_and_preserves_source(tmp_path):
    board=tmp_path/'board.kicad_pcb';board.write_text('unchanged source')
    path=tmp_path/'case.yaml'
    case={'board':board.name,'mode':'2d','output':'results/example'}
    path.write_text(json.dumps(case))

    class FakeRuntime:
        def __init__(self):self.commands=[]
        def image_exists(self,kind):return True
        def image_id(self,kind):return 'fixed-tools-image'
        def run(self,kind,command,**kwargs):
            self.commands.append(command)
            target=kwargs['output']/'extract'
            if command[0]=='kicad-cli':(target/'board.step').write_text('preview')
            else:(target/'board.json').write_text('{}')

    rt=FakeRuntime()
    out=run_case(path,stage='extract',runtime=rt)
    first=json.loads((out/'extract/stage.json').read_text())['key']
    run_case(path,stage='extract',runtime=rt)
    assert len(rt.commands)==1
    case['exports']={'step':True};path.write_text(json.dumps(case))
    run_case(path,stage='extract',runtime=rt)
    second=json.loads((out/'extract/stage.json').read_text())['key']
    assert first!=second
    assert rt.commands[-1][0]=='kicad-cli'
    assert (out/'extract/board.step').is_file()
    assert json.loads((out/'extract/step-export.json').read_text())['units']=='mm'
    assert board.read_text()=='unchanged source'
    # A preview changed outside the pipeline must invalidate extraction.
    (out/'extract/board.step').write_text('edited preview')
    run_case(path,stage='extract',runtime=rt)
    assert len(rt.commands)==5
    assert (out/'extract/board.step').read_text()=='preview'


@pytest.mark.parametrize('exports', [True, None, {'step':'yes'}])
def test_invalid_export_settings_fail_before_extraction(tmp_path,exports):
    (tmp_path/'board.kicad_pcb').write_text('source')
    case=tmp_path/'case.yaml'
    case.write_text(json.dumps({'board':'board.kicad_pcb','mode':'2d','output':'results/test','exports':exports}))
    with pytest.raises(WorkflowError,match='exports.step'):
        load_case(case)


def test_qucs_profile_initialization_preserves_user_preferences(tmp_path):
    from pcb_em.runtime import initialize_gui_settings
    initialize_gui_settings('freecad',tmp_path)
    assert not (tmp_path/'.config/qucs/qucs_s.conf').exists()
    initialize_gui_settings('qucs-s',tmp_path)
    settings=tmp_path/'.config/qucs/qucs_s.conf'
    assert 'DefaultSimulator=8' in settings.read_text()
    assert 'Qucsator=/opt/qucs-s/usr/bin/qucsator_rf' in settings.read_text()
    custom='[General]\nDefaultSimulator=1\nNgspiceExecutable=/custom/ngspice\n'
    settings.write_text(custom)
    initialize_gui_settings('qucs-s',tmp_path)
    assert settings.read_text()==custom

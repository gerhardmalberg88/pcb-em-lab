"""The public case format needs only the Python standard library."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from pcb_em.common import WorkflowError, read_config


def test_json_case_is_read_without_site_packages(tmp_path):
    path = tmp_path / 'case.json'
    expected = {'schema': 1, 'name': 'PCB \u00b0C', 'execution': {'backend': 'cpu'}}
    path.write_text(json.dumps(expected), encoding='utf-8')
    assert read_config(path) == expected
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    result = subprocess.run([sys.executable, '-S', '-c',
        'import json,sys; from pcb_em.common import read_config; print(json.dumps(read_config(sys.argv[1])))',
        str(path)], env=env, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize('text', ['schema: 1\nname: board\n', '{"name": "board",}', '{"schema":'])
def test_non_json_syntax_is_rejected(tmp_path, text):
    path = tmp_path / 'case.json'
    path.write_text(text)
    with pytest.raises(WorkflowError, match='Invalid JSON'):
        read_config(path)


@pytest.mark.parametrize('value', [[], 'board', 1, None])
def test_case_must_be_an_object(tmp_path, value):
    path = tmp_path / 'case.json'
    path.write_text(json.dumps(value))
    with pytest.raises(WorkflowError, match='mapping'):
        read_config(path)


def test_missing_case_has_a_workflow_error(tmp_path):
    with pytest.raises(WorkflowError, match='Cannot read'):
        read_config(tmp_path / 'missing.json')

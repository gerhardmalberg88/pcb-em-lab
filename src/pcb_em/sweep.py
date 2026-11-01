"""Generate independent, fully recorded cases for numerical and model sensitivity."""
import copy
import csv
import json
from pathlib import Path
from .common import WorkflowError,write_json
from .pipeline import load_case,run_case


def write_metrics(location,records):
    previous={};rows=[]
    for record in records:
        report=record.get('report') or {};metrics={}
        candidates=report.get('differential_candidates',[])
        if len(candidates)==1:
            metrics={key:value for key,value in candidates[0].items() if key!='m'}
        if 'inductance_H' in report:
            metrics.update({f'L[{name}] (H)':report['inductance_H'][i][i]
                            for i,name in enumerate(report['windings'])})
        for metric,value in metrics.items():
            old=previous.get(metric)
            change=abs(value-old)/abs(old) if old else None
            rows.append({'parameter':record['parameter'],'value':record['value'],
                         'metric':metric,'result':value,'relative_change_from_previous':change})
            previous[metric]=value
    write_json(location/'comparison.json',{'metrics':rows,
        'scope':'Successive-value sensitivity, not an acceptance test. For 2D, one voltage-parity candidate must exist; confirm mode continuity from fields.'})
    with (location/'metrics.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['parameter','value','metric','result','relative_change_from_previous'], lineterminator="\n")
        writer.writeheader();writer.writerows(rows)


def sweep(path,parameter,values,backend=None,stage='all'):
    path,case,board,project,out=load_case(path,backend=backend)
    if parameter.startswith(('board','project_root','output','execution')):
        raise WorkflowError('Sweep a physical-model parameter, not a path or execution setting')
    location=out/'sweeps'/parameter.replace('.','-');location.mkdir(parents=True,exist_ok=True)
    records=[]
    for index,value in enumerate(values):
        variant=copy.deepcopy(case);target=variant;keys=parameter.split('.')
        try:
            for key in keys[:-1]:target=target[int(key)] if isinstance(target,list) else target[key]
            key=int(keys[-1]) if isinstance(target,list) else keys[-1]
            if isinstance(target,dict) and key not in target:raise KeyError(key)
            original=target[key];target[key]=value
        except (KeyError,IndexError,TypeError,ValueError) as error:
            raise WorkflowError(f'Unknown sweep parameter: {parameter}') from error
        variant.update(board=str(board),project_root=str(project),output=str(location/f'run-{index}'))
        config=location/f'case-{index}.json';write_json(config,variant)
        results=run_case(config,backend=backend,stage=stage)
        report=results/'postprocess/report.json'
        records.append({'parameter':parameter,'value':value,'original':original,
                        'case':str(config),'results':str(results),
                        'report':json.loads(report.read_text()) if stage in ('all','postprocess') and report.exists() else None})
        write_json(location/'sweep.json',records)
        write_metrics(location,records)
    print(f'Sweep evidence: {location}/sweep.json')

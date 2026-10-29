#!/usr/bin/env python3
"""Install checksum-pinned distributions inside the tools container."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

pins=json.loads(Path(sys.argv[1]).read_text())
cache=Path('/opt/downloads');cache.mkdir(exist_ok=True)

def fetch(name):
    asset=pins['assets'][name];path=cache/asset.get('filename',name)
    shared=Path('/upstream')/name
    if shared.is_file() and hashlib.sha256(shared.read_bytes()).hexdigest()==asset['sha256']:
        shutil.copy2(shared,path)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
        with urllib.request.urlopen(asset['url'],timeout=180) as source,path.open('wb') as output:
            shutil.copyfileobj(source,output)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
        raise RuntimeError(f'Checksum mismatch for {name}')
    return path

def wrapper(name,body):
    p=Path('/usr/local/bin')/name;p.write_text('#!/bin/sh\nset -eu\n'+body+'\n');p.chmod(0o755)

for name,directory,command in [('FreeCAD.AppImage','freecad','freecad'),('Qucs-S.AppImage','qucs-s','qucs-s')]:
    image=fetch(name);image.chmod(0o755)
    target=Path('/opt')/directory
    if not (target/'AppRun').exists():
        target.mkdir(exist_ok=True)
        subprocess.run([str(image),'--appimage-extract'],cwd=target,stdout=subprocess.DEVNULL,check=True)
        for child in (target/'squashfs-root').iterdir():shutil.move(str(child),target/child.name)
        (target/'squashfs-root').rmdir()
    wrapper(command,f'exec /opt/{directory}/AppRun "$@"')

freecad_candidates=list(Path('/opt/freecad').rglob('FreeCADCmd'))+list(Path('/opt/freecad').rglob('freecadcmd'))
if not freecad_candidates:raise RuntimeError('FreeCAD command-line executable missing')
fc=freecad_candidates[0]
wrapper('freecadcmd','exec /opt/freecad/AppRun freecadcmd "$@"')
qucs=list(Path('/opt/qucs-s').rglob('qucsator*'))
qucs=[p for p in qucs if p.is_file() and os.access(p,os.X_OK)]
if not qucs:raise RuntimeError('QucsatorRF executable missing from Qucs-S release')
wrapper('qucsator_rf',f'export LD_LIBRARY_PATH="/opt/qucs-s/usr/lib:${{LD_LIBRARY_PATH:-}}"\nexec "{qucs[0]}" "$@"')

openvaf=Path('/opt/openvaf');openvaf.mkdir(exist_ok=True)
with tarfile.open(fetch('openvaf.tar.gz')) as archive:archive.extractall(openvaf,filter='data')
binary=next(p for p in openvaf.rglob('openvaf') if p.is_file())
wrapper('openvaf',f'exec "{binary}" "$@"')

pv=Path('/opt/paraview');pv.mkdir(exist_ok=True)
if not (pv/'bin/pvpython').exists():
    with tarfile.open(fetch('paraview.tar.gz')) as archive:
        prefix=archive.getmembers()[0].name.split('/')[0]+'/'
        members=[]
        for member in archive.getmembers():
            if member.name.startswith(prefix):
                member.name=member.name[len(prefix):]
                if member.name:members.append(member)
        archive.extractall(pv,members=members,filter='data')
for name in ('paraview','pvpython','pvbatch'):
    wrapper(name,f'exec /opt/paraview/bin/{name} "$@"')

python='/opt/view/bin/python3'
if not Path('/opt/python/bin/python').exists():
    subprocess.run([python,'-m','venv','--system-site-packages','/opt/python'],check=True)
# Spack's Python executable resolves into its own package prefix; a venv does
# not automatically see the other Python packages linked into the shared view.
# Expose that view before pip resolves dependencies so NumPy/SciPy/Shapely stay
# on the locked Spack stack instead of being shadowed by downloaded wheels.
site_packages=subprocess.check_output(['/opt/python/bin/python','-c',
    'import sysconfig; print(sysconfig.get_path("purelib"))'],text=True).strip()
view_sites=list(Path('/opt/view/lib').glob('python*/site-packages'))
if len(view_sites)!=1:raise RuntimeError(f'Expected one numerical Python view: {view_sites}')
(Path(site_packages)/'spack-view.pth').write_text(str(view_sites[0])+'\n')
python_lock=Path('/input/python-requirements.lock')
if not python_lock.exists():python_lock=Path('/export/python-requirements.lock')
pip=['/opt/python/bin/python','-m','pip','install','--only-binary=:all:']
if python_lock.exists():
    subprocess.run(pip+['--require-hashes','-r',str(python_lock)],check=True)
    if python_lock.parent==Path('/input'):shutil.copy2(python_lock,'/export/python-requirements.lock')
else:
    subprocess.run(pip+['--report','/export/python-install.json',str(fetch('scikit_rf.whl')),
                        'pandas==2.3.3','typing-extensions==4.15.0','matplotlib==3.10.7'],check=True)
    report=json.loads(Path('/export/python-install.json').read_text())
    requirements=[]
    for item in report['install']:
        meta=item['metadata'];sha=item['download_info']['archive_info']['hashes']['sha256']
        requirements.append(f"{meta['name']}=={meta['version']} --hash=sha256:{sha}")
    if not requirements:raise RuntimeError('Initial pip resolution did not produce a hash lock')
    Path('/export/python-requirements.lock').write_text('\n'.join(sorted(requirements))+'\n')
subprocess.run(['/opt/python/bin/python','-m','pip','freeze'],stdout=Path('/export/python-freeze.txt').open('w'),check=True)
# A retained store may contain several Gmsh builds. Resolve the module from
# this environment, never from whichever old prefix happens to sort first.
gmsh_prefix=Path(subprocess.check_output(['spack','-e','/opt/environment',
    'location','-i','gmsh'],text=True).strip())
gmsh_modules=list(gmsh_prefix.rglob('gmsh.py'))
if not gmsh_modules:raise RuntimeError('Gmsh Python API missing')
wrapper('pcb-python',f'export PYTHONPATH="{gmsh_modules[0].parent}:/workflow/src:${{PYTHONPATH:-}}"\nexec /opt/python/bin/python "$@"')
subprocess.run(['pcb-python','-c','import gmsh, numpy, scipy, shapely, yaml, skrf'],check=True)
subprocess.run(['pcb-python','-c',
    'from pathlib import Path; import numpy, scipy, shapely; '
    'assert all(Path(m.__file__).resolve().is_relative_to("/opt/install") '
    'for m in (numpy, scipy, shapely)), "Numerical modules must use the Spack store"'],check=True)
# The host's checksum-verified upstream cache survives builds; runtime images
# need only the extracted tools, not another copy of every large archive.
shutil.rmtree(cache)

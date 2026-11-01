"""Reopen the completed standalone example on an authenticated private display.

Run with PYTHONPATH=src .venv/bin/python tests/verify_example_gui.py.
Host requirements: Xvfb, xauth, xwininfo, xwd, xdotool, Pillow, NumPy and scikit-rf.
An xdotool unpacked under .cache/gui-test-root is also supported.
Only this check's display and named containers are stopped.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import uuid

import numpy as np
from PIL import Image

from pcb_em.common import ROOT, CACHE, WorkflowError, digest, write_json
from pcb_em.runtime import Runtime


def main():
    example=ROOT/'results/examples/differential-pair'
    output=ROOT/'results/validation/example-gui';output.mkdir(parents=True,exist_ok=True)
    xdotool=shutil.which('xdotool') or CACHE/'gui-test-root/usr/bin/xdotool'
    if not Path(xdotool).is_file():raise WorkflowError('Install xdotool for this optional GUI check')
    for command in ('Xvfb','xauth','xwd'):
        if not shutil.which(command):raise WorkflowError(f'GUI check requires {command}')
    display=next(i for i in range(190,220) if not Path(f'/tmp/.X11-unix/X{i}').exists())
    auth=output/'xauthority';auth.touch(mode=0o600)
    env=dict(os.environ,DISPLAY=f':{display}',XAUTHORITY=str(auth),
             LD_LIBRARY_PATH=str(CACHE/'gui-test-root/usr/lib/x86_64-linux-gnu'))
    subprocess.run(['xauth','-f',str(auth),'add',env['DISPLAY'],
                    'MIT-MAGIC-COOKIE-1',os.urandom(16).hex()],check=True,env=env)
    os.environ.update(DISPLAY=env['DISPLAY'],XAUTHORITY=env['XAUTHORITY'])
    kicad_work=output/'kicad-source';kicad_work.mkdir(exist_ok=True)
    source=ROOT/'examples/differential-pair/board.kicad_pcb'
    shutil.copy2(source,kicad_work/source.name)
    circuit_work=output/'circuit';circuit_work.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'examples/differential-pair/network.sch',circuit_work/'network.sch')
    shutil.copy2(example/'3d/postprocess/network.s2p',circuit_work/'network.s2p')
    (circuit_work/'network.dat').unlink(missing_ok=True)
    specs=[
        ('pcbnew',kicad_work,['pcbnew','/work/board.kicad_pcb'],'PCB Editor'),
        ('freecad',example/'2d/extract',['freecad','/work/board.step'],'FreeCAD'),
        ('gmsh-2d',example/'2d/mesh',['gmsh','/work/board.msh'],'Gmsh'),
        ('gmsh-3d',example/'3d/mesh',['gmsh','/work/board.msh'],'Gmsh'),
        ('paraview-2d',example/'2d',['paraview','--state=/work/postprocess/view.pvsm'],'ParaView'),
        ('paraview-3d',example/'3d',['paraview','--state=/work/postprocess/view.pvsm'],'ParaView'),
        ('qucs-s',circuit_work,['qucs-s','/work/network.sch'],'Qucs'),
    ]
    originals={str(p):digest(p) for p in [source,kicad_work/source.name,
        example/'2d/extract/board.step',example/'2d/mesh/board.msh',
        example/'3d/mesh/board.msh',example/'2d/postprocess/view.pvsm',
        example/'3d/postprocess/view.pvsm']}
    checks={}

    def xdo(*args):
        return subprocess.check_output([str(xdotool),*args],env=env,text=True,
            timeout=10,stderr=subprocess.DEVNULL).strip()

    def windows(pattern):
        try:return xdo('search','--onlyvisible','--name',pattern).splitlines()
        except subprocess.CalledProcessError:return []

    def snapshot(label):
        path=output/(label+'.xwd')
        subprocess.run(['xwd','-display',env['DISPLAY'],'-root','-silent','-out',str(path)],check=True,env=env)
        data=path.read_bytes();header=struct.unpack('>25I',data[:100])
        if header[7]!=0 or header[11] not in (24,32):raise WorkflowError('Unsupported XWD pixel format')
        im=Image.frombytes('RGB',(header[4],header[5]),data[header[0]+header[19]*12:],
            'raw','BGR' if header[11]==24 else 'BGRX',header[12])
        im.save(output/(label+'.png'))
        return im

    with (output/'xvfb.log').open('w') as log:
        xvfb=subprocess.Popen(['Xvfb',env['DISPLAY'],'-screen','0','1280x900x24',
            '-nolisten','tcp','-extension','MIT-SHM','-auth',str(auth)],env=env,stdout=log,stderr=log)
        try:
            time.sleep(1)
            for label,work,command,pattern in specs:
                name='pcb-em-example-gui-'+uuid.uuid4().hex[:12]
                runtime=Runtime();base=runtime.base
                runtime.base=lambda *args,**kw:base(*args,**kw)+['--name',name]
                with ThreadPoolExecutor(max_workers=1) as pool:
                    task=pool.submit(runtime.run,'tools',command,output=work,gui=True,log=output/(label+'.log'))
                    try:
                        win=None
                        for _ in range(90):
                            if task.done():task.result();raise WorkflowError(label+' closed before inspection')
                            for dialog in windows('KiCad Setup'):
                                xdo('windowraise',dialog);xdo('windowfocus',dialog)
                                xdo('key','Escape');time.sleep(1);xdo('key','Return')
                            for dialog in windows('Configure Global Footprint Library Table'):
                                xdo('windowfocus',dialog);xdo('key','Return')
                            found=windows(pattern)
                            if found:win=found[0];break
                            time.sleep(1)
                        if not win:raise WorkflowError(label+' did not create a visible window')
                        time.sleep(4)
                        if label=='pcbnew':
                            for _ in range(20):
                                for dialog in windows('KiCad Setup'):
                                    xdo('windowraise',dialog);xdo('windowfocus',dialog)
                                    xdo('key','Escape');time.sleep(1);xdo('key','Return')
                                for dialog in windows('Configure Global Footprint Library Table'):
                                    xdo('windowfocus',dialog);xdo('key','Return')
                                found=windows('board.*PCB Editor')
                                if found:win=found[0];break
                                time.sleep(1)
                        for dialog in windows('Welcome'):
                            xdo('windowfocus',dialog);xdo('key','Escape')
                        xdo('windowsize',win,'1200','850');xdo('windowfocus',win)
                        xdo('windowmove',win,'0','0')
                        if label=='pcbnew':xdo('key','Home')
                        if label=='freecad':
                            xdo('key','alt+w');time.sleep(.4);xdo('key','1');time.sleep(.4)
                            xdo('key','0','v','f')
                        if label=='qucs-s':
                            xdo('key','F2')
                            for _ in range(30):
                                if (circuit_work/'network.dat').is_file():break
                                if task.done():task.result();raise WorkflowError('Qucs-S closed during simulation')
                                time.sleep(1)
                            if not (circuit_work/'network.dat').is_file():
                                raise WorkflowError('Qucs-S F2 did not produce the example network dataset')
                            for dialog in windows('Qucs Simulation Messages'):
                                xdo('windowfocus',dialog);xdo('key','Return')
                            xdo('windowfocus',win)
                        time.sleep(6)
                        im=snapshot(label);title=xdo('getwindowname',win)
                        if label=='pcbnew' and 'board' not in title:
                            raise WorkflowError('KiCad did not reopen the copied board')
                        if not all(digest(p)==h for p,h in originals.items()):
                            raise WorkflowError('GUI modified an input artifact')
                        pixels=np.asarray(im)[200:800,350:1150].astype(int)
                        checks[label]={'pass':True,'visible_window':title,
                            'authenticated_display':True,'inputs_preserved':True,'image':label+'.png',
                            'colored_viewport_fraction':float((pixels.max(2)-pixels.min(2)>40).mean())}
                        if label=='qucs-s':
                            # This version's title contains only its application
                            # name; the actual dataset verifies the opened case.
                            checks[label]['schematic']='circuit/network.sch'
                            checks[label]['simulation_dataset']='circuit/network.dat'
                            import skrf
                            data=(circuit_work/'network.dat').read_text()
                            frequency=re.search(r'<indep frequency \d+>(.*?)</indep>',data,re.S)
                            transfer=re.search(r'<dep S\[2,1\] frequency>(.*?)</dep>',data,re.S)
                            if not frequency or not transfer:raise WorkflowError('Incomplete Qucs-S dataset')
                            actual=np.array([complex(re.sub(r'([+-])j([^j]+)$',r'\1\2j',x))
                                             for x in transfer[1].split()])
                            network=skrf.Network(str(circuit_work/'network.s2p'))
                            if not np.allclose([float(x) for x in frequency[1].split()],network.f):
                                raise WorkflowError('Qucs-S used different frequency samples')
                            error=float(np.max(abs(actual-network.s[:,1,0])))
                            if not np.isfinite(error) or error>1e-6:
                                raise WorkflowError('Qucs-S transfer differs from the native Touchstone')
                            checks[label]['maximum_s21_error']=error
                        write_json(output/'checks.json',checks)
                        print(label+': reopened; input hashes unchanged',flush=True)
                    except BaseException as error:
                        checks[label]={'pass':False,'error':str(error)}
                        try:
                            snapshot(label+'-failed')
                            checks[label]['image']=label+'-failed.png'
                        except (OSError,subprocess.SubprocessError,WorkflowError):
                            pass
                        write_json(output/'checks.json',checks);raise
                    finally:
                        subprocess.run([runtime.engine,'stop','-t','2',name],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        try:task.result(timeout=20)
                        except WorkflowError:pass  # Intentional stop of this test's container.
        finally:
            xvfb.terminate();xvfb.wait(timeout=10)


if __name__=='__main__':main()

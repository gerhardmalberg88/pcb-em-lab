"""Run under Xvfb and require a mapped window from every GUI launcher."""
import os
from pathlib import Path
import re
import signal
import subprocess
import time
Path(os.environ['HOME']).mkdir(parents=True,exist_ok=True)
for tool in ('kicad','pcbnew','freecad','gmsh','paraview','qucs-s'):
    log=Path('/work')/(tool+'-gui.log')
    with log.open('w') as stream:
        process=subprocess.Popen([tool],stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        found=False;visible_since=None
        try:
            for attempt in range(60):
                if process.poll() is not None:break
                found=False
                windows=subprocess.check_output(['xwininfo','-root','-tree'],text=True)
                for line in windows.splitlines():
                    if not re.search(r'\d{2,}x\d{2,}',line):continue
                    match=re.match(r'\s*(0x[0-9a-fA-F]+)',line)
                    if match:
                        detail=subprocess.run(['xwininfo','-id',match[1]],capture_output=True,text=True)
                        if 'IsViewable' in detail.stdout:found=True;break
                if found:
                    if visible_since is None:visible_since=time.monotonic()
                    if time.monotonic()-visible_since>=3:break
                else:visible_since=None
                time.sleep(.5)
            if not found or process.poll() is not None or visible_since is None or time.monotonic()-visible_since<3:
                raise RuntimeError(f'{tool} did not retain a mapped window; see {log}')
            print('GUI window verified:',tool,flush=True)
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait()

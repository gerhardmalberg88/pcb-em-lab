"""Rootless container execution and explicit CPU/CUDA selection."""
import json
import os
import shutil
from pathlib import Path
from .common import ROOT, CACHE, WorkflowError, call

IMAGES = {kind: f"localhost/pcb-em-{kind}:0.1" for kind in ("tools", "cpu", "cuda")}


def initialize_gui_settings(tool, home):
    """Seed a fresh lab profile; never replace an existing user's preferences."""
    if tool != 'qucs-s':return
    target=Path(home)/'.config/qucs/qucs_s.conf'
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        with target.open('x') as stream:
            # Qucs-S 26.1.1: simQucsator=8. Explicitly select the image's
            # bundled RF binary (and adjacent converter) to avoid discovery.
            stream.write('[General]\nDefaultSimulator=8\nfirstRun=false\n'
                         'Qucsator=/opt/qucs-s/usr/bin/qucsator_rf\nNgspiceExecutable=ngspice\n')
    except FileExistsError:
        pass


class Runtime:
    def __init__(self, engine=None):
        self.engine = engine or os.environ.get("PCB_EM_ENGINE", "podman")
        if self.engine not in ("podman", "docker"):
            raise WorkflowError("PCB_EM_ENGINE must be podman or docker")

    def image_exists(self, kind):
        result = call([self.engine, "image", "inspect", IMAGES[kind]], capture=True, check=False)
        return result.returncode == 0

    def image_id(self, kind):
        result = call([self.engine, "image", "inspect", IMAGES[kind]], capture=True)
        return json.loads(result.stdout)[0]["Id"]

    def gpu_check(self, count=1):
        if not self.image_exists("cuda"):
            return False, "CUDA image is not built"
        args = self.base("cuda", gpu_count=count)
        result = call(args + [IMAGES["cuda"], "/usr/local/bin/pcb-em-cuda-check"],
                      capture=True, check=False)
        return result.returncode == 0, (result.stdout if result.returncode == 0 else result.stderr).strip()

    def select(self, requested, count=1):
        if requested == "cpu":
            # Deliberately do not call gpu_check, nvidia-smi or inspect CUDA here.
            if not self.image_exists("cpu"):
                raise WorkflowError("CPU image missing; run pcb-em build --profile cpu")
            return "cpu", "CPU explicitly selected"
        if requested not in ("auto", "cuda"):
            raise WorkflowError(f"Unknown execution backend: {requested}")
        available, reason = self.gpu_check(count)
        if available:
            return "cuda", "CUDA device preflight passed"
        if requested == "cuda":
            raise WorkflowError(f"CUDA requested but unavailable: {reason}")
        if not self.image_exists("cpu"):
            raise WorkflowError(f"CUDA unavailable ({reason}); CPU image is also missing")
        return "cpu", f"Using CPU: {reason}"

    def base(self, kind, gpu_count=0):
        # Xvfb's readiness handshake cannot target a shell running as PID 1.
        # An init process also reaps children left by GUI and MPI launchers.
        args = [self.engine, "run", "--rm", "--init", "--network=none", "--ipc=private"]
        if self.engine == "podman":
            # Image USER metadata can otherwise override keep-id's default and
            # leave generated files owned by a subordinate host UID.
            args += ["--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}"]
        else:
            args += ["--user", f"{os.getuid()}:{os.getgid()}"]
        args += ["--env", "HOME=/tmp/pcb-em-home", "--entrypoint", "",
                 "--env", "MPLCONFIGDIR=/tmp/pcb-em-matplotlib",
                 "--env", "PYTHONPATH=/workflow/src", "--volume", f"{ROOT}:/workflow:ro"]
        if gpu_count:
            if self.engine == "podman":
                for index in range(gpu_count):
                    args += ["--device", f"nvidia.com/gpu={index}"]
            else:
                args += ["--gpus", str(gpu_count)]
        return args

    def run(self, kind, command, *, project=None, output=None, gpu_count=0,
            env=None, log=None, capture=False, check=True, gui=False):
        args = self.base(kind, gpu_count)
        if project:
            args += ["--volume", f"{Path(project).resolve()}:/project:ro"]
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            args += ["--volume", f"{Path(output).resolve()}:/work:rw", "--workdir", "/work"]
        for key, value in (env or {}).items():
            args += ["--env", f"{key}={value}"]
        if gui:
            gui_home=CACHE/'gui'/Path(command[0]).name/'home'
            gui_home.mkdir(parents=True,exist_ok=True)
            initialize_gui_settings(Path(command[0]).name,gui_home)
            display = os.environ.get("DISPLAY")
            auth = os.environ.get("XAUTHORITY", str(Path.home() / ".Xauthority"))
            if not display or not Path(auth).is_file():
                raise WorkflowError("GUI requires DISPLAY and a readable XAUTHORITY cookie file")
            # FamilyLocal Xauthority cookies are keyed by hostname. Preserve
            # that identity inside the container; retain normal cookie checks.
            args += ["--hostname", os.uname().nodename,
                     "--env", f"DISPLAY={display}", "--env", "XAUTHORITY=/tmp/xauthority",
                     "--env","LIBGL_ALWAYS_SOFTWARE=1","--env","QT_X11_NO_MITSHM=1",
                     "--env","HOME=/gui-home","--volume",f"{gui_home}:/gui-home:rw",
                     "--volume", "/tmp/.X11-unix:/tmp/.X11-unix:ro",
                     "--volume", f"{auth}:/tmp/xauthority:ro"]
        return call(args + [IMAGES[kind]] + list(command), log=log, capture=capture, check=check)

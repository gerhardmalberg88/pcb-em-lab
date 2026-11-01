"""Pinned images built in persistent containers so failures are resumable."""
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path
from .common import ROOT, CACHE, WorkflowError, call, digest, fingerprint, write_json
from .runtime import Runtime, IMAGES

BASE_ASSETS=('spack.tar.gz','spack-packages.tar.gz','palace.tar.gz','cacert.pem')


def input_key(base_hash, data, inputs):
    # Dependency locks are build inputs too: changing one must invalidate an
    # image even when its top-level package requests remain unchanged.
    return fingerprint({"base":base_hash,"environment":data,"scripts":{
        p.name:digest(p) for p in inputs.iterdir() if p.is_file()}})[:12]


def fetch(name, asset):
    target = CACHE / "upstream" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and digest(target) == asset["sha256"]:
        return target
    temporary = target.with_suffix(target.suffix + ".download")
    with urllib.request.urlopen(asset["url"], timeout=120) as source, temporary.open("wb") as dest:
        shutil.copyfileobj(source, dest)
    if digest(temporary) != asset["sha256"]:
        temporary.unlink()
        raise WorkflowError(f"Checksum mismatch: {name}")
    temporary.replace(target)
    return target


def environment(profile, arch="75", cuda_version="12.9.1"):
    common = {
        "concretizer": {"unify": True, "reuse": False,
                        "targets": {"granularity": "generic", "host_compatible": False}},
        "view": "/opt/view",
        "config": {"build_jobs": 2, "install_tree": {"root": "/opt/install"}},
        "packages": {"all": {"target": ["x86_64"], "providers": {
            "mpi": ["openmpi"], "blas": ["openblas"], "lapack": ["openblas"]}},
            "openblas": {"require": "threads=none"},
            "openmpi": {"require": "fabrics=none schedulers=none"}},
    }
    if profile == "tools":
        # Gmsh's GUI needs software OpenGL, not an additional LLVM compiler
        # build. ParaView uses the pinned distribution's Mesa runtime.
        common['packages']['mesa']={'require':'~llvm'}
        # Gmsh 4.15.2 reads FLTK's screen dimensions before opening its first
        # window. The 1.4.4 build returned -1 here (a 1x1 GUI in Xvfb).
        common['packages']['fltk']={'require':'@1.3.7'}
        common["specs"] = [
            "gmsh@4.15.2+opencascade+fltk+shared~mpi~petsc~slepc~med~cgns~mmg",
            "ngspice@46 build=bin +xspice+osdi~X~openmp",
            "python@3.11", "py-pip", "py-numpy", "py-scipy", "py-shapely", "py-pyyaml",
        ]
    else:
        spec = "palace@0.18.1+superlu-dist+slepc+openmp~strumpack~mumps~rocm"
        if profile == "cuda":
            if not re.fullmatch(r"\d+(,\d+)*", arch):
                raise WorkflowError("CUDA architecture must contain integer values, e.g. 75 or 80,89")
            if not re.fullmatch(r"\d+\.\d+(\.\d+)?", cuda_version):
                raise WorkflowError("CUDA version must be numeric, e.g. 12.9.1")
            spec += f" +cuda cuda_arch={arch} ^cuda@{cuda_version} ^openmpi"
        else:
            spec += " ~cuda"
        common["specs"] = [spec]
    return {"spack": common}


def prepare_base(runtime,pins):
    if "@sha256:" not in pins["base_image"]:
        raise WorkflowError("env/pins.json must pin the base image by digest before building")
    context = CACHE / "base-context"
    (context / "assets").mkdir(parents=True, exist_ok=True)
    for name in BASE_ASSETS:
        source = fetch(name, pins["assets"][name])
        target = context / "assets" / name
        if not target.exists() or digest(target)!=pins['assets'][name]['sha256']:
            target.unlink(missing_ok=True)
            os.link(source, target)
    for name in ("Containerfile.base", "install-solver.sh", "install-tools.sh"):
        shutil.copy2(ROOT / "containers" / name, context / name)
    base_pins={"base_image":pins['base_image'],"ubuntu_snapshot":pins['ubuntu_snapshot'],"assets":{
        name:pins['assets'][name] for name in BASE_ASSETS}}
    base_hash = fingerprint({"pins": base_pins, "files": {p.name: digest(p) for p in context.iterdir() if p.is_file()}})[:12]
    base_image = f"localhost/pcb-em-builder:{base_hash}"
    flags=['--layers','--format','docker'] if runtime.engine=='podman' else []
    call([runtime.engine, "build", *flags, "--build-arg",
          f"BASE_IMAGE={pins['base_image']}", "--build-arg",f"APT_SNAPSHOT={pins['ubuntu_snapshot']}","-t", base_image, "-f", str(context / "Containerfile.base"),
          str(context)], log=CACHE / "logs/build-base.log")
    return base_hash,base_image


def build(profile, arch="75", cuda_version="12.9.1", jobs=2):
    runtime=Runtime()
    (CACHE/'spack-source').mkdir(parents=True,exist_ok=True)
    pins=json.loads((ROOT/'env/pins.json').read_text())
    base_hash,base_image=prepare_base(runtime,pins)
    profiles = ["cpu", "tools", "cuda"] if profile == "all" else (["cpu", "tools"] if profile == "cpu" else [profile])
    for kind in profiles:
        data = environment(kind, arch, cuda_version)
        data["spack"]["config"]["build_jobs"] = jobs
        lock_name = f"cuda-{arch.replace(',', '-')}-{cuda_version}" if kind == "cuda" else kind
        exported = ROOT / "env/locks" / lock_name
        exported.mkdir(parents=True, exist_ok=True)
        inputs = CACHE / "build-input" / lock_name
        inputs.mkdir(parents=True, exist_ok=True)
        write_json(inputs / "spack.json", data)
        (inputs / "spack.yaml").unlink(missing_ok=True)
        write_json(ROOT / "env" / f"{kind}.json", data)
        # Never apply an old lock to a changed environment.
        old_manifest = exported / "spack.json"
        from .common import read_config
        if old_manifest.exists() and read_config(old_manifest) == data and (exported / "spack.lock").exists():
            shutil.copy2(exported / "spack.lock", inputs / "spack.lock")
        else:
            (inputs / "spack.lock").unlink(missing_ok=True)
        for name in ("pins.json",):
            shutil.copy2(ROOT / "env" / name, inputs / name)
        installer='install-tools.sh' if kind=='tools' else 'install-solver.sh'
        shutil.copy2(ROOT/'containers'/installer,inputs/installer)
        if kind=='cuda':
            shutil.copy2(ROOT/'scripts/check-cuda.cu',inputs/'check-cuda.cu')
            shutil.copy2(ROOT/'scripts/check-cuda-memory.c',inputs/'check-cuda-memory.c')
            shutil.copy2(ROOT/'containers/cuda-runtime.c',inputs/'cuda-runtime.c')
            # Avoid competing large memory pools on the 6 GiB workstation GPU.
            # The HYPRE adapter uses its public API and makes allocation failures
            # fatal before libCEED's success assumption can hide them.
            write_json(inputs/'runtime-env.json',{'MFEM_MEMORY':'cuda',
                'LD_PRELOAD':'/usr/local/lib/pcb-em-cuda-runtime.so'})
        if kind == "tools":
            shutil.copy2(ROOT / "scripts/install-assets.py", inputs / "install-assets.py")
            if (exported/'python-requirements.lock').exists():
                shutil.copy2(exported/'python-requirements.lock',inputs/'python-requirements.lock')
        key = input_key(base_hash,data,inputs)
        previous=exported/'image.json'
        if previous.exists() and runtime.image_exists(kind):
            record=json.loads(previous.read_text())
            if record.get('inputs')==key and record.get('id')==runtime.image_id(kind):
                print(f'{kind}: cached image {record["id"][:20]}',flush=True)
                continue
        # Reuse the immutable Spack store, preserving the current pinned OS base.
        # Never seed the CPU profile from a CUDA image.
        seed=kind if runtime.image_exists(kind) else ('cpu' if runtime.image_exists('cpu') else None)
        source_image=base_image
        if seed:
            seed_id=runtime.image_id(seed)
            source_image='localhost/pcb-em-cache:'+fingerprint([base_hash,seed_id])[:12]
            flags=['--layers','--format','docker'] if runtime.engine=='podman' else []
            call([runtime.engine,'build',*flags,'--build-arg',f'BASE_IMAGE={base_image}',
                  '--build-arg',f'CACHE_IMAGE={seed_id}','-t',source_image,'-f',str(ROOT/'containers/Containerfile.cache'),
                  str(ROOT/'containers')],log=CACHE/'logs/build-cache.log')
        name = f"pcb-em-build-{kind}-{key}"
        exists = call([runtime.engine, "container", "inspect", name], capture=True, check=False).returncode == 0
        log = CACHE / "logs" / f"build-{kind}.log"
        if exists:
            state=json.loads(call([runtime.engine,'container','inspect',name],capture=True).stdout)[0]['State']
            if state['Running']:call([runtime.engine,'attach',name],log=log)
            elif state['ExitCode']!=0:call([runtime.engine,'start','--attach',name],log=log)
        else:
            script = "/input/"+installer
            call([runtime.engine, "run", "--name", name, "--env", f"BUILD_JOBS={jobs}","--env",f"CUDA_ARCH={arch}",
                  "--volume", f"{inputs}:/input:ro", "--volume", f"{exported}:/export:rw",
                  "--volume", f"{CACHE / 'upstream'}:/upstream:ro",
                  "--volume", f"{CACHE / 'spack-source'}:/opt/spack/var/spack/cache:rw",
                  "--entrypoint", "/bin/bash",source_image, script], log=log)
        status = json.loads(call([runtime.engine, "container", "inspect", name], capture=True).stdout)[0]["State"]
        if status['Running'] or status["ExitCode"] != 0:
            raise WorkflowError(f"{kind} build failed; retained {name} for resuming")
        runtime_env=read_config(inputs/'runtime-env.json') if kind=='cuda' else {}
        changes=[]
        for variable,value in runtime_env.items():
            changes += ['--change',f'ENV {variable}={value}']
        call([runtime.engine, "commit", "--change", 'ENTRYPOINT []', *changes, name, IMAGES[kind]], log=log)
        # On the first build the installer creates dependency locks. Record
        # those exact resolved inputs so the next identical build is a hit.
        for filename in ('spack.lock','python-requirements.lock'):
            if (exported/filename).exists():shutil.copy2(exported/filename,inputs/filename)
        key=input_key(base_hash,data,inputs)
        write_json(exported / "image.json", {"image": IMAGES[kind], "id": runtime.image_id(kind),
                   "inputs": key, "base": pins["base_image"],
                   "runtime_environment":runtime_env})
        # The committed image retains the complete Spack store. Release the
        # duplicate writable layer only after image creation and provenance
        # export succeed; failed builds remain available for resuming.
        call([runtime.engine, 'rm', name], log=log)
        print(f"Built {IMAGES[kind]}; lock and package inventory: {exported}", flush=True)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--profile", choices=["cpu", "cuda", "tools", "all"], default="cpu")
    p.add_argument("--cuda-arch", default="75")
    p.add_argument("--cuda-version", default="12.9.1")
    p.add_argument("--jobs", type=int, default=2)
    a = p.parse_args()
    build(a.profile, a.cuda_arch, a.cuda_version, a.jobs)

"""Public command-line interface; simulation programs stay inside containers."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from .common import ROOT, WorkflowError, call, positive
from .runtime import Runtime, IMAGES


def parser():
    p=argparse.ArgumentParser(prog='pcb-em',description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('bootstrap',help='Install/check the host container runtime')
    b.add_argument('--cuda',action='store_true',help='Also install NVIDIA container integration')
    b=sub.add_parser('build',help='Build pinned, resumable container images')
    b.add_argument('--profile',choices=['cpu','cuda','all','tools'],default='cpu')
    b.add_argument('--cuda-arch',default='75')
    b.add_argument('--cuda-version',default='12.9.1')
    b.add_argument('--jobs',type=positive,default=2)
    d=sub.add_parser('doctor',help='Verify installed tools and container access')
    d.add_argument('--backend',choices=['cpu','cuda','auto'],default='cpu')
    d.add_argument('--full',action='store_true',help='Run numerical and circuit reference tests')
    r=sub.add_parser('run',help='Run stages; successful prerequisites are reused')
    r.add_argument('case',type=Path)
    r.add_argument('--mode',choices=['2d','3d'])
    r.add_argument('--backend',choices=['cpu','cuda','auto'])
    r.add_argument('--mpi-ranks',type=positive)
    r.add_argument('--threads-per-rank',type=positive)
    r.add_argument('--gpu-count',type=positive)
    r.add_argument('--stage',choices=['extract','mesh','solve','postprocess','all'],default='all')
    r.add_argument('--force',action='store_true')
    s=sub.add_parser('sweep',help='Mesh/domain convergence or physical-parameter sensitivity')
    s.add_argument('case',type=Path)
    s.add_argument('--parameter',required=True,help='Dotted key, e.g. mesh.fine_mm or magnetics.cores.0.mu_r')
    s.add_argument('--values',type=float,nargs='+',required=True)
    s.add_argument('--backend',choices=['cpu','cuda','auto'])
    s.add_argument('--stage',choices=['mesh','solve','postprocess','all'],default='all')
    g=sub.add_parser('gui',help='Launch a GUI with a writable work directory')
    g.add_argument('tool',choices=['kicad','pcbnew','freecad','gmsh','paraview','qucs-s'])
    g.add_argument('--workdir',type=Path,default=ROOT/'results/gui')
    g.add_argument('args',nargs='*',help='Container paths, e.g. /work/design.kicad_pcb')
    e=sub.add_parser('export',help='Save images for an offline x86-64 Linux server')
    e.add_argument('directory',type=Path)
    e.add_argument('--profile',choices=['cpu','cuda','all'],default='cpu')
    i=sub.add_parser('import',help='Load image archives and verify their hashes')
    i.add_argument('directory',type=Path)
    return p


def bootstrap(cuda=False):
    if not shutil.which('podman'):
        if not shutil.which('apt-get'):
            raise WorkflowError('Install rootless Podman using your Linux distribution package manager')
        call(['sudo','apt-get','update'])
        call(['sudo','apt-get','install','-y','podman','uidmap','slirp4netns','fuse-overlayfs'])
    call(['podman','info','--format','{{.Host.Security.Rootless}}'])
    if cuda:call(['sudo','bash',ROOT/'scripts/bootstrap-nvidia.sh'])
    print('Host runtime ready. Next: pcb-em build --profile cpu')


def transfer(directory,profile=None):
    from .common import digest,write_json
    rt=Runtime();directory=directory.resolve();directory.mkdir(parents=True,exist_ok=True)
    if profile:
        kinds=['tools']+(['cpu','cuda'] if profile=='all' else [profile])
        manifest={}
        for kind in kinds:
            name=f'pcb-em-{kind}.tar';target=directory/name
            flags=['--format','docker-archive'] if rt.engine=='podman' else []
            call([rt.engine,'save',*flags,'-o',target,IMAGES[kind]])
            manifest[name]={'sha256':digest(target),'image':IMAGES[kind],'id':rt.image_id(kind)}
        write_json(directory/'images.json',manifest)
    else:
        manifest=json.loads((directory/'images.json').read_text())
        for name,info in manifest.items():
            target=directory/name
            if Path(name).name!=name or digest(target)!=info['sha256']:
                raise WorkflowError(f'Archive hash or name invalid: {name}')
        for name in manifest:call([rt.engine,'load','-i',directory/name])


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    extra=[]
    if argv and argv[0]=='gui' and '--' in argv:
        split=argv.index('--');extra=argv[split+1:];argv=argv[:split]
    a=parser().parse_args(argv)
    if a.command=='gui':a.args.extend(extra)
    try:
        if a.command=='bootstrap':bootstrap(a.cuda)
        elif a.command=='build':
            from .build import build
            build(a.profile,a.cuda_arch,a.cuda_version,a.jobs)
        elif a.command=='run':
            from .pipeline import run_case
            run_case(a.case,mode=a.mode,backend=a.backend,ranks=a.mpi_ranks,
                     threads=a.threads_per_rank,gpus=a.gpu_count,stage=a.stage,force=a.force)
        elif a.command=='doctor':
            from .validation import doctor
            return doctor(a.backend,a.full)
        elif a.command=='sweep':
            from .sweep import sweep
            sweep(a.case,a.parameter,a.values,a.backend,a.stage)
        elif a.command=='gui':
            Runtime().run('tools',[a.tool]+a.args,output=a.workdir,gui=True)
        elif a.command=='export':transfer(a.directory,a.profile)
        elif a.command=='import':transfer(a.directory)
    except (WorkflowError,OSError,ValueError,KeyError) as error:
        print(f'pcb-em: {error}',file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Build containers and successful stage caches are retained.',file=sys.stderr)
        return 130
    return 0


if __name__=='__main__':sys.exit(main())

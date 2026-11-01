# Moving the workflow to a server

The repository and Python distribution are named `pcb-em-lab`; the command
remains `pcb-em`. The supplied differential-pair example needs only this
repository. For your own board, copy its case and design assets and pass the
case's explicit path; a sibling checkout layout is not required.

Use a single-node x86-64 Linux host with rootless Podman. CPU operation needs no
NVIDIA runtime. For CUDA, check the host driver/device first, then install NVIDIA
Container Toolkit and CDI. Choose the server's actual compute architecture at
build time; the laptop default is 75 with CUDA 12.9.1.

```bash
./pcb-em export /path/to/image-bundle --profile all
# Copy this repository and the image bundle to the server.
./pcb-em bootstrap
./pcb-em import /path/to/image-bundle
./pcb-em doctor --backend cpu --full
./pcb-em run examples/differential-pair/case.yaml --backend cpu --mpi-ranks 2
```

The image bundle contains Docker-format archives and a SHA-256 manifest checked
before import. Keep `env/locks` and `env/pins.json` with it for provenance. Running
an existing image requires no network; container runs use `--network=none`.
The CPU image archive was exported and imported on this laptop with its image
ID unchanged. A second physical server has not been tested. The current tools
image is about 16 GB, the CPU image about 2 GB and the CUDA image about 13 GB;
these sizes include shared layers and should not simply be added. Rootless
Podman's `--userns=keep-id` can also create copies with remapped ownership when an
image is first run. Allow space for these copies, export archives and loading new
images alongside existing ones. Initial source builds
take hours on this laptop and retain substantial compilation and download caches.
Image creation also needs temporary disk space: the CUDA commit exhausted 22 GB
of free space before any runtime tests. Keep ample free space beyond the final
image size, and write export bundles to a disk with room for all requested images.
Successful builds now remove their builder container after the image commit and
provenance export succeed. Failed builders remain resumable. For older builders,
check that their package prefixes are preserved in the retained image before
removing them. Keep source caches and build logs for reuse and diagnosis. Avoid
blanket `podman system prune`: named compilation caches can still be useful.

To inspect storage without deleting anything:

```bash
df -h .
podman system df -v
podman ps -a --size
du -sh .cache results
```

The laptop cleanup on 2026-10-29 recovered completed/superseded builder layers,
prefetch containers and an obsolete CPU image after checking package inventories.
Free space increased from approximately 13 to 22 GiB, including the space used by
subsequent CUDA validation. Source archives, compiled image caches and build logs
were preserved. The inventory record is `results/validation/storage-recovery.json`.

A subsequent small CUDA runtime patch exposed another storage cost: even a
roughly 34 KB image change triggered a fresh 11–13 GiB ownership-remapped copy
on first launch with Podman 4.9. The first attempt was stopped and its temporary
copy reclaimed; removing an unused older CUDA image recovered enough space to
continue. After final validation on 2026-10-30, the superseded CUDA image copy
was removed too, leaving approximately **33 GiB free**. The compiled stack itself
was not growing. Keep enough temporary
space for both the old and new mapped images until validation succeeds.

For repeated image development or larger PCB studies, move Podman's graphroot
and the workflow caches/results to a larger local Linux filesystem, or build on a
server and import only the images needed on this laptop. Moving caches alone
will not solve image-copy growth. A storage migration has **not** been performed.
Do not manually edit/delete Podman's overlay directories; use image/container
commands after verifying that current packages and results are preserved.

The CUDA runtime starts HYPRE's device pool at 256 MiB (it may grow) and uses
direct MFEM CUDA allocations. Its small adapter also turns libCEED allocation
failures into an explicit error. These settings are automatic with `pcb-em build`.
If using `containers/Containerfile.solver` directly for a CUDA build context,
pass `--build-arg SOLVER_MEMORY=cuda` and
`--build-arg SOLVER_PRELOAD=/usr/local/lib/pcb-em-cuda-runtime.so` in addition to
the pinned base and architecture arguments. Direct Docker builds are untested.

Recompile Verilog-A sources on the destination host before loading their OSDI
files. The pinned OpenVAF 23.5.0 binary works with its default native CPU target,
but its `--target_cpu generic` option crashed during validation. The full doctor
check compiles and exercises a fresh OSDI model on each host; compiled model
results are not included in the tool images.

To build for another GPU, substitute its compute architecture:

```bash
./pcb-em build --profile cuda --cuda-arch 80 --cuda-version 12.9.1 --jobs 2
./pcb-em doctor --backend cuda --full
./pcb-em run CASE.yaml --backend cuda --mpi-ranks 1 --gpu-count 1
```

Multiple architectures may be supplied as a comma-separated list, supported by
the pinned CUDA/Spack recipes. Each CUDA variant has a separate lock directory.
The most recently built CUDA image receives the local `:0.1` tag; export an image
before replacing that tag if you need to retain a particular server build.

`PCB_EM_ENGINE=docker` selects Docker for runtime commands. Container recipes use
standard Docker syntax; Podman remains the tested default. Docker requires its
own working rootless configuration and NVIDIA runtime setup. MPI here is
single-node only; distributed schedulers and fabric-specific MPI are not configured.

Build logs live in `.cache/logs`; retained `pcb-em-build-*` containers preserve
compiled packages on failure. Avoid pruning these containers or images until
validation passes. Source paths are mounted read-only. GUI launchers require an
X11/XWayland display and authentication cookie; headless render checks use Xvfb.

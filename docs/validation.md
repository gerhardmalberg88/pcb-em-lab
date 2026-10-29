# Validation status

Observed validation, 2026-10-30. This file records observed checks, not intended
capabilities. Update it after each completed build and numerical check.

See the [implementation checklist and remaining engineering TODOs](TODO.md)
for completed work and open numerical/physical accuracy checks.

The workspace was relocated into `pcb-em-lab` on 2026-10-30. Existing historical
logs and provenance retain their recorded absolute paths; map the old workspace
root to the current checkout when inspecting them. The path mapping and metadata
preservation checks are in `results/validation/relocation.json`. After the move,
all 15 Python tests, four-stage COMH cache reuse, CPU isolation, tools source
mounting and the CUDA device/kernel preflight passed. Images were not rebuilt.

| Check | Observed status |
|---|---|
| Rootless Podman | Installed and working, version 4.9.3 |
| Host GPU | RTX 2060, compute capability 7.5; working driver retained |
| GPU inside Podman | Passed `nvidia-smi -L` with CDI after compatibility fix |
| NVIDIA compatibility | Toolkit default CDI 0.7 rejected by Podman 4.9; NVIDIA's `no-additional-gids-for-device-nodes` flag produced compatible CDI 0.5 |
| Native KiCad extraction | 10.0.7; BMS copper, stackup and 198 component placements extracted read-only |
| BMS 2D pipeline | COMH and COML completed extraction, meshing, CPU solving and field rendering; twelve mesh/vertical-domain sweep runs and four wider-section runs passed |
| CPU solver image | Built on pinned snapshot; verified no CUDA dependency and no NVIDIA devices visible |
| Tools image / GUI checks | All CLI/Python interfaces, STEP units, six GUI launchers, ParaView headless rendering and authenticated desktop forwarding passed; Gmsh uses FLTK 1.3.7 |
| CUDA solver image / numerical comparison | Built for CUDA 12.9.1 / SM75. A small HYPRE/libCEED memory adapter passes all three references, including static field export; CPU/CUDA differences 5.49e-5 / 2.24e-6 / 1.60e-10. The installed image passes all 15 full doctor checks and the static invalid-memory-access check with zero errors. COMH differential-mode comparison passes; its second mode exceeds the 0.02% target (details below). |
| Palace BoundaryMode / Driven / Magnetostatic references | All three passed on CPU; maximum relative CSV differences approximately 1.07e-4, 1.31e-5 and 5.65e-8, respectively |
| BMS 3D and internal magnetics | All eight BMS CPU cases passed. COMH and COML 3D each passed sixteen solves and both circuit handoffs. T501 Driven passed twenty-four solves and winding-field rendering; L601/T501/T502 static pipelines passed |
| Backend/cache contracts | Fifteen tests passed, including CPU without GPU probes, explicit CUDA failure, auto fallback, failed-run provenance, no switch after solver failure, artifact cache validation, standard Touchstone reference impedance, port ordering/phase, CAD hole-area preservation and valid 2D boundary adjacency |
| Actual stage-cache and source mounts | All four stages reused; altered mesh artifact, physical setting and disposable source copy invalidated the appropriate stages; read-only source write rejected; missing-board error checked |
| Image transfer | CPU image saved in Docker archive format and imported through `pcb-em import`; image ID unchanged; second physical server untested |
| Palace configuration schema | Generated 2D, 3D Driven and Magnetostatic configurations passed the pinned schema |
| Circuit handoffs | Container RC reference passed Touchstone import, passive fitting, floating-port ngspice, XSPICE, OpenVAF compilation/OSDI and QucsatorRF transfer checks; generated COMH and COML 3D QucsatorRF/ngspice handoffs passed |
| Design preservation | All saved design-file hashes match the starting workspace, including the pre-existing modified project file |

`pcb-em doctor --backend cpu --full` and its CUDA equivalent write evidence under
ignored `results/validation`. CPU checks run without CDI devices and verify that
the solver dependency graph contains no CUDA package. CUDA access alone is not a
solver validation. All BMS physical models remain exploratory until geometry,
material assumptions, mode/port definitions and convergence are reviewed.

The installed runtime selection matrix also passes: explicit CPU and CUDA,
automatic CUDA selection, automatic CPU selection for an unavailable second GPU,
and a clear error for that explicit unavailable CUDA request. No solver failure
caused a backend switch. Evidence: `results/validation/backend-after-cuda.json`.
Final CPU isolation was rechecked after the UID/GID correction; it still has no
CUDA package dependency or NVIDIA device (`cpu/final-isolation.json` under the
validation results directory).

Runtime checks found and corrected an Xvfb readiness-signal hang when its shell
was PID 1; containers now use an init process. The numerical Python environment
explicitly exposes Spack's package view, with an installation check ensuring that
NumPy, SciPy and Shapely load from the Spack store. FLTK 1.4.4 returned invalid
screen dimensions in the Gmsh GUI check; 1.3.7 reports the correct dimensions and
passes the GUI check. ParaView's Qt GUI also needed the ICCCM and keysyms XCB
libraries, now included in the tools image.
Gmsh's HXT optimizer stalled on the bounded PCB with two requested threads in
this build without OpenMP. The same geometry completed with one thread. Meshing
now defaults to one thread and rejects a larger count when Gmsh lacks OpenMP;
solver MPI ranks remain independently configurable, defaulting to two on CPU.
Passive fitting now tries low orders first and records the passivity/error checks
for every attempted order. The RC reference passed at one real pole with RMS
error approximately 2.22e-16. See [server transfer](servers.md) for the observed
OpenVAF target-option limitation and recompilation on each execution host.
The generated COMH handoff exposed a Touchstone interoperability issue:
scikit-rf's optional HFSS impedance comments omitted the scalar reference from
the standard option line. Export now writes an explicit real reference impedance
(`R 100.0` for the BMS cases). QucsatorRF and floating-port ngspice checks then
passed against the actual generated network. QucsatorRF can report a parse error
while returning zero; the handoff checker inspects its log as well as the response.

## CUDA memory policy and diagnosis

A traced 18 MB `cudaMalloc` request failed with out-of-memory status before the
original illegal-access failure. HYPRE's initial Umpire pool was 4 GiB on this
6 GiB card; libCEED's returning error handler could not safely propagate the
allocation error through its success-assuming macro. The small source-controlled
adapter uses HYPRE's public pool-size API and aborts clearly on that CUDA
allocation error. See the pinned
[HYPRE pool defaults](https://github.com/hypre-space/hypre/blob/v3.2.0/src/utilities/umpire.c)
and [libCEED error macro](https://github.com/CEED/libCEED/blob/8a374e8d5d8d33fd19ce69a93026384ec1046a86/include/ceed/macros.h).

The CUDA image now uses direct MFEM allocations and a 256 MiB initial HYPRE
pool, which can grow. An impossible 8 TiB allocation verifies the explicit error
path; it does not trigger CPU fallback. The patch was compiled offline against
the existing image, and all 82 packages in its active Spack environment retain
the same hashes. Image lineage and adapter source/binary hashes are recorded in
`env/locks/cuda-75-12.9.1/image.json`. Future CUDA builds compile the same adapter.
The host driver and physical models were unchanged. Reassess this adapter when
upgrading HYPRE or libCEED; it addresses the pinned versions, not every release.

The unfiltered Compute Sanitizer log includes OpenMPI pointer-classification
API errors. Its
[pinned implementation](https://github.com/open-mpi/ompi/blob/v5.0.10/opal/mca/accelerator/cuda/accelerator_cuda.c)
tries `cuMemRetainAllocationHandle` and handles failure when a pointer is not a
VMM allocation. The separate invalid-memory-access check uses
`--report-api-errors no`; the unfiltered log is retained for inspection. This
filter does not disable memory-access checking. The final image completed the
full static run with zero reported memory errors. Evidence is collected
under `results/validation/cuda-small-pool/` and `results/validation/cuda/`.

Rootless runtime commands explicitly select the caller's UID/GID, preventing
image `USER` metadata from assigning output files to a subordinate host UID.
Actual output ownership, a refreshed CPU COMH run, and all six cache/source-mount
checks passed after this correction (`results/validation/cache-final/checks.json`).

## Numerical studies

The following 2D sweeps used the final tools and CPU solver images, including
extraction, field rendering and provenance. Earlier native preflights are retained
as diagnostic evidence; the values below are from the container pipeline.

| 2D section | Mesh scale 1 | Scale 0.75 | Scale 0.5 | Vertical air margin 9 → 12 mm at scale 1 |
|---|---:|---:|---:|---:|
| COMH differential candidate | 102.144 Ω | 102.422 Ω | 102.713 Ω | 102.254 → 102.267 Ω |
| COML differential candidate | 101.141 Ω | 101.370 Ω | 101.718 Ω | 101.224 → 101.238 Ω |

A unique voltage-parity candidate remained mode 1 in these sweeps. The finest two
meshes changed impedance by about 0.28% / 0.34%; the two largest vertical air margins
changed it by about 0.013% / 0.014%. This does not validate the assumed dielectric
properties or the complete communication link. Field patterns and mesh/domain
limits still need engineering review for a chosen acceptance tolerance.
Evidence: `results/validation/container-convergence.json` and each BMS 2D output's
`sweeps/*/comparison.json`, `metrics.csv` and per-run fields/provenance.

Separate lateral-section checks retained the section centre and vertical margin
while increasing width from 10 to 14 and 18 mm. COMH gave
102.144 / 102.178 / 102.077 Ω; COML gave 101.141 / 101.166 / 101.166 Ω. The last
width changes were about 0.10% and 0.00021%, respectively. COMH's nonmonotonic
trend is smaller than the observed mesh-refinement change; this separate study
does not establish a combined mesh/domain error bound. The unique differential
candidate remained mode 1. Evidence: `results/validation/lateral-convergence.json`
and the BMS outputs' `sweeps/section-width/` cases, fields and provenance.

### Same-mesh COMH CPU/CUDA comparison

The final COMH pipeline ran on CUDA using the identical mesh SHA-256 as CPU.
Voltage-parity screening identified mode 1 as differential in every comparison.
The original all-mode check failed and is retained; its 0.02% threshold was not
relaxed. Field export and postprocessing completed on both backends.

| Settings | Differential Z, CPU / CUDA | Largest differential Z/L/C difference | Second-mode Z, CPU / CUDA | Largest second-mode Z/L/C difference |
|---|---:|---:|---:|---:|
| Supplied settings; CPU 2 ranks / CUDA 1 | 102.144177 / 102.142634 Ω | 0.00171% | 3.285995 / 3.283636 Ω | 0.0719% |
| Both 1 rank; linear tolerance 1e-12, eigen tolerance 1e-10 | 102.144283 / 102.142123 Ω | 0.00256% | 3.283867 / 3.289885 Ω | 0.1832% |

With the supplied tolerances and one CPU rank, the two impedances were
102.145033 / 3.285445 Ω. Thus the second mode also changes with CPU rank count
and CPU solver tolerances. Tightening tolerances does not resolve its sensitivity.
Low-frequency conditioning or port-derived quantities need further investigation;
this is an interpretation of the probes, not a proven root cause. Small reported
backward residuals do not establish precision of every modal observable.
The differential-mode comparisons pass the threshold, but do not establish
physical accuracy. Do not claim the second mode has passed this accuracy check.
Evidence: `results/validation/cuda/bms-comparison.json`,
`results/validation/cuda/bms-numerics/comparisons.json`, and the retained failure
in `.cache/logs/final-cuda-validation-sequence.log`.

The final bounded COMH 3D pipeline produced a complete two-port network at eight
frequencies from 1 to 10 MHz, with maximum sampled singular value 1.000000002 and
reciprocity error 2.51e-9. Its field-error indicator norm is about 0.56. The coarse
first-order mesh is a pipeline check, not a converged field prediction. QucsatorRF
matched the exported S21 within 4.89e-9; the passive fitted ngspice model's matched
load voltage differed by at most 0.000496 V over the checked band, including a
10 V floating output reference. The input plane is on parallel secondary traces
near the connector; the cropped transformer-pad stubs remain in the model.
COML completed the same eight-frequency/two-excitation pipeline. Its sampled
maximum singular value was 1.000000001 and reciprocity error 5.57e-10. Its QucsatorRF
S21 error was below 5.27e-9, and the floating-reference ngspice voltage error below
0.000496 V. Both passive fits have in-band RMS error about 0.00140. Evidence:
`results/validation/official-cpu-runs.json` and `results/validation/bms-handoffs/checks.json`.

A T501 Driven preflight excited all eight turn ports at 1 MHz and produced a
four-winding network. Complex field superposition was checked against the
terminal voltages and net currents, including incident-source current. A later
static sensitivity check exposed incompatible curved source-gap edges. Replacing
them with rectangular gaps made all eight static sources converge at the same
1e-8 tolerance. Sixteen corrected mesh/domain/material runs using the pinned CPU
image and native validation mesher passed; older magnetic preflights
are retained only as diagnostic evidence. L601 permeability 50/100/200 gave
138.44/142.35/144.36 nH. Refining mesh scale 1/0.75/0.5 gave
142.33/146.44/150.72 nH. Additional scales 0.35/0.25 gave 153.14/154.56 nH
(a 0.93% last successive change). Increasing the air-domain half-size
6/9/12/16/24 mm gave 134.98/142.27/144.69/145.81/146.77 nH
(a 0.66% last successive change). These are separate mesh/domain studies, not
a combined error bound. These values are far below the saved 220 µH component
value: the template is an uncalibrated workflow demonstrator. Numerical refinement
and physical-model calibration are separate tasks. Evidence:
`results/validation/native-magnetic-studies-rect/studies.json`.

Those native studies also include T501 transformer permeability 250/500/1000,
with primary self-inductance approximately 28.11/28.33/28.45 nH. A subsequent
container sweep varies only the integrated-choke permeability over the same
values while keeping identical mesh bytes: its positive-winding self-inductance
is 21.151/21.277/21.341 nH. All three runs completed all eight source excitations
and winding-field postprocessing. T501 and T502 have identical configured
internal geometry, materials, mesh and numerical settings, so this isolated
template study applies to both configurations. It does not establish their real
internal construction or magnetic properties. Evidence:
`results/validation/transformer-cmc-sensitivity.json` and hardware
`sim/results/em/t501-internal/sweeps/magnetics-cores-1-mu_r/`.

The final T501 Driven container case completed all eight turn excitations at
0.1, 4 and 10 MHz. Its four-winding network was reciprocal to 8.70e-12 and passive
at the sampled frequencies. Each frequency also produced four one-ampere-peak
winding-field combinations, with current residual below 4.45e-16 A and terminal
voltage discrepancy below 2.17e-11 V. The static L601/T501/T502 winding matrices
are symmetric and positive definite. These checks establish numerical consistency
of the templates, not their accuracy as representations of the physical parts.

The saved-board audit found 21 physical stackup layers/sublayers, including eight
copper layers; total thickness is 1.708 mm, matching the board setting. It recorded
368 vias, 80 drilled pads, 198 components and 14 keepouts. COMH polarity is
J501 pin 1 positive / pin 2 negative; COML is J502 pin 2 positive / pin 1 negative.
All recorded keepout intersections are edge slivers within the 0.002 mm polygon
tolerance, with no overlap remaining inside the eroded keepout interiors. No
copper was removed to obtain that result. Fourteen saved design-file hashes
still match the starting workspace, including its pre-existing project changes.

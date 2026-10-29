# Implementation checklist against the approved plan

**Status, 2026-10-30: CPU, tools and CUDA images are installed and exercised.**
Both full doctors pass, all three CPU/CUDA reference comparisons pass, and the
GPU memory-access diagnostic reports zero errors. All eight BMS CPU pipelines
completed. The same-mesh COMH differential-mode comparison passes; the auxiliary
second-mode comparison exceeds the 0.02% target and remains an open numerical
accuracy check. The retained failure and sensitivity results are documented below.

Disk space is approximately **33 GiB free** after removing verified superseded
image copies. The storage recommendation and remaining engineering work are at
the end of this checklist. No storage migration or driver replacement was made.

This is the tracking document for what is done and what comes next. Checked boxes
mean the stated work or check has actually been completed. Implementation and
validation are listed separately where they differ. Detailed numerical evidence
and limitations are in [validation.md](validation.md); commands and configuration
are in the [root README](../README.md), [cases.md](cases.md) and
[servers.md](servers.md). Evidence paths below are relative to this repository
unless explicitly identified as hardware-repository paths. Generated evidence is
ignored by Git and remains on this machine.

## Scope to preserve

- Separate reusable `pcb-em-lab` repository; BMS cases stay in
  `../bms-cmu-bq79616-hardware`.
- Rootless Podman, Docker-compatible recipes, separate tools/CPU/CUDA images,
  Spack environments and dependency locks.
- CPU operation without CUDA or NVIDIA devices; optional CUDA 12.9.1 / SM75 for
  this RTX 2060, with architecture configurable for servers.
- KiCad extraction → Gmsh → Palace → ParaView and circuit handoffs; selectable
  2D, 3D PCB and approximate internal-magnetics analyses.
- Explicit backend selection; automatic fallback only at GPU preflight, never
  after a solver/model failure.
- Preserve original design files, unrelated working-tree changes, build caches,
  logs and provenance. Keep the working graphics driver.
- Thermal work remains documentation/placeholders and a Mermaid workflow.
  Installing Elmer or implementing thermal solvers is outside this EM plan.
- No expansion into cables/external assemblies, saturation, hysteresis,
  distributed MPI, or component qualification.

## 1. Repositories and documentation

- [x] Create the separate local workflow repository and CLI launcher.
- [x] Move the complete workspace into the cloned `pcb-em-lab` repository
  (2026-10-30), retain its Git metadata, rename package/documentation references,
  and update BMS links. Preserve old local Git metadata under ignored
  `.cache/relocation/source-repository.git`; move caches/results without copying.
- [x] Apply Apache-2.0 to the workflow's original software and documentation
  (2026-10-30); update LICENSE, NOTICE and Python package metadata. The BMS
  hardware repository retains CERN-OHL-P-2.0. No Git actions were performed.
- [x] Keep BMS physical cases in the hardware repository.
- [x] Remove both workflow XMLs from the repository and replace their links.
- [x] Put simplified EM and thermal Mermaid diagrams in the workflow root README.
- [x] Document EM case directories and the thermal balancing-resistor placeholder.
- [x] Document configuration, GUI use, server transfer and observed validation.
- [x] Preserve the pre-existing modified KiCad project file; all 14 saved design
  hashes still match the starting workspace.

Evidence: `results/validation/design-preservation.json` and
`results/validation/document-links.json` (local documentation links rechecked). No commits or publication have been performed.

## 2. Environments and installation

- [x] Install and verify rootless Podman 4.9.3.
- [x] Diagnose host GPU access: RTX 2060 works; graphics driver retained.
- [x] Install NVIDIA Container Toolkit/CDI using the user-completed sudo steps.
- [x] Correct the CDI format compatibility issue with Podman 4.9.
- [x] Pin Spack 1.2.2, Palace 0.18.1, KiCad 10.0.7, container base/snapshot,
  package recipes and downloaded artifact checksums.
- [x] Build the tools image: KiCad, FreeCAD, Gmsh, ParaView/pvpython, scikit-rf,
  Qucs-S/QucsatorRF, ngspice with XSPICE/OSDI, and OpenVAF.
- [x] Build the CPU solver image and verify no CUDA dependency or GPU device.
- [x] Build the CUDA solver image with CUDA 12.9.1 and architecture 75.
- [x] Export dependency locks, package inventories and image provenance.
- [x] Implement independent CPU/CUDA/all builds, configurable architecture and
  toolkit, two default build jobs, two CPU ranks and one GPU rank.
- [x] Keep tool-specific Python environments isolated with file handoffs.
- [x] Finish numerical validation of the CUDA image; building it is not a pass.

Current local image IDs (short form): CPU `f19db8891045`, tools `c2dce1744a4b`,
CUDA `510b7d5e247e`. See `env/locks/{cpu,tools,cuda-75-12.9.1}/` and
`env/pins.json` for complete identities and versions.

## 3. CLI, execution and portability

- [x] Implement `bootstrap`, `build`, `doctor`, `run`, `gui`, `sweep`, image
  `export` and `import`.
- [x] Separate execution settings from physical-model settings; CLI overrides
  case execution settings.
- [x] Implement `extract`, `mesh`, `solve`, `postprocess`, `all` and prerequisites.
- [x] Implement strict CPU, explicit CUDA and automatic preflight selection.
- [x] Test that CPU does not probe NVIDIA and solver failures never switch backend.
- [x] Record source/configuration/tool/implementation hashes and failed-run provenance.
- [x] Exercise actual cache reuse, changed-artifact/source/config invalidation,
  read-only source mounts and actionable missing-board errors.
- [x] Export/import the CPU image in Docker archive format and verify identical ID.
- [x] Document equivalent single-node x86-64 server commands and GPU architecture
  parameters.
- [x] Complete the real-runtime selection matrix after the final CUDA fix:
  explicit CPU, explicit CUDA, auto CUDA, auto CPU with an unavailable requested
  GPU, and clear failure for that explicit unavailable CUDA request.

Evidence: `tests/`, `results/validation/cache-final/checks.json`, and
`results/validation/cpu-image-transfer/checks.json`. The latest test run passed
all 15 tests. The final installed-image matrix passes; see
`results/validation/backend-after-cuda.json`. Docker execution and a second physical server are documented but
have not been tested on this machine.

## 4. KiCad and physical-model pipelines

- [x] Extract saved stackup, copper/fills/tracks/pads/vias, holes, outline,
  placements, model transforms and isolation keepouts without saving/refilling
  the source design.
- [x] Audit board heights, holes, connector polarity and keepouts: 21 stackup
  layers/sublayers, eight copper layers, 1.708 mm total thickness, 198 components,
  368 vias, 80 drilled pads and 14 keepouts.
- [x] Implement 2D sections, Gmsh meshes, Palace BoundaryMode input, impedance,
  propagation/per-length reporting and field rendering.
- [x] Run COMH and COML 2D CPU cases plus mesh, vertical-domain and lateral-width
  convergence studies.
- [x] Implement layered 3D PCB geometry, copper, through-vias/pads, configurable
  connector contacts, cropped/whole-board selection and explicit mechanical STEP
  inputs with material/transform configuration.
- [x] Run bounded COMH and COML 3D CPU cases: two ports × eight frequencies each.
  Model ends at board-mounted connector contacts; no external cables.
- [x] Export ordered/polarized Touchstone networks, fields and circuit handoffs.
- [x] Implement editable approximate T501/T502 transformer plus integrated
  common-mode-choke models and an L601 model.
- [x] Run T501/T502/L601 linear static CPU cases and T501 small-signal Driven
  case (eight turn excitations × three frequencies).
- [x] Generate signed winding matrices and correctly normalized linear winding
  field combinations, with current/voltage consistency checks.
- [x] Run L601 material, mesh and domain sensitivity studies and T501 transformer
  permeability 250/500/1000; expose magnetic dimensions and winding parameters.
- [x] Audit magnetic sensitivity coverage: L601 material/mesh/domain studies,
  T501 transformer permeability and the integrated-choke permeability sweep are
  complete. T501/T502 have identical internal-model, mesh and numerical settings;
  these isolated-template sensitivities apply to both configured models, not to
  unverified supplier internals. The choke sweep used identical mesh bytes.

Evidence: hardware `sim/results/em/`,
`results/validation/official-cpu-runs.json`,
`results/validation/container-convergence.json`,
`results/validation/lateral-convergence.json`, and
`results/validation/native-magnetic-studies-rect/studies.json`.
Additional shared-template evidence:
`results/validation/transformer-cmc-sensitivity.json` and hardware
`sim/results/em/t501-internal/sweeps/magnetics-cores-1-mu_r/`.

**Physical confidence remains limited.** The bounded 3D cases use coarse,
first-order PEC approximations; COMH's field-error indicator is about 0.56, so this
is not a converged field prediction. Connector geometry is simplified. Magnetic
geometry/materials are inferred templates; L601 predicts roughly 0.14–0.15 µH,
far below its saved 220 µH component value. Numerical convergence does not
calibrate that model. Whole-board solving and arbitrary component STEP geometry
have not been demonstrated on the BMS board; the bounded cases are the completed
3D validation. Blind/buried vias and crops bisecting holes are rejected explicitly.

## 5. Tool and circuit validation

- [x] Verify installed CLI tools and Python interfaces.
- [x] Verify six GUI launchers, authenticated desktop forwarding, FreeCAD-to-Gmsh
  STEP units and ParaView headless rendering.
- [x] Pass all three Palace reference examples on CPU: BoundaryMode, Driven,
  Magnetostatic, compared with upstream reference tables.
- [x] Demonstrate CPU execution with no NVIDIA devices and no CUDA dependency.
- [x] Exercise Touchstone import, passive fitting, QucsatorRF, floating-reference
  ngspice, XSPICE and a compiled Verilog-A/OSDI model.
- [x] Exercise generated COMH/COML 3D QucsatorRF/ngspice handoffs, not just a toy
  network.
- [x] Pass CUDA device/kernel preflight and Palace version checks.
- [x] Pass BoundaryMode and full Driven GPU references using direct CUDA
  allocation. Maximum CPU/GPU CSV relative differences: approximately 5.49e-5
  and 2.24e-6, respectively.
- [x] Run isolated Driven GPU Compute Sanitizer check with zero reported errors.
- [x] Pass Magnetostatic GPU reference including field export and CPU comparison.
- [x] Pass the complete final `doctor --backend cuda --full` run.
- [x] Run the same-mesh BMS COMH 2D CPU/CUDA comparison and record its result.
- [x] Validate any GPU fix with a targeted memory check and numerical comparisons;
  do not accept a run merely because it no longer crashes.

Evidence: `results/validation/cpu/doctor.json`,
`results/validation/cpu/palace/references.json`,
`results/validation/bms-handoffs/checks.json`, and
`results/validation/cuda/palace/references.json` (all three GPU references),
`results/validation/cuda/doctor.json` (all 15 checks passed), and
`results/validation/cuda/bms-comparison.json`.

The COMH comparison used identical mesh bytes. Differential-mode Z/L/C differed
by at most 0.00171% at the supplied settings and 0.00256% with tighter solvers.
The second mode differed by 0.0719% / 0.1832%, respectively, exceeding the 0.02%
comparison target. CPU-only rank/tolerance changes also perturb that mode. The
strict all-mode check remains failed; the threshold was not relaxed. Evidence:
`results/validation/cuda/bms-numerics/comparisons.json` and the original
`.cache/logs/final-cuda-validation-sequence.log`.

## 6. CUDA memory fix: installed and validated

The failure was traced to an actual failed 18 MB CUDA allocation. HYPRE 3.2's
initial Umpire device pool reserves 4 GiB on this 6 GiB GPU. libCEED 1.0's
`CeedCall` success assumption can hide the returning allocation error and leave
a null field buffer. Direct MFEM CUDA allocation alone was insufficient.

The explicit runtime adapter in `containers/cuda-runtime.c` starts HYPRE's pool
at 256 MiB through its public API (the pool can grow), and makes a CUDA allocation
failure fatal before libCEED can continue with a null buffer. The CUDA image also
uses `MFEM_MEMORY=cuda`. No driver replacement, model change, field suppression
or automatic solver fallback is involved.

- [x] Pass all three reference cases with the installed adapter, including static
  field export. CPU/CUDA maximum relative differences: BoundaryMode 5.49e-5,
  Driven 2.24e-6, Magnetostatic 1.60e-10.
- [x] Exercise a deliberately impossible allocation and verify its clear
  GPU-memory error.
- [x] Include adapter compilation and runtime policy in future CUDA builds.
- [x] Complete the targeted Magnetostatic memory diagnostic: zero invalid-memory
  errors with the final image. Expected OpenMPI pointer-probe API failures are
  documented separately.
- [x] Complete installed-image validation and provenance update.

Evidence: `results/validation/cuda-small-pool/palace/references.json`,
`results/validation/cuda-small-pool/oom-check.log`,
`.cache/logs/cuda-pointer-malloc.log` (root cause), and
`.cache/logs/cuda-final-memory-access.log` (zero memory errors).
Earlier failed diagnostic logs remain preserved under `.cache/logs`.

## 7. Disk-space recovery

- [x] Investigate the user's approximately 13 GiB remaining-space report.
- [x] Identify duplicate completed builders/prefetch layers and rootless image
  ownership-remapping copies as major contributors.
- [x] Verify package inventories before removing completed/superseded builders
  and one obsolete CPU image; preserve current compiled images, source archives
  and logs.
- [x] Add automatic successful-builder removal after image commit and provenance
  export; retain failed builders for resumption.
- [x] Document storage inspection and temporary-space needs in [servers.md](servers.md).

At resumption, approximately 22 GiB was free on the 172 GiB filesystem. A tiny
CUDA image patch triggered another 11–13 GiB ownership-remapped copy on first
launch. That attempt was stopped and its temporary copy reclaimed. Removing an
unused older CUDA image provided space for the retry; after final validation,
the superseded direct-allocation image and completed patch builder were removed.
Approximately **33 GiB is now free**. Source/download cache is about 8.9 GiB;
workflow validation results about 7 GiB; BMS results about 4.3 GiB.

Keep the current images, source archives, locks, logs and numerical evidence.
`podman system df` counts shared layers and mapped copies differently from actual
filesystem usage; monitor `df` as well. Evidence:
`results/validation/storage-recovery.json` and `storage-final.json` in that directory.

## Remaining engineering TODOs

The installation and pipeline work above is usable for the documented exploratory
cases. These checks remain open before stronger numerical/physical claims:

- [ ] **Resolve COMH second-mode precision** if that mode is needed. Investigate
  low-frequency eigenproblem conditioning and port-derived quantities. CPU rank
  and CPU/GPU tolerance probes are already recorded; tighter tolerances alone
  did not resolve the discrepancy. Preserve the failed 0.02% check.
- [ ] **Choose engineering acceptance criteria and calibrate physical inputs.**
  Review differential-mode fields and combined mesh/domain error; obtain actual
  dielectric, connector and magnetic geometry/material data. The coarse 3D
  fields and inferred magnetic templates are not qualified device predictions.
- [ ] **Select a larger storage location before repeated image builds or large
  board studies.** Moving Podman's graphroot plus caches/results to a larger
  Linux filesystem is recommended; server-side image builds are another option.
  Current exploration can continue with the recovered space. No migration has
  been performed, and no additional large build is running.
- [ ] **Validate deployment-specific configurations when needed:** the actual
  target server/GPU architecture, Docker execution, whole-board models and
  user-supplied component STEP geometry. The completed checks used this laptop,
  Podman, bounded PCB cases and the documented approximations.

Final audit: 15 Python tests pass; all 14 design hashes remain unchanged; both
workflow XMLs and their links are absent; all eight canonical CPU cases report
complete; final CPU isolation and cache checks pass. Source changes remain local
and uncommitted. No full numerical-stack rebuild was needed for the GPU fix.

# Cases and physical assumptions

Start with the self-contained [differential-pair example](../examples/differential-pair/README.md)
for small 2D/3D cases and GUI instructions.

Meshing defaults to one thread. The pinned Gmsh profile lacks OpenMP, so
`mesh.threads` must be 1; requesting more fails clearly. This avoids an HXT
optimization stall observed on the thin layered PCB with two requested threads.
Palace's independent CPU MPI default remains two ranks with one thread per rank.

Paths in a case resolve relative to the case file. `project_root` contains the
board and any project-local assets. `output` must be a dedicated generated-results
directory. BMS cases write under `sim/results/em`, already ignored by that repository.

Common keys:

```yaml
name: communication-section
mode: 2d
analysis: boundary-mode
board: ../../../design/board.kicad_pcb
project_root: ../../..
output: ../../results/em/communication-section
execution: {backend: auto, threads_per_rank: 1, gpu_count: 1}
mesh: {fine_mm: 0.05, coarse_mm: 1.5, scale: 1, order: 2}
materials:
  substrate_epsilon_r: 4.5
  soldermask_epsilon_r: 3.3
assumptions:
  - Replace material estimates with the manufacturer's characterized stackup.
```

Optional `exports: {step: true}` adds a KiCad board/copper STEP preview during
extraction, without component bodies. It uses the KiCad user origin `0x0mm` and
millimetres; it is not an input to the solver and its axes differ from the EM
geometry. The option participates in the extraction cache key. Gmsh exports
`mesh/geometry.brep` alongside the tagged mesh for both 2D and 3D cases.

The extractor records all enabled copper layers, saved zone fills, tracks/arcs,
pads, drilled holes, footprint placement, model transforms and rule-area keepouts.
Geometry uses saved copper rather than netclass defaults. It does not introduce
a reference plane across an isolation gap. Missing saved fills are reported.
Coordinates are saved KiCad XY in millimetres; z=0 is the top of F.Cu, with positive
z above the board. Footprint geometry has already been transformed by KiCad.
`mesh/source-audit.json` records contiguous layer heights, hole counts, explicit
port pad/net polarity and saved copper intersecting applicable keepouts. A
zone-fill-only keepout does not prohibit tracks or pads. Reported overlaps never
cause the extractor to delete copper or change the saved PCB.

## 2D BoundaryMode

`cross_section.line_mm` gives two endpoints of a line through the PCB in XY.
The two nets in `pair` (positive, negative) must intersect that line. The section contains
all intersected copper and physical dielectric sublayers, surrounded by air.
The line endpoints set the lateral extent; `air_margin_mm` expands the vertical
air region above and below the stackup. Check section width separately when
assessing lateral-boundary sensitivity.
The solver uses finite copper thickness and PEC boundaries. The model is a
uniform line approximation, not an end-to-end communication link.

```yaml
frequency_hz: 4000000
cross_section:
  line_mm: [[292, 123], [302, 123]]
  pair: [/bq79616/COMHP, /bq79616/COMHN]
  air_margin_mm: 6
  target_index: 1.8
  modes: 2
```

`mode-Z.csv` contains modal impedance and applicable per-length parameters;
the other Palace CSVs contain propagation and mode information. Inspect field
polarity to identify differential and common modes. Do not equate the first
eigenmode or a magnitude-only voltage integral with a validated differential line.
Compare progressively smaller `fine_mm`, higher order, and larger air domains.
Keep the same mode definition when comparing runs.

```bash
./pcb-em sweep CASE.yaml --parameter mesh.fine_mm --values 0.08 0.06 0.04 --backend cpu
./pcb-em sweep CASE.yaml --parameter mesh.scale --values 1 0.75 0.5 --backend cpu
./pcb-em sweep CASE.yaml --parameter cross_section.air_margin_mm --values 6 9 12 --backend cpu
./pcb-em sweep MAGNETICS.yaml --parameter magnetics.cores.0.mu_r --values 50 100 200 --backend cpu
```

Each sweep writes independent resolved cases, results and a summary under the
case output directory. `metrics.csv` and `comparison.json` give successive changes
in differential-candidate impedance/L/C or winding self-inductances. Ambiguous
2D mode selections are not compared automatically. Sweep tables expose sensitivity; convergence acceptance
still requires matching the same physical modes and reviewing the selected metric.
`mesh.algorithm_3d` selects HXT (`10`, default) or Delaunay (`1`) for 3D PCB
meshes. Delaunay is useful when HXT improvement is slow on thin PCB geometry.
Optional `mesh.cad_tolerance_mm` sets both CAD and boolean tolerance in mm
(maximum 0.001 mm); record it and keep it well below source geometry precision.
This can help dense coplanar IC-pad geometry without editing the source PCB.
`mesh.drill_chord_error_mm` optionally reduces drill/barrel polygon faceting to a
bounded radial error, never exceeding the extractor's polygon tolerance. Pads,
copper sheets and dielectrics use the same subtracted bore polygon, preserving
contact. The default keeps the original 48-segment circles. Setting
`mesh.extend_from_boundary: false` stops very fine boundary sizes from spreading
through entire faces/volumes; this changes mesh density and requires sensitivity
checks, while retaining the constructed geometry.
The generated `geometry.json` records the algorithm, tetrahedron count, minimum
`minSICN` quality and count below 0.01; nonpositive quality prevents solving.
A positive-quality mesh still requires numerical convergence checks.
`mesh.optimize: false` disables automatic tetrahedron optimization for a bounded
coarse run; positive orientation is still checked. Treat local field peaks and
absolute values as exploratory until mesh/domain sensitivity is established.

`mesh.scale` globally scales the mesh sizes and is the primary refinement control
for 3D cases. `fine_mm` and `coarse_mm` bound local sizes; the 2D generator also
uses `fine_mm` in its explicit refinement field around conductors.

Optional `numerics.linear_tolerance`, `numerics.max_iterations` and
`numerics.estimator_multigrid` control linear convergence and the error estimator.
Defaults are 1e-9 / 100 iterations for 2D and 1e-8 / 200 for 3D; 3D enables the
multigrid error estimator. These settings are shared by CPU and CUDA runs.
Optional `numerics.estimator_tolerance` and `numerics.estimator_max_iterations`
map to Palace's separate flux-error estimator controls. They do not change the
main field-solver tolerance. Use a looser estimator tolerance only for approximate
diagnostics, record it in the case assumptions, and do not treat its indicators
as a mesh-convergence certificate. Omitted settings retain Palace's defaults.
A Palace warning that a linear solve did not converge prevents a successful cache
entry even when the solver process returns zero.

## 3D PCB Driven

`region_mm: [xmin, ymin, xmax, ymax]` selects a bounded region; omit it for the
whole board. The model includes dielectric layers, copper sheets at each layer's
midplane, drilled holes and plated barrel surfaces. Copper is PEC in the initial
generator, so conductor loss and skin effect are not represented. The initial
connector representation is editable square contacts. A connector housing can
be supplied as a separate mechanical solid. The modeled connection ends at the
board-mounted contacts and excludes mating cables and external assemblies.

`connectors` supplies `ref`, `height_mm` and `pin_width_mm`. Ports name their
positive/negative component pads (`J501:1`, `J501:2`) and `reference_ohms`.
Optional `positive_xy_mm` / `negative_xy_mm` place a calibration plane on the
corresponding saved F.Cu net. The generator rejects coordinates outside those nets
and a gap crossing other copper. The port's integration direction runs from the
declared positive to negative terminal. `geometry.json` records actual coordinates.
Optional `positive_net` / `negative_net` assertions detect a pin/net assignment
change before solving; the supplied BMS connector cases use them.
Pin-top ports end at board-mounted connector contacts.
Uniform lumped ports require a rectangular gap. Place a trace calibration plane
between parallel straight trace segments; a gap clipped by angled fanout edges is
rejected before meshing. Copper beyond that calibration plane remains part of the
model, so record any open pad/trace stubs in the case assumptions.

Connector through-holes receive an ideal conductive solder fill connecting the
contact to the plated barrel. Its conductivity is PEC, matching the initial copper
approximation. Ordinary vias retain hollow plated barrels.
The initial drill model supports through holes. It rejects blind/buried vias and
crops that bisect a hole, rather than extending a partial drill through the board.

Optional `mechanicals` entries import separate, closed STEP solids from paths
relative to `project_root`. Supply `step`, `name`, `translation_mm`,
`rotation_xyz_deg` (X then Y then Z), and `scale`, plus either `material: PEC` or
`epsilon_r`, `mu_r`, and `loss_tangent`. Parts must fit inside the air domain and
dielectrics must not overlap. Use board coordinates verified against KiCad exports.
Extraction records KiCad model transforms for review; the mesher does not guess a
model's material or silently convert every footprint's visual model into an EM solid.

All ports are excited in separate Driven runs with identical frequency samples.
`postprocess/network.sNp` records port names, polarity/calibration metadata in
standard comments and a real scalar reference impedance on its option line, while
`report.json` records ordering, terminal polarity and fit status. A transient
subcircuit is exported only after successful vector fitting, passivity testing
and enforcement; fewer than eight samples deliberately produces no fit. Supply
a broad, sufficiently resolved frequency band for transient use.

`qucsatorrf.net` supplies a ready RF network handoff. Its linear frequency grid
interpolates the solved Touchstone samples. A successful passive fit also supplies
`differential-network.cir`, whose subcircuit terminals are `p1 n1 p2 n2 ...`.
Controlled voltage/current interfaces preserve each physical port's floating
reference; the internal fitting ground is not a galvanic common-mode connection
between ports. Supply real bias/reference paths in the surrounding circuit.
The raw `network.cir` is the fitting implementation in abstract port coordinates.

## Internal magnetics

Use `mode: 3d`, `analysis: magnetostatic` or `magnetic-driven`, and `component`.
Each `magnetics.cores` entry defines name, centre, cylinder radius/height, and
linear relative permeability. Each winding defines centre, turns, radius,
conductor width, axial pitch and sign. Each resolved turn has its own terminal.
Each source gap is rectangular so its uniform sheet current has no unintended
normal component through the side edges. Curved source gaps can make the static
curl-curl equation incompatible even when a Driven run returns a result.
Series winding inductance is calculated from the complete signed turn matrix.
Postprocessing also superposes the saved unit-current turn fields into one-ampere
winding fields (`winding-*.vtu`). Only linear field arrays are summed; energy
density is not incorrectly added across separately excited snapshots. Raw Palace
snapshots remain available for individual turns and other current combinations.
Each snapshot is first divided by its excitation current from `terminal-I.csv`;
the saved solver fields are not assumed to represent one ampere.
Driven runs retain the complete `turn-network.sNp` and combine signed turn
impedances into series-winding ports (`Z_winding = W.T Z_turn W`). The main
Touchstone and circuit handoffs then use winding port names and polarity.
These ideal series connections omit the helical leads and their parasitics.
Driven field postprocessing also combines all turn excitations with complex
weights to impose one peak ampere in the selected winding and zero current in
the other windings. `driven-winding-weights.json` records the current residual
and comparison with network terminal voltages; `winding-*.pvd` steps through
frequency in Hz. This uses the net turn current, including the incident source,
not just Palace's `V/R` termination-current columns. Only linear E/B fields are
combined; energy and Poynting arrays must be recomputed from those fields.
The current convention follows the [pinned Palace implementation](https://github.com/awslabs/palace/blob/0dc74cdf8c36c58b69b21c4a06e816048ec0b83f/palace/models/postoperator.cpp).
One ampere is a linear normalization, not an asserted operating current or a
prediction that the actual core remains unsaturated at that current.

A multi-core case can use separate transformer and common-mode-choke cores
and winding sets. Dimensions, turn counts and materials supplied without
manufacturer evidence are **inferred placeholders**, not recovered internals.
Package STEP files cannot establish winding topology. The open cylindrical cores
and gapped sheet turns deliberately expose editable assumptions and may differ
substantially from the actual closed magnetic circuit. Do not claim component
field accuracy from terminal inductance agreement alone.

Sweep permeability, core dimensions, winding spacing and domain size. Record
numerical convergence separately from sensitivity to uncertain physical inputs.
Saturation, hysteresis and nonlinear core behavior are outside these Palace cases.

## Review gates

Review source hashes, extracted layer heights, pad/net polarity, holes, keepouts,
physical group tags and field plots. Check mesh and domain convergence and
reciprocity/passivity where applicable. Link reviewed conclusions to the hardware
analysis document; generated plots alone do not close an engineering requirement.

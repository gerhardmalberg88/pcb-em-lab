# Standalone differential-pair example

This synthetic 20 × 12 mm PCB exercises KiCad → Gmsh → Palace → ParaView without
another checkout, external footprints or component models. Its files are
Apache-2.0. It is a teaching fixture, not a manufacturing design or an impedance
qualification. The supplied saved PCB is ready to use.

Two 0.8 mm top traces have a 0.6 mm edge gap over a rectangular bottom ground
plane. J1/J2 pad 1 is `P`, pad 2 is `N`. The saved stackup has 35 µm copper,
a 0.93 mm core with εr = 4.2, and two 15 µm mask layers with εr = 3.3.
Estimated dielectric losses are zero. The 2D cut at x = 10 mm is marked on
`Dwgs.User`; the 3D ports are 13 mm apart, with open pad/trace stubs beyond them.

| Case | Calculation | Output under `results/examples/differential-pair/` |
|---|---|---|
| `case.yaml` | Two cross-section modes at 100 MHz, modal impedance and per-length quantities | `2d/` |
| `driven.yaml` | Two-port network at eight frequencies, 100–800 MHz, fields and circuit handoffs | `3d/` |

Both use PEC copper: finite thickness in 2D, sheets at layer midplanes in 3D.
They omit conductor loss. Their small meshes and finite air domains have not
undergone convergence studies; results demonstrate operation, not accuracy.

## Run

From the lab root after [installation](../../README.md#quick-start):

```bash
./pcb-em run examples/differential-pair/case.yaml --backend cpu
# Optional 3D extension
./pcb-em run examples/differential-pair/driven.yaml --backend cpu
```

CPU uses two MPI ranks and one thread per rank. When the CUDA image is built
and verified, add `--backend cuda --mpi-ranks 1` instead. Backend changes rerun
the solver in the same output directory; copy results or change `output` in a
copy of the case first if you want to keep separate comparisons.

Each stage is also independently selectable, with prerequisite resolution:

```bash
./pcb-em run examples/differential-pair/case.yaml --backend cpu --stage extract
./pcb-em run examples/differential-pair/case.yaml --backend cpu --stage mesh
./pcb-em run examples/differential-pair/case.yaml --backend cpu --stage solve
./pcb-em run examples/differential-pair/case.yaml --backend cpu --stage postprocess
```

Extraction reads saved fills without saving/refilling the PCB. `exports.step`
adds a KiCad board/copper preview, with component models excluded. This STEP is
not the solver geometry: it uses KiCad's export axes and `0x0mm` origin. Do not
overlay it on the numerical geometry without checking the transform. The
numerical model uses KiCad XY in mm, z = 0 at the top copper surface, and Palace
`Model.L0 = 0.001`. In 2D, mesh X is distance along the cut and mesh Y is height.

## GUI access to each step

For a menu-driven workflow in VS Code, use **File → Open Workspace from File**
and select [differential-pair.code-workspace](differential-pair.code-workspace).
Then choose **Terminal → Run Task**: `EM 2D` and `EM 3D` tasks run each CPU stage
or the complete case; `Inspect` tasks open KiCad, FreeCAD, Gmsh, ParaView or
Qucs-S. Alternatively, press **Ctrl+P** and type `task EM` or `task Inspect`.
Inspection tasks first run any required pipeline stages. Run one task
at a time for a given case and close its external GUI before rebuilding it.
See the [VS Code task documentation](https://code.visualstudio.com/docs/debugtest/tasks)
for the task menu. No extension is required, and no task starts automatically.

The workspace's PCB task opens `results/examples/differential-pair/gui-source/`.
Edits to this inspection copy do not change the simulation's source board.
Its Qucs-S task opens `gui-circuit/`, preserves schematic edits and refreshes the
generated Touchstone data. Edit the supplied YAML files in VS Code to change
the simulated cases. The commands below provide the same inspection tools
without requiring VS Code.

GUI commands use authenticated X11/XWayland and separate persistent preferences
under `.cache/gui/`. Close an application to return to the terminal. For KiCad's
first launch, accept its default settings and installed footprint-library table
if prompted. The fixture does not need downloaded models or libraries.

| Step | GUI | File |
|---|---|---|
| PCB and 3D board view | KiCad PCB Editor; **View → 3D Viewer** | `board.kicad_pcb` |
| Board/copper STEP | FreeCAD | `extract/board.step` |
| Constructed geometry and tagged mesh | Gmsh | `mesh/geometry.brep`, `mesh/board.msh` |
| Case and solver settings | VS Code or another text editor | YAML, `mesh/case.json`, `solve/fields.json` or `solve/excitation-*.json` |
| Fields, slices and mode/frequency selection | ParaView | `postprocess/view.pvsm`, native `.pvd` files |
| Results and logs | Text editor or spreadsheet | `postprocess/README.md`, `report.json`, native CSVs and `solve/stage.log` |
| Optional circuit reuse | Qucs-S | supplied `network.sch` with `postprocess/network.s2p` from 3D |

Run these from the lab root. Use a copy for KiCad, which may write preferences
beside the board. The output directory is writable in the other GUI sessions:

```bash
mkdir -p results/examples/differential-pair/gui-source
cp -n examples/differential-pair/board.kicad_pcb results/examples/differential-pair/gui-source/
./pcb-em gui pcbnew --workdir results/examples/differential-pair/gui-source -- /work/board.kicad_pcb
./pcb-em gui freecad --workdir results/examples/differential-pair/2d/extract -- /work/board.step
./pcb-em gui gmsh --workdir results/examples/differential-pair/2d/mesh -- /work/board.msh
./pcb-em gui gmsh --workdir results/examples/differential-pair/3d/mesh -- /work/geometry.brep
./pcb-em gui paraview --workdir results/examples/differential-pair/2d -- --state=/work/postprocess/view.pvsm
./pcb-em gui paraview --workdir results/examples/differential-pair/3d -- --state=/work/postprocess/view.pvsm
```

FreeCAD: **0** selects axonometric view, **V, F** fits. Gmsh: **Tools → Visibility**
shows physical groups in `board.msh`; a BREP stores geometry, not physical names.
ParaView's time selector steps through modes (2D) or frequencies (3D). Read the
native CSVs for physical frequencies. Open other native PVD collections to
inspect both port excitations. Field normalization appears in the image; a
modal eigenfield does not represent a specified operating voltage.
When using a host ParaView outside the launcher, relocate `/work` in the
Load State dialog to the case's result directory, or open its native PVD file.
For 3D Gmsh inspection, hide the surrounding air group or use a clipping plane
to reveal the board inside the air domain.

Palace has a JSON/command-line workflow, not a native solver GUI. Edit the YAML
in a GUI text editor and launch the `Solve` task from the supplied workspace,
or run the stage command in its integrated terminal. For
example, with VS Code installed:

```bash
code examples/differential-pair/case.yaml results/examples/differential-pair/2d/mesh/case.json
```

Generated solver JSON is replaced on rerun; change the source YAML for
repeatable runs. Keep manually edited solver files outside stage directories.
See [Running Palace](https://awslabs.github.io/palace/stable/run/).

The 3D run exports 100 Ω Touchstone data and a QucsatorRF netlist. The supplied
`network.sch` is a native GUI schematic with the S-parameter file component,
two matched 100 Ω ports and an eight-point 100–800 MHz sweep already connected.
Its Cartesian plot displays S11 (reflection) and S21 (transmission) in dB.
Copy it beside the generated Touchstone file, open it and press **F2** to
simulate, then close the simulation messages window to see the curves.
A fresh lab GUI profile selects QucsatorRF automatically; if you
already have a profile, select that backend in the simulator toolbar. Existing
preferences are preserved. If the backend path is requested, use
`/opt/qucs-s/usr/bin/qucsator_rf`. Its two abstract ports represent differential
ports, not a four-terminal common-mode network. A SPICE model is exported only
after fit/passivity checks pass; inspect `report.json` before using it.

```bash
cp -n examples/differential-pair/network.sch results/examples/differential-pair/3d/postprocess/
./pcb-em gui qucs-s --workdir results/examples/differential-pair/3d/postprocess -- /work/network.sch
```

## Preserved outputs

The pipeline generates `postprocess/fields.png`, `fields-domain.png` and a
reopenable `view.pvsm`. Native Palace fields, tables, solver inputs and logs
remain alongside derived reports. Stage manifests and `provenance.json` record
hashes, tool identities, backend and completion. Generated outputs are ignored.

Optional regeneration uses KiCad's system Python:
`/usr/bin/python3 examples/differential-pair/generate-board.py NEW.kicad_pcb`.
The generator refuses to overwrite existing files; normal runs use the supplied
saved board directly.

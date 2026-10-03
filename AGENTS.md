# AGENTS.md: helping users with gds2openEMS

This file is for AI coding agents (Claude Code, Codex, Copilot, Cursor, ...)
that help a user build and run openEMS simulation models with gds2openEMS. It
explains the workflow, links to the right documentation for each topic, and
lists the rules and pitfalls that matter when you write or change a model
script for a user.

Read it before you write a model script. When this file and the code
disagree, the code is right: read the source instead of guessing.

## 1. What gds2openEMS does

gds2openEMS builds an [openEMS](https://www.openems.de/) **FDTD** (finite
difference time domain) model from a **GDSII layout** plus an **XML stackup
file** (metal, via and dielectric layers with their materials), runs the
simulation and writes S-parameters. The target technology is IHP SG13G2 (and
SG13CMOS5L): inductors, lines, couplers, capacitors, antennas.

The user provides three things: the GDSII file, the XML stackup file, and a
**model script** in Python. Unlike the sibling FEM workflow gds2palace, the
model script does everything in one run: it builds the model and mesh, shows
a preview, runs the openEMS solver, and computes the S-parameters itself.
openEMS runs locally on Windows, Linux and macOS.

```
GDSII + XML stackup + model script (.py)
        |  python model.py
        v
AppCSXCAD preview (optional) -> openEMS FDTD run, one run per excited port
        v
output/<model>_data/sub-<n>/ (time-domain port data)  ->  <model>.sNp, written by the script
```

How FDTD differs from a frequency-domain solver:

- One run excites **one port** with a wideband pulse and gives **one column**
  of the S-matrix over the whole frequency range. A full S-matrix needs one
  run per port.
- The number of frequency points costs nothing (the result is an FFT), but
  fine meshes are expensive: the time step shrinks with the smallest cell.

## 2. Where things are

This file is at the root of the repository
<https://github.com/VolkerMuehlhaus/gds2openEMS>. All links below are
relative to that root.

**If the user only installed the package** (`pip install gds2openEMS`), the
documentation, examples and stackup files are not on their disk. Read them on
GitHub (prefix the paths below with
`https://github.com/VolkerMuehlhaus/gds2openEMS/blob/main/`), or suggest
cloning the repository. The user needs at least one XML stackup file, e.g.
from [`workflow/`](workflow/), for any model.

The openEMS and CSXCAD Python bindings are **not** ordinary pip wheels on
every platform: they are installed with openEMS itself (pre-built for Windows,
built from source on Linux), see the installation chapter below. Check that
`import openEMS, CSXCAD` works before debugging anything else.

To see the installed version and code: `pip show gds2openEMS`; the package
source is in the `gds2openEMS` folder of the venv's `site-packages`. In a
clone, it is [`workflow/modules/`](workflow/modules/).

### Documentation map

| Topic | Document |
|---|---|
| Overview, installation, examples with result plots | [`README.md`](README.md) |
| User's guide (workflow, settings, ports, meshing, field dumps, antennas, FAQ) | [`doc/userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md`](doc/userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md) (also as PDF in [`doc/`](doc/)) |
| Installing openEMS and CSXCAD | <https://docs.openems.de/python/install.html>, and "Required software and Python modules" in the user's guide |
| Change log | [`doc/CHANGES.md`](doc/CHANGES.md) |
| XML stackup format reference | [`doc/XML_stackup_format.md`](doc/XML_stackup_format.md) |
| Derived layers (layers computed by boolean operations) | [`doc/derived_layers.md`](doc/derived_layers.md) |
| Basic example scripts | [`workflow/`](workflow/) |
| Advanced examples | [`more_examples/README.md`](more_examples/README.md) |
| Helper scripts (port de-embedding, ...) | [`scripts/README.md`](scripts/README.md) |
| openEMS itself (FDTD object, NF2FF, ...) | <https://docs.openems.de/python/> |

### Code map (read these instead of guessing)

| File | Contents |
|---|---|
| [`workflow/modules/util_simulation_setup.py`](workflow/modules/util_simulation_setup.py) | `setupSimulation()`, `runSimulation()`, ports, field dumps. Optional `settings` keys are read with `settings.get(key, default)`: search for that to see all keys and defaults |
| [`workflow/modules/util_stackup_reader.py`](workflow/modules/util_stackup_reader.py) | `read_substrate()`, XML stackup parsing |
| [`workflow/modules/util_gds_reader.py`](workflow/modules/util_gds_reader.py) | `read_gds()`, GDSII reading, via array merging, derived layers |
| [`workflow/modules/util_meshlines.py`](workflow/modules/util_meshlines.py) | xy and z mesh line generation |
| [`workflow/modules/util_utilities.py`](workflow/modules/util_utilities.py) | output paths, `calculate_Sij()`, `write_snp()` |

## 3. Input files

### GDSII layout

- `read_gds()` reads the cell named `cellname`, or the first top-level cell if
  that name doesn't exist. Hierarchy is flattened.
- Only the layer numbers in `layerlist` and the datatypes in `purposelist` are
  read. IHP drawing data is datatype 0: use `purposelist=[0]`.
- Units: the GDSII coordinates are used as they are, in units of
  `settings['unit']` (normally `1e-6`, i.e. microns).
- **Ports** and **field dump boxes** are polygons on extra layers that are not
  in the stackup, by convention 201 and up (see section 4).
- Holes and cutouts are handled automatically. `preprocess_gds` is obsolete
  and only prints a note.
- Geometry can also be added in Python without GDSII:
  [`workflow/run_line_noGDSII.py`](workflow/run_line_noGDSII.py), or combined
  with GDSII: [`more_examples/combine_layout_sources/`](more_examples/combine_layout_sources/).

### XML stackup

- Stackup files for openEMS are in [`workflow/`](workflow/):
  - `SG13G2.xml`, `SG13G2_200um.xml`: SG13G2 with substrate.
  - `SG13G2_200um_backsideGND.xml`: with backside metal.
  - `SG13G2_nosub.xml`: no substrate, for structures shielded by a ground
    metal.
  - `SG13CMOS5L*.xml`: the same variants for SG13CMOS5L.

  A parameterized SG13G2 stackup with `<Variables>` is in
  [`more_examples/parameterized_XML_stackup/`](more_examples/parameterized_XML_stackup/).
- **gds2openEMS stackups and gds2palace stackups are not interchangeable**,
  even for the same technology. They model e.g. the MIM dielectric
  differently. Never use a gds2palace stackup file with gds2openEMS or the
  other way round.
- Stackup `<Variables>` can be changed from the script without editing the
  XML: `stackup_reader.read_substrate(XML_filename, variable_overrides={'total_thickness': 100})`.
- Layers that are not drawn directly (e.g. resistors) are `<DerivedLayers>`:
  boolean operations on other layers, resolved automatically by `read_gds()`.
  See [`more_examples/resistors_sg13g2/`](more_examples/resistors_sg13g2/).
- To edit a stackup with a GUI, use this package's `stackupEditor` command (a
  separate copy of setupEM's editor, reading and writing through this
  package's own reader).

## 4. Writing a model script

Start from the example closest to what the user wants (same port type and
count, similar structure), not from scratch:

| Use case | Example |
|---|---|
| Thru line, via ports, one excitation (symmetry assumed) | [`workflow/run_line_viaport.py`](workflow/run_line_viaport.py) |
| Thru line, full 2-port | [`workflow/run_line_full2port.py`](workflow/run_line_full2port.py) |
| Any number of ports, full S-matrix | [`workflow/run_generic_nport.py`](workflow/run_generic_nport.py) |
| Inductor, 1-port differential / 2-port | [`workflow/run_inductor_diffport.py`](workflow/run_inductor_diffport.py), [`workflow/run_inductor_2port.py`](workflow/run_inductor_2port.py) |
| Composite GSG ports | [`workflow/run_line_GSG_complex.py`](workflow/run_line_GSG_complex.py) |
| MIM capacitor with via array merging | [`workflow/run_rfcmim_2port_full.py`](workflow/run_rfcmim_2port_full.py) |
| Field dumps | [`workflow/run_line_viaport_fielddump.py`](workflow/run_line_viaport_fielddump.py) |
| Antenna with far field (NF2FF) | [`workflow/run_dual_dipole.py`](workflow/run_dual_dipole.py) |
| Inductor compared to measurement | [`more_examples/measured_vs_simulated/more_accurate_models_L6n2/`](more_examples/measured_vs_simulated/more_accurate_models_L6n2/) |

The examples use the `settings = {}` dictionary; scripts with loose top-level
variables (the older style) are still supported. Use the dictionary for new
scripts.

### Template

This is a complete model script for any number of ports, based on
`run_generic_nport.py`. Every value marked `# ASK` is design intent: get it
from the user, don't invent it.

```python
import os
import numpy as np
from openEMS import openEMS
from gds2openEMS import *    # stackup_reader, gds_reader, simulation_setup, utilities

gds_filename = "my_layout.gds"    # ASK
XML_filename = "SG13G2.xml"       # an openEMS stackup, copied next to the script

settings = {}
settings['preview_only'] = False  # True: show the AppCSXCAD preview and stop
settings['no_gui'] = True         # no preview window: required for unattended runs
settings['merge_polygon_size'] = 0  # via array merging distance in um, 0 = off (see below)

script_path = utilities.get_script_path(__file__)
model_basename = utilities.get_basename(__file__)
sim_path = utilities.create_sim_path(script_path, model_basename)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

settings['unit'] = 1e-6           # GDSII coordinates are in microns
settings['margin'] = 50           # um, dielectric oversize around the layout
settings['fstart'] = 0            # Hz    # ASK
settings['fstop'] = 50e9          # Hz    # ASK
settings['numfreq'] = 401         # output points, free in FDTD
settings['refined_cellsize'] = 1  # um, mesh size at conductor edges
settings['cells_per_wavelength'] = 20
settings['Boundaries'] = ['PEC', 'PEC', 'PEC', 'PEC', 'PEC', 'PEC']   # ASK: absorbing for radiating structures
settings['energy_limit'] = -40    # dB, end criterion of the time-domain run

simulation_ports = simulation_setup.all_simulation_ports()
# via port between two metals, polygon on GDS layer 201
simulation_ports.add_port(simulation_setup.simulation_port(
    portnumber=1, voltage=1, port_Z0=50, source_layernum=201,
    from_layername='Metal1', to_layername='TopMetal2', direction='z'))
# in-plane port on one metal, rectangle on GDS layer 202
simulation_ports.add_port(simulation_setup.simulation_port(
    portnumber=2, voltage=1, port_Z0=50, source_layernum=202,
    target_layername='TopMetal2', direction='x'))

materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate(XML_filename)
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)
allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0],
                                  metals_list=metals_list,
                                  merge_polygon_size=settings['merge_polygon_size'])

# FDTD object: end criterion, excitation pulse and boundaries are openEMS settings
FDTD = openEMS(EndCriteria=np.exp(settings['energy_limit']/10 * np.log(10)))
FDTD.SetGaussExcite((settings['fstart']+settings['fstop'])/2, (settings['fstop']-settings['fstart'])/2)
FDTD.SetBoundaryCond(settings['Boundaries'])

settings['simulation_ports'] = simulation_ports
settings['materials_list'] = materials_list
settings['dielectrics_list'] = dielectrics_list
settings['metals_list'] = metals_list
settings['layernumbers'] = layernumbers
settings['allpolygons'] = allpolygons
settings['sim_path'] = sim_path
settings['model_basename'] = model_basename

# one FDTD run per excited port (ports with voltage=0 are skipped)
for excite_portnumbers in simulation_ports.all_active_excitations():
    settings['excite_portnumbers'] = excite_portnumbers
    simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)   # named parameters!
    simulation_setup.runSimulation(FDTD=FDTD, settings=settings)

if not settings['preview_only']:
    num_ports = simulation_ports.portcount
    f = np.linspace(settings['fstart'], settings['fstop'], settings['numfreq'])
    s_params = np.empty((num_ports, num_ports, settings['numfreq']), dtype=object)
    for i in range(1, num_ports + 1):
        for j in range(1, num_ports + 1):
            s_params[i-1, j-1] = utilities.calculate_Sij(i, j, f, sim_path, simulation_ports)
    snp_name = os.path.join(sim_path, model_basename + '.s' + str(num_ports) + 'p')
    utilities.write_snp(s_params, f, snp_name, z0=simulation_ports.get_reference_impedance())
```

`setupSimulation()` and `runSimulation()` must be called with named
parameters (`FDTD=..., settings=...`) when using the settings dictionary.

### Settings

Settings keys are case-insensitive (`numthreads` works like `numThreads`).

Required: `unit`, `margin`, `fstart`, `fstop`, `numfreq`, `refined_cellsize`,
`cells_per_wavelength` (or `max_cellsize`), plus `Boundaries` and
`energy_limit`, which the script passes to the `openEMS` object. Optional keys
and defaults (from `util_simulation_setup.py`; check there for the current
list):

| Key | Default | Meaning |
|---|---|---|
| `preview_only` | `False` | Show the AppCSXCAD preview and stop without simulating |
| `no_gui` | `False` | Never show AppCSXCAD; simulate right away |
| `force_simulation` | `False` | Simulate even if the model is unchanged (see below) |
| `max_cellsize` | calculated | Maximum cell size, only used if it can't be calculated from `fstop`, `unit` and `cells_per_wavelength` |
| `merge_polygon_size` | `0` | Via array merging distance in µm, passed to `read_gds()` |
| `fill_factor_correction` | `False` | Scale the conductivity of merged via arrays by their fill factor |
| `air_around` | `0` | Extra air around the model in addition to `margin`, one value or 6 values |
| `numThreads` | `0` (automatic) | Force the openEMS thread count |
| `field_dumps` | none | An `all_field_dumps()` object, see "Field dumps" in the user's guide |
| `easyMesh` | `False` | Use the easyMesh4openEMS mesher (separate package) |
| `z_mesh_function` | `create_z_mesh` | `util_meshlines.create_z_mesh_legacy` reproduces the z mesh before 28-Sep-2026 |

Boundaries (`xmin, xmax, ymin, ymax, zmin, zmax`): `'PEC'`, `'PMC'` (symmetry
plane), `'MUR'` (absorbing), `'PML_8'` (better absorbing, much slower).
Radiating structures and antennas need absorbing boundaries with enough
distance; shielded structures can use `PEC`.

### Ports

- Each port uses its own GDS layer (`source_layernum`), not used by the
  stackup. Add `simulation_ports.portlayers` to `layernumbers` before
  `read_gds()`, or the port shapes are not read.
- **Via port** (vertical): `from_layername` and `to_layername`, `direction='z'`
  or `'-z'`.
- **In-plane port**: `target_layername`, `direction='x'`, `'-x'`, `'y'` or
  `'-y'`.
- The sign of `direction` sets the polarity. `port_Z0` is the port reference
  impedance.
- **`voltage=0` only skips a port's run if the script builds its excitation
  list with `simulation_ports.all_active_excitations()`**, as the template
  does. Many examples hardcode the list (e.g. `[1]` or `[[1], [2]]`); there,
  remove the port number from the list yourself.
- S-parameters of a port that was never excited are not available.
  `write_snp()` raises an error naming them rather than writing a broken
  file. `run_line_viaport.py` excites only port 1 and copies S11/S21 to
  S22/S12, assuming a symmetric structure: only do that if the structure
  really is symmetric.
- Composite ports (e.g. GSG) are made from several ports and combined in the
  script's own post-processing: see `run_line_GSG_complex.py`.
- Lumped ports add some series inductance. `python scripts/deembed_openEMS.py result.s2p`
  writes a `_deembedded` file with an estimate of it removed (not for
  composite ports).

### Via arrays

`merge_polygon_size > 0` merges vias on `Type="via"` layers that are closer
than this distance (µm) into one polygon. It never connects vias that land on
different metal shapes above or below (gds2openEMS 0.5.1 and newer). Merging
fills the gaps with via metal, which overstates the via conductance: set
`settings['fill_factor_correction'] = True` to correct it. If the GDSII file
already contains merged vias (e.g. from gds_prepare_for_EM), the original vias
are gone and no correction is possible.

## 5. Running

- `python model.py` builds the model, shows the AppCSXCAD preview (unless
  `no_gui`), runs one FDTD simulation per excitation, and writes the `.sNp`
  file. With `preview_only = True`, it stops after the preview.
- **Results are reused**: `runSimulation()` stores a hash of the model and of
  the script up to the `runSimulation()` call. If nothing changed, it skips
  the solver ("Data for this model already exists, skipping simulation!").
  Changes to the post-processing code below the call don't trigger a new run.
  Use `settings['force_simulation'] = True` to simulate anyway.
- Output: `output/<model>_data/` next to the script, with one `sub-<n>/`
  folder per excitation (port data, field dumps) and the `.sNp` file. If that
  path is too long on Windows (over 200 characters) or can't be created, the
  output goes to an `openEMS` folder in the system TEMP directory instead.
- For unattended runs, set `no_gui = True` and use `python -u`, or the output
  is buffered and a log file stays empty until the end.
- Run time grows with the cell count and with the number of time steps. Long
  runs come from very small cells (check the smallest z cell, set by the
  thinnest layer used), high-Q resonances, and `PML_8` boundaries.

## 6. Results

- The script writes the Touchstone file itself with `utilities.write_snp()`.
  There is no separate conversion step.
- Plot with [plot_snp](https://github.com/VolkerMuehlhaus/plot_snp)
  (`python plot_snp.py result.s2p S11 S21`), or with scikit-rf and matplotlib.
  For scripted runs use the `Agg` backend and `savefig()`, not `plt.show()`;
  most examples end with `plt.show()`, which blocks an unattended run.
- Field dumps (`vtk` or `hdf5`) open in ParaView or AppCSXCAD.
- **Ripple in the results** usually means the time-domain signal had not
  decayed (`energy_limit` not low enough) or reflections from the boundary
  (too little `margin`/`air_around`, or `PEC` where an absorbing boundary is
  needed).
- Check convergence by comparing two `refined_cellsize` values. A starting
  point is 1/5 to 1/10 of the smallest critical width or gap.

## 7. Ask the user, don't decide

These are design decisions that the files can't tell you:

- Frequency range, and whether field dumps or far-field data are needed.
- Which GDS layers hold the ports, port type (via or in-plane), which metals
  they connect, polarity and reference impedance; which ports to excite (full
  S-matrix or one column); whether the structure is symmetric.
- Which stackup file (technology, substrate or not, backside metal) and
  whether variables need overrides.
- Boundary conditions: shielded (`PEC`) or radiating (absorbing).
- Accuracy versus run time (`refined_cellsize`, `energy_limit`).

## 8. Common mistakes

| Symptom | Cause |
|---|---|
| Unattended run "hangs" | AppCSXCAD preview or `plt.show()` window waiting: set `no_gui` and save plots instead |
| No output in a log file for a long time | Python buffers stdout: use `python -u` |
| Solver skipped although the user expects a new run | Unchanged model: the hash check reuses the results; `force_simulation` |
| Wrong results or errors with a stackup that "should work" | A gds2palace stackup used with gds2openEMS |
| Port missing or at the wrong place | Port layer not in `layernumbers`, or wrong `source_layernum` |
| Error about missing S-parameters | A port was not excited (voltage 0, or left out of a hardcoded list) |
| Field dump covers the whole layout | Dump layer not read: `layernumbers.extend(field_dumps.dumplayers)` before `read_gds()` |
| Ripple in the S-parameters | `energy_limit` too high, or boundary reflections |
| Very slow run | Tiny cells from thin layers or a too fine `refined_cellsize`, or `PML_8` boundaries |
| "Unused primitive (type: LinPoly)" warnings | Touching polygons on one layer; harmless |

## 9. Related tools

| Tool | Use |
|---|---|
| [gds2palace](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2) (`pip install gds2palace`) | The same kind of workflow for the AWS Palace FEM solver (and Elmer FEM, including thermal). Similar model script, but **its own stackup files** |
| [setupEM / setupThermal](https://github.com/VolkerMuehlhaus/setupEM) | GUI that builds and runs **gds2palace** models without writing Python; it doesn't create openEMS models |
| [gds_prepare_for_EM](https://github.com/VolkerMuehlhaus/gds_prepare_for_EM) (`pip install gds_prepare_for_EM`) | Simplifies tape-out GDSII before EM simulation: removes dummy fill and small cutouts, merges via arrays safely, replaces round pads |
| [plot_snp](https://github.com/VolkerMuehlhaus/plot_snp) | Plots Touchstone files: dB, phase, Smith chart |
| [KLayout](https://www.klayout.de/) | Viewing and editing GDSII, measuring the layout, drawing port shapes |

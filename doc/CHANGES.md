# Change list

This is an (incomplete) list of changes and new features.

## 22-Sep-2026

The [hash-based skip](userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md#re-running-a-model-the-hash-based-skip) in `runSimulation()` now also hashes the calling model script itself (up to and including the `runSimulation()` call), not just the generated CSX file. This catches changes to solver-runtime settings like `numThreads` or `EndCriteria` that never end up in the CSX file and were previously missed, causing stale results to be silently reused. Code after the call (post-processing, plotting, ...) is still excluded from the hash, so editing that still doesn't force a re-solve. Existing `simulation_model.hash` files from before this change will mismatch once, forcing one re-simulation per cached result.

## 12-Sep-2026

Added two reserved stackup materials that need no `<Materials>` entry: `PEC` (ideal conductor, on conductor/via/sheet Layers, modeled with `CSX.AddMetal`) and `AIR` (built-in default dielectric, overridable). Also supported in the Stackup Editor (`stackup_editor/`).

Ported the Stackup Editor's Layers-tab column-header click-to-sort (Name alphabetically, Zmin/Zmax resulting position largest-first) from setupEM, closing a gap since this repo's editor was forked off.

## 03-Sep-2026

Added a graphical **Stackup XML Editor** (`pip install gds2openEMS` now also installs a `stackupEditor` console command). Covers Variables, Materials, the Dielectric stack, drawn Layers, Reference-relative positioning, Derived Layers, and Thermal Tables, with a live cross-section preview, undo, and an "Import from ADS Momentum" option (`*.subst`/`*.ltd`). `PySide6` is now a dependency of `gds2openEMS`.

This is a port of the equivalent editor from the sibling `gds2palace_ihp_sg13g2`/`setupEM` project, re-pointed at this repo's own `util_stackup_reader.py` (identical XML schema, independently-maintained reader) - a new top-level `stackup_editor/` package, not shared/symlinked with setupEM's original per this workspace's usual convention for these sibling repos.

## 02-Sep-2026

New user's guide, v3

Migrated all 10 `workflow/run_*.py` examples to the `settings{}` dictionary syntax and the `gds2openEMS` PyPI package (`from gds2openEMS import *`), instead of loose top-level variables and a local `modules/` copy. Behavior is unchanged.

This was really two separate things that had gotten tangled together: which code you use (a local `modules/` copy vs. `pip install gds2openEMS`) and which coding style you use (loose variables vs. `settings{}`). They're independent. README.md now documents them as two separate choices.

Removed the `postprocess_only` switch from all example model scripts. It's no longer needed: `runSimulation()` already skips the FDTD solve automatically via a content hash of the model. If the model hasn't changed since the last run, it just reuses the existing result. 

Added `more_examples/local_modules_copy/`, a fully self-contained example (its own `modules/` copy, GDSII layout, and XML stackup) demonstrating the local-copy distribution method on its own. 

`util_simulation_setup.py` module load `import shapely` now fails with a clear error message if shapely module is missing. 

`voltage=0` ports are now actually skipped in scripts that build their excitation list from `simulation_ports.all_active_excitations()`, saving simulation time instead of wasting it. Referencing a never-excited port's S-parameters now fails with a clear error instead of crashing.

Added `scripts/sync_local_modules_copy.py`, so `more_examples/local_modules_copy/modules/` (used to demonstrate the local `modules` folder method) doesn't silently drift out of sync with the canonical source. Run it whenever `workflow/modules/` changes.


## 01-Sep-2026
Fixed a crash in `resolve_derived_layers()`: `gdspy.boolean()` raises `IndexError` when called with an empty operand (e.g. a resistor recognition layer with no polygons in the current cell), which previously aborted the whole GDSII read. The boolean fold now short-circuits using the OR/AND/NOT identity instead whenever either operand is empty. Same fix applied to gds2palace_ihp_sg13g2's independent copy of this reader.

Added a new example, `more_examples/parameterized_XML_stackup`, showing how to override stackup `<Variable>`s (`total_thickness`, `air_thickness`) from a model script via `read_substrate(variable_overrides=...)`, in both the loose top-level variable style and the `settings{}` dictionary style.

## 20-Aug-2026
Corrected a license inconsistency: the repository's LICENSE file said Apache-2.0, while every source file's own header comment already said GPLv3. The code headers were correct — this workflow directly imports and drives the GPLv3-licensed openEMS solver object in-process, with no linking exception covering that use, so GPLv3 is the license actually required here. LICENSE, `pyproject.toml`, and the remaining files that were missing a header now all agree on GPLv3.

The `gds2openEMS` PyPI package can now be built directly with `python -m build` from this repository (`pyproject.toml` at the repo root, publishing `workflow/modules/` under the `gds2openEMS` name), instead of maintaining a separate manually-synced copy.

Fixed `write_snp()` writing a hardcoded 50 Ohm reference impedance into the Touchstone (`*.snp`) file header regardless of the actual port impedance used in the simulation. All model scripts now pass the real port reference impedance from `simulation_ports`, so the header correctly reflects non-50 Ohm setups (e.g. differential/GSG ports).

## 13-18-Aug-2026
Added support for derived layers in the stackup XML format, with a new IHP resistor example under `more_examples`.

The stackup reader (`util_stackup_reader.py`) now supports a `<Variables>` block and `=`-prefixed expressions, ported from gds2palace_ihp_sg13g2's reader to keep the two independent copies in sync. This allows a stackup XML file to define named values that other attributes can reference, instead of repeating the same physical value in multiple places.

Keyhole/hole polygons are now split before CSXCAD extrusion, fixing incorrect geometry for layers with holes. This requires the `shapely` package, now a documented dependency.

## 12-Jul-2026
Added `calculate_Zij()` for multiport Z-parameter extraction (previously only available for 2-port).

## 19-Jun-2026
New `numThreads` workflow option to force the number of openEMS solver threads, instead of relying on automatic thread count detection. Two examples are provided in the `more_examples` folder.

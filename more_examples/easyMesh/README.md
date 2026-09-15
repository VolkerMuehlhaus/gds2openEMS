# easyMesh4openEMS Meshing

`openEMS_generic_nport_MA.py` swaps gds2openEMS's own default meshing for the
third-party [easyMesh4openEMS](https://github.com/MustafaAlchalabi/easyMesh4openEMS)
module, enabled with one setting:

```python
settings['easyMesh'] = True
```

Two other things this example demonstrates, independent of the meshing choice:

- **The modern `settings{}` dict script style** (one dictionary passed to
  `setupSimulation()`/`runSimulation()` as a single named argument), rather
  than the classic loose top-level variables used by `local_modules_copy`
  and `combine_layout_sources` - see `workflow/run_generic_nport.py` for
  where this style comes from.
- **A fully generic n-port sweep and Touchstone export**: it loops over
  `simulation_ports.all_active_excitations()` and writes a full `S_ij`
  matrix (`utilities.write_snp()`) for however many ports are defined,
  instead of hand-writing a 2-port S2P as the other line examples do.

Model geometry is the same simple 2-port via-port line
(`line_simple_viaport.gds`) used by `combine_layout_sources` and
`local_modules_copy`, read against the same reduced, substrate-free
`SG13G2_nosub.xml` stackup, and installs gds2openEMS as a normal PyPI
package (`from gds2openEMS import *`) rather than a local `modules/` copy.

Requires the `easyMesh4openEMS` PyPI package in addition to `gds2openEMS`
itself (`pip install easyMesh4openEMS`).

## See also

- [`../local_modules_copy`](../local_modules_copy) - same base line model
  and classic script style, using a local `modules/` copy instead of the
  PyPI package.
- [`../combine_layout_sources`](../combine_layout_sources) - same base line
  model, demonstrating mixing GDS geometry with native openEMS/STL shapes.
- [easyMesh4openEMS](https://github.com/MustafaAlchalabi/easyMesh4openEMS) -
  the meshing module itself.

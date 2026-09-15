# Using a Local `modules/` Copy (No PyPI Install Needed)

Every other example imports gds2openEMS as an installed package
(`from gds2openEMS import *`). This one instead ships its own copy of the
reader/utility modules in [`modules/`](modules/) and imports them directly:

```python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'modules')))
import modules.util_stackup_reader as stackup_reader
import modules.util_gds_reader as gds_reader
import modules.util_utilities as utilities
import modules.util_simulation_setup as simulation_setup
import modules.util_meshlines as util_meshlines
```

That makes this folder fully self-contained - GDS, XML stackup and the
gds2openEMS code itself all live right here, so `run_line_viaport.py` runs
with nothing more than `pip install openEMS CSXCAD` (no `pip install
gds2openEMS` required). This is a distribution/import-style choice,
independent of the loose-variable-vs-`settings{}` coding style question -
this example pairs it with the classic loose top-level variables, matching
how it's traditionally shown.

`modules/` here is a **manual copy** of this repo's own `workflow/modules/`
- there is no symlink or build step keeping it in sync, so a fix made
upstream won't automatically show up here.

The model itself is the same 2-port via-port line as
`workflow/run_line_viaport.py` (a via port between `Metal1` and `TopMetal2`
at each end, S2P output built by assuming reverse-path symmetry rather than
exciting both ports), read against the reduced, substrate-free
`SG13G2_nosub.xml` stackup so plain `PEC` boundaries can be used directly.

## See also

- [`../easyMesh`](../easyMesh) - same base line model, using the installed
  PyPI package and the `settings{}` dict style instead.
- [`../combine_layout_sources`](../combine_layout_sources) - same base line
  model, demonstrating mixing GDS geometry with native openEMS/STL shapes.
- `workflow/run_line_viaport.py` - the original version of this model.

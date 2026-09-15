# Combining Multiple Geometry Sources

`run_combine_example.py` builds one openEMS model from **four different
geometry sources at once**, to show which ones participate in gds2openEMS's
automatic meshing and which don't:

| Source | Added via | Auto-meshed? |
|---|---|---|
| GDSII layout (`line_simple_viaport.gds`) | `gds_reader.read_gds()` → `allpolygons` | Yes |
| Extra rectangle/polygon added in code | `allpolygons.add_rectangle()` / `allpolygons.add_polygon()` | Yes - same `allpolygons` object |
| A plain PEC box, native openEMS API | `CSX.AddMetal('patch').AddBox(...)` | **No** |
| An STL shape | `CSX.AddMetal('Metal').AddPolyhedronReader('example.stl')` | **No** |

The key takeaway: **only what's inside `allpolygons` when
`simulation_setup.setupSimulation()` runs gets automatic mesh refinement.**
`add_rectangle()`/`add_polygon()` calls made *before* that call join the same
GDS-derived data structure and get meshed along with it - shown here adding a
ground plane rectangle on `Metal5` and a polygon on `Metal3`. Anything added
*after* `setupSimulation()` via raw openEMS/CSXCAD calls (the PEC box, the
STL polyhedron) is invisible to that automatic mesh and needs its own manual
mesh lines (`mesh.AddLine(...)`, commented out here as a reminder) - or it
may end up under-resolved or missing from the simulation entirely.

The PEC box also demonstrates **priority**: `setupSimulation()`'s own
geometry uses priority 200 (metals) and 10 (dielectrics), so the box use
priority 210 to make sure it displaces the dielectric it sits inside of
rather than being hidden by it.

Model geometry is the same simple 2-port via-port line
(`line_simple_viaport.gds`) used by the `local_modules_copy` and `easyMesh`
examples, read against the reduced, substrate-free `SG13G2_nosub.xml`
stackup (real silicon substrate/backside-ground replaced by a thin PEC-backed
spacer, so plain `PEC` boundaries work directly without a lossy backing
material to absorb).

## See also

- [`../local_modules_copy`](../local_modules_copy) - same base line model,
  demonstrating the local `modules/` folder distribution style instead.
- [`../easyMesh`](../easyMesh) - same base line model, demonstrating the
  `settings{}` dict script style and the easyMesh4openEMS meshing module.
- openEMS's own Python API docs for `AddBox`/`AddPolyhedronReader`/
  `AddLine` if you want to add more native-API geometry of your own.

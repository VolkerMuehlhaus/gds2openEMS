# Loose-variable openEMS model in the style of the gds2openEMS examples (2024), for
# gds2openEMS.convert2settings tests. Runs against the stand-in modules folder.
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'modules')))

import modules.util_stackup_reader as stackup_reader
import modules.util_gds_reader as gds_reader
import modules.util_utilities as utilities
import modules.util_simulation_setup as simulation_setup
import modules.util_meshlines as util_meshlines

from openEMS import openEMS
import numpy as np

# preview model/mesh only?
preview_only = True
postprocess_only = False

gds_filename = "line.gds"   # geometries
XML_filename = "stack.xml"  # stackup

preprocess_gds = False
merge_polygon_size = 0.5

script_path = utilities.get_script_path(__file__)
model_basename = utilities.get_basename(__file__)
sim_path = utilities.create_sim_path (script_path,model_basename)

unit   = 1e-6  # geometry is in microns
margin = 50    # distance in microns from GDSII geometry boundary to simulation boundary

fstart =  0e9
fstop  = 110e9
numfreq = 401

refined_cellsize = 1  # mesh cell size in conductor region

Boundaries = ['PEC', 'PEC', 'PEC', 'PEC', 'PEC', 'PEC']

cells_per_wavelength = 20   # how many mesh cells per wavelength, must be 10 or more
energy_limit = -40          # end criteria for residual energy (dB)

simulation_ports = simulation_setup.all_simulation_ports()
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=1, voltage=1, port_Z0=50, source_layernum=201, target_layername='TopMetal2', direction='x'))
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=2, voltage=1, port_Z0=50, source_layernum=202, target_layername='TopMetal2', direction='-x'))

materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate (XML_filename)
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)

allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0], metals_list=metals_list, preprocess=preprocess_gds, merge_polygon_size=merge_polygon_size)

wavelength_air = 3e8/fstop / unit
max_cellsize = (wavelength_air)/(np.sqrt(materials_list.eps_max)*cells_per_wavelength)

FDTD = openEMS(EndCriteria=np.exp(energy_limit/10 * np.log(10)))
FDTD.SetGaussExcite( (fstart+fstop)/2, (fstop-fstart)/2 )
FDTD.SetBoundaryCond( Boundaries )


def describe():
    # reads module variables from inside a function
    return f'margin {margin} um, {numfreq} points'


print(describe())

for port in simulation_ports.ports:
    simulation_setup.setupSimulation   ([port.portnumber],
                                        simulation_ports,
                                        FDTD,
                                        materials_list,
                                        dielectrics_list,
                                        metals_list,
                                        allpolygons,
                                        max_cellsize,     # from the formula above
                                        refined_cellsize,
                                        margin,
                                        unit,
                                        xy_mesh_function=util_meshlines.create_xy_mesh_from_polygons)

    simulation_setup.runSimulation  ([port.portnumber],
                                        FDTD,
                                        sim_path,
                                        model_basename,
                                        preview_only,
                                        postprocess_only)

f = np.linspace(fstart,fstop,numfreq)
print("points", len(f), "preview", preview_only)

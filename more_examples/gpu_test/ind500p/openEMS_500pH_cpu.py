import os
import sys

from gds2openEMS import *

from openEMS import openEMS
import numpy as np
import matplotlib.pyplot as plt

settings = {}

# Model comments
# Simple inductor model, 2 port model with two via ports to substrate, full two port simulation


# ======================== workflow settings ================================

settings['preview_only'] = False  # preview model/mesh only?
settings['postprocess_only'] = False # postprocess existing data without re-running simulation?
settings['no_gui'] = False # if set to True, there is no mesh/model preview in AppCSXCAD, and simulation starts immediately. 


# ===================== input files and path settings =======================

gds_filename = "OctaDiffTap_0n50_ports.gds"      # geometries
XML_filename = "SG13G2_200um.xml"               # stackup

# preprocess GDSII for safe handling of cutouts/holes?
settings['preprocess_gds'] = False

# merge via polygons with distance less than .. um, set 0 to disable via merging
settings['merge_polygon_size'] = 1.0

# get path for this simulation file
script_path = utilities.get_script_path(__file__)

# use script filename as model basename
model_basename = utilities.get_basename(__file__)

# set and create directory for simulation output
sim_path = utilities.create_sim_path (script_path,model_basename)
print('Simulation data directory: ', sim_path)

# change current path to model script path
os.chdir(os.path.dirname(os.path.abspath(__file__)))


# ======================== simulation settings ================================

settings['unit']   = 1e-6   # geometry is in microns
settings['margin'] = 70    # distance in microns from GDSII geometry boundary to simulation boundary 

settings['fstart'] = 0
settings['fstop']  = 100e9
settings['numfreq'] = 401

settings['refined_cellsize'] = 1.0  # mesh cell size in conductor region

# choices for boundary: 
# 'PEC' : perfect electric conductor (default)
# 'PMC' : perfect magnetic conductor, useful for symmetries
# 'MUR' : simple MUR absorbing boundary conditions
# 'PML_8' : PML absorbing boundary conditions
settings['Boundaries'] = ['PEC', 'PEC', 'PEC', 'PEC', 'PEC', 'PEC']

settings['cells_per_wavelength'] = 20   # how many mesh cells per wavelength, must be 10 or more
settings['energy_limit'] = -50          # end criteria for residual energy (dB)

# ports from GDSII Data, polygon geometry from specified special layer
# note that for multiport simulation, excitations are switched on/off in simulation_setup.createSimulation below
simulation_ports = simulation_setup.all_simulation_ports()
# instead of in-plane port specified with target_layername, we here use via port specified with from_layername and to_layername
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=1, voltage=1.0, port_Z0=50.0, source_layernum=201, from_layername='Metal1', to_layername='TopMetal2', direction='z'))
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=2, voltage=1.0, port_Z0=50.0, source_layernum=202, from_layername='Metal1', to_layername='TopMetal2', direction='z'))

# ======================== simulation ================================

# get technology stackup data
materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate (XML_filename)
# get list of layers from technology
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)

# read geometries from GDSII, only purpose 0
allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0], metals_list=metals_list, preprocess=settings['preprocess_gds'], merge_polygon_size=settings['merge_polygon_size'])


# calculate maximum cellsize from wavelength in dielectric
# max_cellsize is calculated by setupSimulation from settings['fstop'], settings['unit'] and settings['cells_per_wavelength']


########### create model, run and post-process ###########

FDTD = openEMS(EndCriteria=np.exp(settings['energy_limit']/10 * np.log(10)))
FDTD.SetGaussExcite( (settings['fstart']+settings['fstop'])/2, (settings['fstop']-settings['fstart'])/2 )
FDTD.SetBoundaryCond( settings['Boundaries'] )


########### create model, run and post-process ###########

# run all port excitations, one after another

for port in simulation_ports.ports:
    settings['excite_portnumbers'] = [port.portnumber]
    settings['simulation_ports'] = simulation_ports
    settings['materials_list'] = materials_list
    settings['dielectrics_list'] = dielectrics_list
    settings['metals_list'] = metals_list
    settings['allpolygons'] = allpolygons
    settings['xy_mesh_function'] = util_meshlines.create_xy_mesh_from_polygons
    simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)
    
    settings['excite_portnumbers'] = [port.portnumber]
    settings['sim_path'] = sim_path
    settings['model_basename'] = model_basename
    simulation_setup.runSimulation(FDTD=FDTD, settings=settings)


# Initialize an empty matrix for S-parameters
num_ports = simulation_ports.portcount
s_params = np.empty((num_ports, num_ports, settings['numfreq']), dtype=object)

# Define frequency resolution. Due to FFT from Empire time domain results, 
# this is postprocessing and we can change it again at any time.
f = np.linspace(settings['fstart'],settings['fstop'],settings['numfreq'])

# Populate the S-parameter matrix with simulation results
for i in range(1, num_ports + 1):
    for j in range(1, num_ports + 1):
        s_params[i-1, j-1] = utilities.calculate_Sij(i, j, f, sim_path, simulation_ports)

# Write to Touchstone *.snp file
snp_name = os.path.join(sim_path, model_basename + '.s' + str(num_ports) + 'p')
utilities.write_snp(s_params, f, snp_name)

print('Created S-parameter output file at ', snp_name)
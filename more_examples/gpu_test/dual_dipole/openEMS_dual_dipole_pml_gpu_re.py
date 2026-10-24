import os
import sys

from gds2openEMS import *

from openEMS import openEMS
import numpy as np
import matplotlib.pyplot as plt

settings = {}

# Model comments
#
# Dual dipole 245 GHz, design by IHP Klaus Schmalz
# Port defined in GDSIIfile on layer 201
# S11 only, no nf2ff box: resonance estimation needs a model without field dumps


# ======================== workflow settings ================================

# preview model/mesh only?
# postprocess existing data without re-running simulation?
settings['preview_only'] = False
settings['postprocess_only'] = False

# ===================== input files and path settings =======================

gds_filename = "dipole_port_sg13.gds"   # geometries
XML_filename = "SG13G2_200um_backsideGND.xml"       # stackup

# preprocess GDSII for safe handling of cutouts/holes?
settings['preprocess_gds'] = True

# merge via polygons with distance less than .. microns, set to 0 to disable via merging.
settings['merge_polygon_size'] = 0

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

settings['unit'] = 1e-6   # geometry dimensions and all lengths unit is ?m (micrometer)
settings['margin'] = 100    # distance in microns from GDSII geometry boundary to chip boundary 

settings['fstart'] = 200e9
settings['fstop']  = 300e9
settings['numfreq'] = 401


settings['refined_cellsize'] = 2.5  # mesh cell size in conductor region

settings['engine'] = 'gpu'
settings['resonance_estimation'] = True   # stop when the extrapolated S11 has converged
settings['no_gui'] = True             # no AppCSXCAD preview (batch run)
settings['force_simulation'] = True   # always re-run, no cached results

# choices for boundary: 
# 'PEC' : perfect electric conductor (default)
# 'PMC' : perfect magnetic conductor, useful for symmetries
# 'MUR' : simple MUR absorbing boundary conditions
# 'PML_8' : PML absorbing boundary conditions
settings['Boundaries'] = ['PML_8', 'PML_8', 'PML_8', 'PML_8', 'PML_8', 'PML_8']

settings['cells_per_wavelength'] = 12   # how many mesh cells per wavelength, must be 10 or more
settings['energy_limit'] = -60          # end criteria for residual energy (dB), safety limit for resonance estimation

# ports from GDSII Data, polygon geometry from specified special layer
# note that for multiport simulation, excitations are switched on/off in simulation_setup.createSimulation below
simulation_ports = simulation_setup.all_simulation_ports()
simulation_ports.add_port(simulation_setup.simulation_port(portnumber=1, voltage=1, port_Z0=50, source_layernum=201, target_layername='TopMetal2', direction='x'))

# ======================== simulation ================================

# get technology stackup data
materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate (XML_filename)
# get list of layers from technology
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)

# read geometries from GDSII, only purpose 0
allpolygons = gds_reader.read_gds(gds_filename, layernumbers, purposelist=[0], metals_list=metals_list, preprocess=settings['preprocess_gds'], merge_polygon_size=settings['merge_polygon_size'])

# calculate maximum cellsize from wavelength in dielectric
wavelength_air = 3e8/settings['fstop'] / settings['unit']
max_cellsize = (wavelength_air)/(np.sqrt(materials_list.eps_max)*settings['cells_per_wavelength']) 


########### create model, run and post-process ###########

# Prepare simulation for port 1 excitation
settings['excite_portnumbers'] = [1]  # list of ports that are excited for this simulation run
FDTD = openEMS(EndCriteria=np.exp(settings['energy_limit']/10 * np.log(10)))
FDTD.SetGaussExcite( (settings['fstart']+settings['fstop'])/2, (settings['fstop']-settings['fstart'])/2 )
FDTD.SetBoundaryCond( settings['Boundaries'] )

settings['simulation_ports'] = simulation_ports
settings['materials_list'] = materials_list
settings['dielectrics_list'] = dielectrics_list
settings['metals_list'] = metals_list
settings['allpolygons'] = allpolygons
settings['xy_mesh_function'] = util_meshlines.create_xy_mesh_from_polygons
settings['air_around'] = 0.5*wavelength_air
FDTD = simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)

# run simulation
settings['sim_path'] = sim_path
settings['model_basename'] = model_basename
sub1_data_path = simulation_setup.runSimulation(FDTD=FDTD, settings=settings)

# definition of some utility functions
def dB(value, factor=20):
    return factor*np.log10(np.abs(value))

# evaluate results for 1-port simulation
if not settings['preview_only']:  
    f = np.linspace(settings['fstart'], settings['fstop'], settings['numfreq'])

    s11 = utilities.calculate_Sij(1, 1, f, sim_path, simulation_ports)
    s11_dB = dB(s11)

    # write Touchstone S1P file
    s1p_name = os.path.join(sim_path, model_basename + '.s1p')
    utilities.write_snp (np.array([s11]),f, s1p_name)

    # plot return loss
    fig, axis = plt.subplots(num="Return Loss", tight_layout=True)
    axis.plot(f/1e9, s11_dB, 'k-', linewidth=2, label='S11 (dB)')
    axis.grid()
    axis.set_xmargin(0)
    axis.set_xlabel('Frequency (GHz)')
    axis.set_title("Return Loss")
    axis.legend()
    
    # show all plots
    plt.show()

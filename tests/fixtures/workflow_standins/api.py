"""Canonical signatures for the workflow calls EMStudio templates use.

Both golden_standins and convert_loose import from here so the two fixtures cannot
drift on argument names / defaults. Recording (STANDIN_RECORD / CONVERT_RECORD) is
added by the callers.
"""


class openEMS:
    """Stand-in for ``from openEMS import openEMS``.

    Only ``EndCriteria`` is accepted — a typo like ``EndCritera=`` must fail.
    """

    def __init__(self, EndCriteria=None):
        self.EndCriteria = EndCriteria

    def SetGaussExcite(self, f0, fc):
        pass

    def SetBoundaryCond(self, BC):
        pass


class simulation_port:
    def __init__(self, portnumber, voltage, port_Z0, source_layernum, target_layername=None,
                 from_layername=None, to_layername=None, direction='x'):
        self.portnumber = portnumber
        self.voltage = voltage
        self.port_Z0 = port_Z0
        self.source_layernum = source_layernum
        self.target_layername = target_layername
        self.from_layername = from_layername
        self.to_layername = to_layername
        self.direction = direction


class all_simulation_ports:
    def __init__(self):
        self.ports = []
        self.portcount = 0
        self.portlayers = []

    def add_port(self, port):
        self.ports.append(port)
        self.portcount = len(self.ports)
        self.portlayers.append(port.source_layernum)

    def all_active_excitations(self):
        return [p for p in self.ports if p.voltage != 0]


class StackupLayers:
    eps_max = 11.9

    def getlayernumbers(self):
        return [8, 10, 30]


def read_substrate(XML_filename, variable_overrides=None):
    return [], [], StackupLayers()


def read_gds(filename, layerlist, purposelist, metals_list, preprocess=False, merge_polygon_size=0,
             mirror=False, offset_x=0, offset_y=0, gds_boundary_layers=None, layernumber_offset=0,
             cellname="", derived_layers=None):
    if gds_boundary_layers is None:
        gds_boundary_layers = []
    return []


def setupSimulation(excite_portnumbers=None, simulation_ports=None, FDTD=None, materials_list=None,
                    dielectrics_list=None, metals_list=None, allpolygons=None, max_cellsize=None,
                    refined_cellsize=None, margin=None, unit=None,
                    z_mesh_function=None, xy_mesh_function=None, air_around=0,
                    field_dumps=False, settings=None, fill_factor_correction=False):
    return FDTD


def runSimulation(excite_portnumbers=None, FDTD=None, sim_path=None, model_basename=None,
                  preview_only=None, postprocess_only=None, force_simulation=False, no_gui=False,
                  numThreads=None, settings=None):
    return None


def create_palace(excite_ports, settings):
    return "config.json", "data_dir"

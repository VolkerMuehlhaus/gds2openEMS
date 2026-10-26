# Test stand-in for gds2openEMS util_simulation_setup.py: the same signatures, settings branch,
# defaults and max_cellsize formula as the real workflow, but instead of meshing it records the
# values it would use (JSON lines into $CONVERT_RECORD).
import json
import os

import numpy as np

try:
    from . import util_meshlines
except ImportError:
    import util_meshlines


def _record(kind, **values):
    path = os.environ.get("CONVERT_RECORD")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"kind": kind, **values}, sort_keys=True, default=repr) + "\n")


def setupSimulation (excite_portnumbers=None,
                     simulation_ports=None,
                     FDTD=None,
                     materials_list=None,
                     dielectrics_list=None,
                     metals_list=None,
                     allpolygons=None,
                     max_cellsize=None,
                     refined_cellsize=None,
                     margin=None,
                     unit=None,
                     z_mesh_function=util_meshlines.create_z_mesh,
                     xy_mesh_function=util_meshlines.create_xy_mesh_from_polygons,
                     air_around=0,
                     field_dumps=False,
                     settings=None,
                     fill_factor_correction=False):
    if dielectrics_list is None:
        if settings is not None:
            excite_portnumbers = settings['excite_portnumbers']
            simulation_ports   = settings['simulation_ports']
            materials_list     = settings['materials_list']
            dielectrics_list   = settings['dielectrics_list']
            metals_list        = settings['metals_list']
            allpolygons        = settings['allpolygons']
            refined_cellsize   = settings['refined_cellsize']
            margin             = settings['margin']
            unit               = settings['unit']
            z_mesh_function    = settings.get('z_mesh_function',util_meshlines.create_z_mesh)
            xy_mesh_function   = settings.get('xy_mesh_function', util_meshlines.create_xy_mesh_from_polygons)
            air_around         = settings.get('air_around', 0)
            field_dumps        = settings.get('field_dumps', False)

            fstop = settings.get('fstop',None)
            unit  = settings.get('unit',None)
            cpw   = settings.get('cells_per_wavelength',None)
            if (fstop is not None) and (unit is not None) and (cpw is not None):
                wavelength_air = 3e8/fstop / unit
                max_cellsize = (wavelength_air)/(np.sqrt(materials_list.eps_max)*cpw)
            else:
                max_cellsize       = settings.get('max_cellsize',None)
                if max_cellsize is None:
                    raise SystemExit('no max_cellsize')
        else:
            raise SystemExit('no settings')

    if settings is not None:
        fill_factor_correction = fill_factor_correction or settings.get('fill_factor_correction', False)

    _record("setup", excite=excite_portnumbers, ports=id(simulation_ports), fdtd=id(FDTD),
            max_cellsize=max_cellsize, refined_cellsize=refined_cellsize, margin=margin, unit=unit,
            z_mesh=getattr(z_mesh_function, "__name__", None),
            xy_mesh=getattr(xy_mesh_function, "__name__", None),
            air_around=air_around, field_dumps=field_dumps, fill=fill_factor_correction)
    return FDTD


def runSimulation (excite_portnumbers=None,
                   FDTD=None,
                   sim_path=None,
                   model_basename=None,
                   preview_only=None,
                   postprocess_only=None,
                   force_simulation=False,
                   no_gui = False,
                   numThreads=None,
                   settings=None):
    if excite_portnumbers is None:
        if settings is not None:
            excite_portnumbers = settings['excite_portnumbers']
            sim_path           = settings['sim_path']
            model_basename     = settings['model_basename']
            preview_only       = settings.get('preview_only',False)
            postprocess_only   = settings.get('postprocess_only','')
            force_simulation   = settings.get('force_simulation', False)
            no_gui             = settings.get('no_gui', False)
            numThreads         = settings.get('numThreads', 0)
        else:
            raise SystemExit('no settings')

    if no_gui:
        preview_only = False
        postprocess_only = False
    if numThreads is None:
        numThreads = 0
    _record("run", excite=excite_portnumbers, fdtd=id(FDTD), sim_path=sim_path,
            model_basename=model_basename, preview_only=bool(preview_only),
            postprocess_only=bool(postprocess_only), force=force_simulation, no_gui=no_gui,
            numThreads=numThreads)
    return os.path.join(sim_path, "excite_" + "_".join(str(p) for p in excite_portnumbers))


# Same port types as workflow_standins.api (golden_standins shares that module).
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
        return [p for p in self.ports if getattr(p, "voltage", 0) != 0]


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

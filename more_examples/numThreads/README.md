# Optional parameter to set fixed number of solver threads

The files provided here demonstrate the new "numThreads" workflow option introduced 19-June-2026:
Before, openEMS was detecting the "best" number of solver threads automatically, which could lead to low number of threads if the computer was busy with other things running in parallel. Now, the number of threads used by openEMS can be forced to a fix value in the model script.  

This parameter is optional and can be set in two different ways, depending on the model syntax that you use. Examples of both cases are included.

## Classic workflow syntax:

A new optional numThreads parameter can be specified in simulation_setup.setupSimulation ()

```python
numThreads = 8  
(...)  
simulation_setup.runSimulation (excite_ports, FDTD, sim_path, model_basename, preview_only, numThreads=numThreads)      
```

This parameter is optional, it defaults to automatic thread detection by openEMS, as known from previous workflow releases.  

```python
simulation_setup.runSimulation (excite_ports, FDTD, sim_path, model_basename, preview_only)    
```


Setting numThreads=0 will also enable automatic thread detection by openEMS, instead of forcing a specific thread count.


## New settings[] model syntax, as also known from the gds2palace workflow:

A new optional numThreads parameter can be specified in the settings[] list

```python
settings['numThreads'] = 8  
(...)  
simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)  
simulation_setup.runSimulation(FDTD=FDTD, settings=settings)    
```

This parameter is optional, it defaults to automatic thread detection by openEMS, as known from previous workflow releases. 


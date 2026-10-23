# Running openEMS on the GPU

## Why a GPU?

openEMS is an FDTD solver. In every timestep it updates the fields in every mesh cell, so the run time grows with the number of cells times the number of timesteps. Antennas, mm-wave structures and anything with a large air box quickly reach millions of cells and hundreds of thousands of timesteps, and the simulation then takes from many minutes to hours.

Each cell update is simple arithmetic on a few numbers, and all cells can be updated at the same time. That is what GPUs are built for: thousands of small cores working on large arrays in parallel.

## What is new

openEMS now has a GPU engine. It runs on Apple GPUs (Metal, macOS) and on AMD and NVIDIA GPUs (HIP). It is not in an openEMS release yet: you have to build openEMS from its current source code. See [Running on the GPU](../../doc/userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md#running-on-the-gpu) in the user's guide.

In the gds2openEMS model script, one line switches to the GPU:

```python
settings['engine'] = 'gpu'
```

Without this line, openEMS uses its CPU engine as before. Nothing else in the model changes.

## What speedup to expect

### hpz2: AMD Ryzen AI Max+ PRO 395 (16 cores, 32 threads), integrated Radeon 8060S GPU, Linux

![GPU speedup over the CPU engine](img/speedup_overview.png)

- The GPU engine was 1.6× to 3.6× faster than the CPU engine on the same machine.
- The gain is largest for big models with PML boundaries, where the CPU engine is slow.
- Small models with simple PEC boundaries gain less.
- The S-parameters and antenna results agree between CPU and GPU. Changing the boundary type changes the results much more than changing the engine.

### Apple M4, macOS

To be added.

## Test models

Each folder has the GDSII file, the stackup, the model scripts for CPU and GPU, and a README with the details:

| Folder | Model |
|---|---|
| [`dual_dipole`](dual_dipole) | Dual dipole antenna at 245 GHz, with PML and with MUR boundaries |
| [`ind500p`](ind500p) | Octagon inductor with center tap, 0–100 GHz |

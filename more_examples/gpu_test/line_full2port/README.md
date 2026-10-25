# Thru line, full 2-port: CPU vs GPU

A simple thru line on TopMetal2, simulated from 20 to 100 GHz with two ports. This is the workflow example [`run_line_full2port.py`](../../../workflow/run_line_full2port.py). The model is small (0.36 M mesh cells) but has PML boundaries.

## Key facts

- The GPU was **3.3× faster** on hpz2, **3.5× faster** on the Apple M4 and **14× faster** on the Windows laptop with its discrete NVIDIA GPU, although the model is small.
- The reason is the PML boundaries: they are slow on the CPU engine.
- CPU and GPU give the same S-parameters.

## Speed

Solve time per excitation (the model runs one excitation per port):

| Machine | CPU engine | GPU engine | GPU speedup |
|---|---|---|---|
| hpz2, Radeon 8060S | 44 s | 13 s | 3.3× |
| Apple M4 | 115 s | 33 s | 3.5× |
| Windows laptop, RTX 3060 | 289 s | 21 s | 14× |

- The GPU engine updates the PML boundaries together with the rest of the model, at full speed.
- The laptop's CPU engine is especially slow with PML, and its GPU is fast, so the gap is largest there.

## Results

![S11 and S21, CPU vs GPU](img/line_full2port_cpu_gpu.png)

The curves of CPU and GPU lie on top of each other (Apple M4 shown). S21 agrees within 0.015 dB, S11 within 0.02 dB in the useful range. On hpz2 and on the laptop, CPU and GPU even gave identical S-parameters, and the same on both machines.

Only at the deepest S11 dip (−38 dB) is the difference larger, 0.12 dB. It comes from where each run stops: the GPU engine checks the end criterion at other timesteps than the CPU engine.

## Model and scripts

| Script | Engine |
|---|---|
| [`openEMS_line_full2port_cpu.py`](openEMS_line_full2port_cpu.py) | CPU (default) |
| [`openEMS_line_full2port_gpu.py`](openEMS_line_full2port_gpu.py) | GPU: `settings['engine'] = 'gpu'` |

That one line is the only difference between the two scripts. Compared to the workflow example, both also set `preview_only = False`, `no_gui = True` and `force_simulation = True` for a batch run. The model files are `line_simple.gds` and the stackup `SG13G2_nosub.xml`. The boundaries are `PML_8` on five sides and PEC below.

## Test details

| | hpz2 | Apple M4 | Windows laptop |
|---|---|---|---|
| CPU | AMD Ryzen AI Max+ PRO 395, 16 cores | Apple M4, 10 cores (4 performance, 6 efficiency) | AMD Ryzen 7 5800H, 8 cores |
| GPU | AMD Radeon 8060S, built-in, HIP | Apple M4, 8 cores, built-in, Metal | NVIDIA RTX 3060 Laptop, 6 GB, HIP |
| Main memory, OS | 107 GB, Linux | 16 GB, macOS 26 | 32 GB, Windows 11 |
| openEMS | v0.37.0-33-g53a4264 | v0.37.0-32-gec4d2db | v0.37.0-38-gd686f1d (Windows test package) |
| GPU speed | 1,807 MC/s | 640 MC/s | 1,456 MC/s |
| CPU speed | 451–455 MC/s (6 threads, automatic) | 160–175 MC/s (4 threads, automatic) | 64–69 MC/s (automatic threads) |
| Solve time per excitation (CPU / GPU) | 43 and 44 s / 13 and 13 s | 112 and 118 s / 32 and 33 s | 278 and 299 s / 21 and 20 s |
| Timesteps per excitation (CPU / GPU) | 51,662 / 51,662 | 52,629 and 51,636 / 51,662 | 51,636 / 51,662 |

All machines: mesh 112 × 89 × 36 = 0.36 M cells, smallest cell 1.44 × 1.25 × 0.40 µm, Gaussian pulse 20–100 GHz, timestep 1.26 fs, end criterion −40 dB. Each engine ran once, one after the other. The MacBook Air has no fan, so long runs can be slowed down by its temperature. The hpz2 and laptop results are not in the repository.

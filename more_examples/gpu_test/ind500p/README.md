# Inductor: CPU vs GPU

An octagon inductor with center tap on IHP SG13G2, simulated from 0 to 100 GHz with two ports. The model is small (0.8 M mesh cells) and has PEC boundaries.

## Key facts

- On the Windows laptop with its discrete NVIDIA GPU, the GPU was **8.6× faster** than the CPU.
- On the machines with a GPU built into the processor, the GPU gained little: **1.6×** on hpz2, **1.05×** on the Apple M4.
- All runs give the same inductance and Q.

## Speed

Solve time per excitation (the model runs one excitation per port):

| Machine | CPU engine | GPU engine | GPU speedup |
|---|---|---|---|
| hpz2, Radeon 8060S | 45 s | 29 s | 1.6× |
| Apple M4 | 78 s | 74 s | 1.05× |
| Windows laptop, RTX 3060 | 198 s | 23 s | 8.6× |

- With PEC boundaries, the CPU engine is fast. On hpz2 and the M4, it runs at more than half the speed of their GPUs.
- On the M4, CPU and GPU share the same memory, whose speed probably limits both here.
- The laptop's GPU has its own, faster memory and was the fastest GPU in the test. Its CPU was the slowest. See [Discrete GPU or shared memory?](../README.md#discrete-gpu-or-shared-memory)

For comparison: with PML boundaries, the built-in GPUs gain much more, see the [dual dipole](../dual_dipole) and the [thru line](../line_full2port).

## Results

![Differential inductance and Q, CPU vs GPU, hpz2](img/ind500p_cpu_gpu.png)

All machines and engines give 433 pH at 1 GHz, a peak Q of 17 at 45 GHz, and self-resonance at 87 GHz.

On hpz2, CPU and GPU give identical results, to the last digit. The laptop's GPU run is identical to them too. Where runs stopped at a slightly different timestep (M4, laptop CPU), the differences stay below 1 pH in L and 0.02 dB in S11.

## Model and scripts

| Script | Engine |
|---|---|
| [`openEMS_500pH_cpu.py`](openEMS_500pH_cpu.py) | CPU (default) |
| [`openEMS_500pH_gpu.py`](openEMS_500pH_gpu.py) | GPU: `settings['engine'] = 'gpu'` |

That one line is the only difference between the two scripts. The model files are `OctaDiffTap_0n50_ports.gds` and the stackup `SG13G2_200um.xml`, with two via ports from Metal1 to TopMetal2. For the Apple M4 and the laptop, `no_gui = True` and `force_simulation = True` were set for a batch run.

## Test details

| | hpz2 | Apple M4 | Windows laptop |
|---|---|---|---|
| CPU | AMD Ryzen AI Max+ PRO 395, 16 cores | Apple M4, 10 cores | AMD Ryzen 7 5800H, 8 cores |
| GPU | AMD Radeon 8060S, built-in, HIP | Apple M4, 8 cores, built-in, Metal | NVIDIA RTX 3060 Laptop, 6 GB, HIP |
| Main memory, OS | 107 GB, Linux | 16 GB, macOS | 32 GB, Windows 11 |
| openEMS | v0.37.0-33-g53a4264 | v0.37.0-32-gec4d2db | v0.37.0-38-gd686f1d (Windows test package) |
| GPU speed | 1,955 MC/s | 798 MC/s | 2,716 MC/s |
| CPU speed | 1,270 MC/s | 740–770 MC/s (3 or 4 threads) | 273 MC/s |
| Timesteps per excitation (CPU / GPU) | 68,486 / 68,486 | 70,798 and 70,020 / 71,576 and 70,020 | 66,130 and 65,352 / 68,486 |

All machines: 0.8 M cells, PEC boundaries, end criterion −50 dB. The solve times above are the averages of the two excitations.

## More plots

Differential inductance and Q on the Apple M4:

![Differential inductance and Q, CPU vs GPU, Apple M4](img/ind500p_cpu_gpu_m4.png)

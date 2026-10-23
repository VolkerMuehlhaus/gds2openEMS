# Inductor: CPU vs GPU

An octagon inductor with center tap (`OctaDiffTap_0n50_ports.gds`, stackup `SG13G2_200um.xml`), simulated from 0 to 100 GHz with two via ports from Metal1 to TopMetal2. The model has 0.8 M mesh cells and PEC boundaries, and runs one excitation per port.

| Script | Engine |
|---|---|
| [`openEMS_500pH_cpu.py`](openEMS_500pH_cpu.py) | CPU (default) |
| [`openEMS_500pH_gpu.py`](openEMS_500pH_gpu.py) | GPU: `settings['engine'] = 'gpu'` |

That one line is the only difference between the two scripts.

## Speed

On hpz2 (AMD Ryzen AI Max+ PRO 395 with 16 cores and 32 threads, integrated Radeon 8060S GPU, Linux), the GPU engine solved each excitation in 29 s, the CPU engine in 45 s. The GPU was 1.6× faster.

That is less than for the [dual dipole](../dual_dipole) (3.6×). This model is about ten times smaller and has PEC boundaries.

## Results

![Differential inductance and Q, CPU vs GPU](img/ind500p_cpu_gpu.png)

Both engines give identical results. The port voltages and currents from openEMS match to the last digit, and so do the S-parameters. Both runs give 433 pH at 1 GHz, a peak Q of 17 at 45 GHz, and self-resonance at 87 GHz.

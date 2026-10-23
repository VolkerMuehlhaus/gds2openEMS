# Dual dipole antenna: CPU vs GPU

A 245 GHz dual dipole antenna on IHP SG13G2 (IHP design, K. Schmalz), `dipole_port_sg13.gds` with stackup `SG13G2_200um_backsideGND.xml`. The model has 7.6 M mesh cells and computes S11 from 200 to 300 GHz, plus the radiation pattern at 245 GHz.

It was simulated four times: with the CPU and the GPU engine, each with PML and with MUR absorbing boundaries.

| Script | Engine | Boundaries |
|---|---|---|
| [`openEMS_dual_dipole_pml_cpu.py`](openEMS_dual_dipole_pml_cpu.py) | CPU (default) | `PML_8` |
| [`openEMS_dual_dipole_pml_gpu.py`](openEMS_dual_dipole_pml_gpu.py) | GPU | `PML_8` |
| [`openEMS_dual_dipole_mur_cpu.py`](openEMS_dual_dipole_mur_cpu.py) | CPU (default) | `MUR` |
| [`openEMS_dual_dipole_mur_gpu.py`](openEMS_dual_dipole_mur_gpu.py) | GPU | `MUR` |

The scripts differ only in these two settings:

```python
settings['engine'] = 'gpu'                  # GPU scripts only
settings['Boundaries'] = ['PML_8'] * 6      # or ['MUR'] * 6
```

All four also set `settings['resonance_estimation'] = False`, so every run continues until the energy has decayed to the -40 dB end criterion. That makes the run times comparable.

The runs were on hpz2: AMD Ryzen AI Max+ PRO 395 (16 cores, 32 threads) with integrated Radeon 8060S GPU, Linux. They ran one after another, because the CPU and the integrated GPU share the same memory. The same four runs on an Apple M4 are [further below](#apple-m4-macos).

## PML boundaries: 3.6× faster

![Solver speed over wall time, PML](img/speed_vs_time.png)

The GPU engine ran at a steady 1,740 million cell updates per second (MC/s). The CPU engine ran at about 480 MC/s. The simulation took 14 minutes on the GPU and 50 minutes on the CPU.

### Same convergence

![Energy vs timestep and vs wall time, PML](img/convergence.png)

Per timestep, the energy in the model decays the same way with both engines (left). The GPU only gets there sooner (right). Most of the run time is spent in the slow tail after the excitation, typical for a resonant structure like this antenna.

### Same results

![S11, CPU vs GPU, PML](img/s11.png)

The S11 curves lie on top of each other. The largest difference is 0.02 dB. It comes from the two runs stopping at slightly different timesteps: the GPU engine checks the end criterion less often. The antenna results at 245 GHz agree as well:

| At 245 GHz | CPU | GPU |
|---|---|---|
| Directivity | 8.09 dBi | 8.09 dBi |
| Radiation efficiency | 77.54 % | 77.55 % |

## MUR boundaries: 2.6× faster

![Solver speed over wall time, MUR](img/speed_vs_time_mur.png)

MUR boundaries need much less computation than PML. This helps the CPU engine a lot: it runs 66 % faster with MUR than with PML. The GPU engine gains only 22 %. So with MUR the GPU advantage drops to 2.6×: 12 minutes on the GPU, 30 minutes on the CPU.

![S11, CPU vs GPU, MUR](img/s11_mur.png)

Again, CPU and GPU give the same S11, within 0.04 dB.

## PML or MUR?

![S11, PML vs MUR](img/s11_boundary.png)

The boundary type changes the result far more than the engine does. With MUR, the S11 minimum is 1 dB deeper and the curves differ by up to 1.6 dB, about 40 times the CPU/GPU difference. The directivity at 245 GHz is 0.36 dB higher with MUR.

MUR is a simpler absorbing boundary and reflects part of the radiated wave back into the model. PML is the better reference for antennas. With the GPU engine, PML costs little extra time: 14 minutes with PML, 12 minutes with MUR.

## Apple M4, macOS

The same four scripts also ran on an Apple M4 MacBook Air (10 CPU cores, 8-core GPU, 16 GB RAM, macOS), one after another:

| Boundaries | CPU engine | GPU engine (Metal) | GPU speedup |
|---|---|---|---|
| `PML_8` | 145 min, 165 MC/s, 4 threads | 30 min, 833 MC/s | 4.9× |
| `MUR` | 56 min, 433 MC/s, 2 threads | 27 min, 922 MC/s | 2.1× |

![Solver speed over wall time, Apple M4](img/speed_vs_time_m4.png)

The M4's GPU engine is about half as fast as hpz2's (833 against 1,740 MC/s with PML), its CPU engine about a third as fast (165 against 480 MC/s). So the GPU gains even more here: 4.9× with PML, against 3.6× on hpz2. With MUR it is 2.1×, against 2.6× on hpz2. With MUR, the automatic thread count chose only 2 threads for the CPU engine.

During the PML run, the GPU speed fell slowly from 875 to about 805 MC/s. The MacBook Air has no fan; macOS recorded no thermal warning during the runs.

![S11, CPU vs GPU, Apple M4](img/s11_m4.png)

CPU and GPU give the same S11, within 0.022 dB with PML and 0.021 dB with MUR, and the same antenna results as on hpz2:

| At 245 GHz | PML, CPU | PML, GPU | MUR, CPU | MUR, GPU |
|---|---|---|---|---|
| Directivity | 8.10 dBi | 8.10 dBi | 8.44 dBi | 8.44 dBi |
| Radiation efficiency | 77.54 % | 77.55 % | 77.24 % | 77.25 % |

As on hpz2, the boundary type changes S11 far more than the engine: up to 1.5 dB between PML and MUR.

The M4 runs used openEMS v0.37.0-32-gec4d2db and gds2openEMS 0.6.3, with the CPU engine's automatic thread count and the Metal backend of the GPU engine. The run ends after 189,001 (CPU) or 190,656 (GPU) timesteps.

## Test details

| Item | Value |
|---|---|
| Mesh | 259 × 259 × 113 = 7.58 M cells, smallest cell 2.07 × 2.50 × 0.40 µm |
| Excitation | Gaussian pulse 200–300 GHz, timestep 1.26 fs |
| End criterion | `energy_limit = -40` dB, about 190,000 timesteps |
| openEMS | v0.37.0-33-g53a4264 (built from source, with GPU engine) |
| gds2openEMS | 0.6.3 |
| CPU engine | 32 threads (automatic thread count) |
| GPU engine | HIP backend, Radeon 8060S (integrated) |
| Host | hpz2: AMD Ryzen AI Max+ PRO 395 (16 cores, 32 threads), 107 GB RAM, Linux |

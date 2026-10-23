# GSG thru line: CPU vs GPU

A 50 Ω GSG thru line (`gsg_through_50ohm.gds`, stackup `SG13G2.xml`), simulated from 0 to 350 GHz. This is the workflow example [`run_line_GSG_complex.py`](../../../workflow/run_line_GSG_complex.py). Each GSG port is made from two in-plane ports of 100 Ω, from the signal line to the ground on either side, and both are excited at the same time. The model has 2.2 M mesh cells, PEC boundaries and a MUR boundary at the top. It runs one excitation; the reverse direction comes from symmetry.

| Script | Engine |
|---|---|
| [`openEMS_line_GSG_cpu.py`](openEMS_line_GSG_cpu.py) | CPU (default) |
| [`openEMS_line_GSG_gpu.py`](openEMS_line_GSG_gpu.py) | GPU: `settings['engine'] = 'gpu'` |

That one line is the only difference between the two scripts. Compared to the workflow example, both also set `preview_only = False`, `no_gui = True` and `force_simulation = True` for a batch run.

## Speed

On an Apple M4 (MacBook Air, 10 CPU cores, 8-core GPU, macOS), the GPU engine solved the excitation in 106 s, the CPU engine in 124 s. The GPU was only 1.2× faster.

The time steps themselves were 1.5× faster on the GPU: 58 s instead of 88 s, at 995 MC/s instead of 670 MC/s. But before the first timestep, openEMS sets up the model on the CPU, for both engines. For this model the setup took about 36 s with the CPU engine and about 48 s with the GPU engine, a large part of the total.

That is much less than for the [thru line with PML](../line_full2port) (3.5×). Without PML, the CPU engine is fast, and the setup takes a larger share of a short run.

## Results

![S11 and S21, CPU vs GPU](img/line_GSG_cpu_gpu.png)

The curves lie on top of each other. S21 agrees within 0.001 dB, S11 within 0.03 dB above −30 dB, and within 0.5 dB at the lowest S11 of −48 dB at DC. The differences come from the runs stopping at slightly different timesteps (CPU 27,224, GPU 26,620): the GPU engine checks the end criterion at other timesteps.

## Test details

| Item | Value |
|---|---|
| Mesh | 154 × 166 × 85 = 2.17 M cells, smallest cell 1.21 × 1.25 × 0.40 µm |
| Excitation | Gaussian pulse 0–350 GHz, timestep 1.07 fs |
| End criterion | `energy_limit = -40` dB, about 27,000 timesteps |
| openEMS | v0.37.0-32-gec4d2db (built from source, with GPU engine) |
| gds2openEMS | 0.6.3 |
| CPU engine | 4 threads (automatic thread count) |
| GPU engine | Metal backend, Apple M4 (integrated, 8 cores) |
| Host | Apple M4 MacBook Air (4 performance and 6 efficiency cores), 16 GB RAM, macOS 26 |

Each engine ran once, one after the other. The setup times are the openEMS solve time minus the time for the timesteps. The MacBook Air has no fan, so long runs can be slowed down by thermal throttling.

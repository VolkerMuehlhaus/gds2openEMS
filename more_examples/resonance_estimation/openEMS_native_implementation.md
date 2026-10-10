# Resonance estimation in openEMS: notes for a native implementation

For the openEMS maintainers. This document describes how gds2openEMS stops openEMS early once the extrapolated port result has converged ("resonance estimation"), what was learned while building and testing it, and how the same feature could be implemented in openEMS itself. Source references are to openEMS v0.37.0-rc3-32 (`02c6d1e`).

## Summary

- **The problem:** the energy end criterion does not tell how much of the result is still missing. For passive structures with slow decay (inductor L/R tails, RC time constants of capacitors with the port resistors), −40 dB cuts off part of the decay, and the low-frequency result is wrong: the L6n2 inductor's low-frequency series resistance is 20 % too low at −40 dB. −60 dB is accurate for most such models, but runs longer than needed for many of them.
- **The approach:** while openEMS runs, fit a model of decaying resonances to the probe signals recorded so far, extrapolate them, and stop as soon as the extrapolated result no longer changes. The extended signals are used for the DFT. Commercial time-domain solvers have offered this for a long time ("AR filter", "resonance estimation").
- **Status:** implemented in gds2openEMS (`settings['resonance_estimation']`, module [`util_resonance_estimation.py`](../../workflow/modules/util_resonance_estimation.py), about 550 lines of Python and numpy, GPL-3.0) as a Python thread next to `FDTD.Run()`. The thread stops openEMS with `SetAbort(True)`. It was tested on six models with −90 dB reference runs. Compared with plain −60 dB runs, it took 0.45–0.83× the solve time, and its S-parameter error was the same or smaller. For the MIM capacitor it was 20× smaller.
- **Proposal:** three steps of increasing effort: (1) small fixes that help any external monitor, (2) the monitor in the openEMS Python interface, (3) a native C++ end criterion. Step 2 gives most of the benefit for Python users; step 3 also serves Octave/Matlab and the command line.

The user-facing story with plots is in [README.md](README.md) in this folder.

## Results that motivate it

Solve time for all port excitations together, and the worst S-parameter error over all frequencies (max |ΔS|) against a −90 dB run of the same model. All runs used openEMS v0.37.0-rc3-32 on one 16-core workstation.

| Model | Band | −40 dB | −60 dB | Resonance estimation (−60 dB as safety limit) |
|---|---|---|---|---|
| L6n2 inductor, 6.2 nH, 2 ports | 0–14 GHz | 116 s, 1.4·10⁻² | 212 s, 1.1·10⁻³ | 160 s, 1.1·10⁻³ |
| MIM capacitor, 2 ports | 0–100 GHz | 185 s, 2.5·10⁻¹ | 404 s, 2.2·10⁻² | 181 s, 1.1·10⁻³ |
| 2 nH inductor, 2 ports to substrate | 0–30 GHz | 276 s, 1.1·10⁻² | 857 s, 1.7·10⁻³ | 523 s, 4.0·10⁻⁴ |
| 2 nH inductor, 1 differential port | 0–30 GHz | 148 s, 1.7·10⁻² | 336 s, 1.4·10⁻³ | 278 s, 9.0·10⁻⁵ |
| PA core, 5 ports, MUR top boundary | 0–350 GHz | 65 s, 1.4·10⁻³ | 182 s, 5.9·10⁻⁴ | 81 s, 1.5·10⁻³ |
| PA core, 4 ports, MUR top boundary | 0–350 GHz | 40 s, 9.6·10⁻⁴ | 107 s, 2.0·10⁻⁴ | 52 s, 8.3·10⁻⁴ |

In every resonance estimation run, each excitation was stopped by the convergence rule before it reached −60 dB. The PA cores decay fast; they stop right after the pulse with about −40 dB accuracy. With a −60 dB safety limit, a user can expect the accuracy of a −60 dB run or better for slowly decaying models, and −40 dB accuracy for fast ones.

## How the gds2openEMS implementation works

- **Data:** for each excitation, the voltage and current probes of all lumped ports (`port_ut_N`, `port_it_N`, sampled every `GetNyquistNum()/OverSampling` timesteps), and the excitation signal (`et`).
- **Two fit methods**, with poles shared by all probe signals of one excitation:
  - *Known-input fit* (ARX: y[n] = Σ a_k·y[n−k] + Σ b_k·e[n−k], with the excitation e as known input; one shared denominator for all signals). It is refined with Steiglitz-McBride iterations. It also uses the samples recorded while the pulse is still on, so it works for records that end shortly after the pulse.
  - *Free-decay fit* (matrix pencil) on the samples after the excitation has dropped below −60 dB of its peak. It is used when at least 30 such samples exist.
  - Poles with |z| ≥ 1 are reflected to 1/z*.
- **Model order (ARX):** each order is fitted without the last 6 samples and has to predict them. The order is raised while the prediction error is above 1 %, or while the next order still improves it at least 10×.
- **Stop rule:** extrapolations from the record cut at N, N−4 and N−8 samples, all with the same method, give the excited port's S-parameter column within 3·10⁻⁴ (max |ΔS| over the band where the excitation spectrum is above 1 % of its peak). The newest extrapolation also has to pass the tail check. The rule is evaluated at every new probe sample.
- **Tail check:** the extrapolated tail must not grow above 3× the signal level at the end of the record. Its effective time constant τ_eff = 2·E_tail/A_end² (signals normalized to their peaks) must be at most 3× the free decay recorded after the pulse. A slow pole with negligible amplitude passes; one that dominates the tail does not.
- **After the run:** the extrapolation from the complete record must agree with the one from N−4 samples within 3·10⁻³ and pass the tail check. If it does not, and the run was stopped by the stop rule, the extrapolation that met the stop rule is used; otherwise the original data is used. The extended probe signals are written to `sub-N/resonance_estimation/`, and the S-parameter calculation reads them instead of the original files.
- **Extension length:** until the slowest pole has decayed to 10⁻⁷, at most 20× the record length.
- **Cost:** below 1 s per check in numpy, for records of 50–300 samples.

## Proposal

### Step 1: small changes that help any external monitor

1. **End message after an abort** ([issue #236](https://github.com/thliebig/openEMS/issues/236)). After the loop in `openEMS::RunFDTD()` (`openems.cpp`, about line 1541), the warning "Max. number of timesteps was reached before the end-criteria … was reached" is printed whenever `change > endCrit`, including after `SetAbort()`, an `ABORT` file or SIGINT. Users of the gds2openEMS feature see this on every early stop, and gds2openEMS has to explain it in its own log. Proposal: remember why the loop ended and print "aborted (…)" for the abort cases.
2. **Probe flush schedule.** Probe files are flushed only in the progress report, every 4 s of wall-clock time (`PA->FlushNext()`). An external monitor therefore sees the data up to 4 s late, which costs solve time on small models. An option to flush every probe sample, or every K samples, would remove this lag. The files are small.
3. **Reset of `m_Abort`.** `SetAbort(True)` stays set for the next `Run()` of the same object. gds2openEMS calls `SetAbort(False)` before each excitation. Resetting it at the start of `RunFDTD()` would be safer.

### Step 2: resonance estimation in the openEMS Python interface

The natural place for the first native version is the Python interface. It already knows the ports, their probe file names and their reference impedance (`ports.py`: `Port.U_filenames`, `I_filenames`, `CalcPort()`). The solver core has no port concept.

- `openEMS.Run(sim_path, ..., resonance_estimation=True)`: starts a monitor thread before `RunFDTD()`. This works because `Run()` releases the GIL (`with nogil:`, `openEMS.pyx`). The thread reads the growing probe files, applies the stop rule, and calls `SetAbort(True)`. The ports to check are the ones added with `AddLumpedPort()` and similar functions.
- `Port.CalcPort(...)` (or `UI_data`) reads the extended signals when they exist, or gets an option to extrapolate itself.
- The gds2openEMS module could be moved nearly unchanged. Its interfaces are: read probe files (`port_ut_N`, `port_it_N`, `et`), the port Z0, `SetAbort()`, and an output folder.
- Limitations: not available from Octave/Matlab or the command line, and the probe files lag up to 4 s (step 1.2 fixes that).

### Step 3: a native end criterion in the C++ engine

A native implementation would follow the pattern of the steady-state extension: `Eng_Ext_SSD` keeps its own `change` value up to date (`GetLastDiff()`), and `RunFDTD()` uses it instead of the energy. A resonance estimation processing could provide `change` in the same way.

What it needs:

- **In-memory time series of the probes.** `ProcessIntegral::Process()` (`Common/processintegral.cpp`) writes each new value to its file, and `m_Results` holds only the latest one. A buffer per probe (a few hundred to a few thousand doubles) would be enough. The excitation signal is available from `Excitation` (`GetVoltageSignal()`, `GetLength()`, `GetNyquistNum()`).
- **A convergence metric without ports.** The solver does not know which probes form a port, nor Z0. Two options:
  1. *Per probe, normalized by the excitation:* check that X_p(f)/E(f) of every probe has converged, in the band where |E(f)| is above about 1 % of its peak. This works for every port type and for field probes and needs no new input. It is probably the right choice. The tolerance then refers to the probe transfer functions instead of S; a probe-to-S mapping for typical lumped ports would set its value.
  2. Port definitions (probe pairs, Z0) in the XML, with S checked directly. This is more precise, but adds API.
- **A timestep schedule.** By default, the energy is evaluated only in the 4 s progress report (`if (t_diff>4)`), so the stop time of a normal run depends on the machine speed. `--exact-endcriteria` evaluates it every `GetNyquistNum()` timesteps instead. A result-based criterion should be evaluated at every probe sample, see the pitfalls below.
- **Linear algebra.** It needs least squares, SVD, eigenvalues of small non-symmetric matrices (up to about 100×100), and polynomial roots via companion matrices. openEMS links TinyXML, HDF5, Boost and VTK, but no linear algebra library. Eigen (header-only, MPL-2.0) would be the natural addition. Each check then takes milliseconds.
- **Threading.** Run the check in the main thread between `IterateTS()` calls; at milliseconds per check this does not slow the engine. Alternatively, use a helper thread that works on a snapshot of the probe buffers.
- **Output.** Two options:
  - Write extended time-domain probe files next to the originals; post-processing in Python or Octave then reads them.
  - Add the tail analytically to frequency-domain probes (`m_FD_Samples`). For a tail Σ r_k·z_kⁿ from sample N on, the DFT is closed form: Σ r_k·z_k^N·e^{−jωNΔt} / (1 − z_k·e^{−jωΔt}). No long time series is needed.
- **Interface.** For example, an XML attribute `<FDTD ... ResonanceEstimation="1">`, a command line flag, and a keyword in the Python `openEMS()` constructor. Default off. `EndCriteria` stays the safety limit.
- **End message:** "resonance estimation converged after … timesteps (change …)", plus whether the extended signals are used.

## Pitfalls found while testing

- **Check at every probe sample.** Checking only every few samples (for example every 2 s of wall-clock time) missed convergence. On a 6-port PA core, the three extrapolations agreed only for a few consecutive samples at a time, and an excitation that should have stopped at 64 ps ran to the energy limit. Checking every sample, with extrapolations cached between checks (each record length is fitted once), fixed it.
- **Limit the tail length.** A slow pole (for example, a time constant of 1 ns from a 50 ps record) gives very long tails and very expensive checks. Cap the extension (here 20× the record), and let the tail check reject such fits.
- **Use the same method for all compared extrapolations.** A testcase stopped too early when the stop rule compared a free-decay fit (21 free-decay samples) with known-input fits that happened to agree. The method is now chosen once, from the shortest record of the three.
- **The free-decay fit needs enough samples.** With 20–22 free-decay samples, its slowest time constant jumped between 16 and 385 ps from one sample to the next. It is now used from 30 samples on.
- **Slow spurious poles.** Free-decay fits sometimes contain slow poles that the record cannot support (956 ps and 12.7 ns time constants from 40–80 ps of free decay). The tail check catches them. Comparing with the raw result is not a usable safeguard: the raw result of an early stop is expected to disagree, most of all where the extrapolation helps most.
- **Absorbing boundaries.** With MUR at the top boundary, the free-decay fit was sometimes worse than no extrapolation (up to 2.4·10⁻³ at some stop times). Radiation is not well described by a few damped modes. A self-check and a fallback are needed.
- **Field dumps and nf2ff.** Frequency-domain dumps accumulate their DFT during the run. An early stop truncates them, and extrapolating the port probes does not fix that. gds2openEMS does not stop early when the model contains a `DumpBox`. A native implementation could do the same, or extrapolate the dumps too: the poles are shared, so only residues per cell would be needed.
- **One stop per excitation.** Each excitation is a separate run with its own stop time. Sharing poles across excitations was slightly better offline (6·10⁻⁴ against 8.6·10⁻⁴ for the MIM), but is not possible during the run.
- **Non-decaying states.** With openEMS v0.0.36, the excited lumped port kept driving a small DC current after the pulse. The energy stalled at about −73 dB, and the low-frequency result kept changing with run length. openEMS v0.37.0-rc3 does not show this; commit 0a6699a ("lumpedRLC: fix ADE bugs") is the likely fix. Any decay-based criterion fails in such a state. A native implementation should warn about a pole at z ≈ 1.
- **Excitation tail.** The Gaussian pulse is truncated at about −79 dB of its peak and does not end at exactly zero (−1.1·10⁻⁴ relative). Commit 07c96e1 ("fix final Gaussian pulse signal to 0") addresses the start of the pulse; the end may be worth checking too.

## How it was tested

- **Bit-identical truncation.** With the same openEMS build, a run that stops earlier is bit-identical to a longer run of the same model, cut at the same time. One −90 dB run per model can therefore be cut at every probe sample to replay any stop rule offline, without new simulations. This is how the tolerances were chosen, and how changes to the rules were checked before running them live.
- **Different physics:** the L6n2 inductor (slow L/R tail, long pulse), a MIM capacitor (short pulse, RC time constant longer than the pulse), a 2 nH inductor with ports to the substrate (slow substrate component), and PA cores at 0–350 GHz with an absorbing top boundary. There were also two user testcases: a 3-port balun at 100–200 GHz and a 6-port PA core.
- **Compare records from one openEMS build.** v0.0.36 and v0.37 gave a 0.04 Ω different low-frequency resistance for the same L6n2 model and mesh.

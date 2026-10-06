# Implementation report: dielectric loss tangent → Debye dispersive materials

This document explains the design and verification behind the change in this PR, for anyone
reviewing it or wanting to understand *why* it's built this way rather than just *what* changed
(see [`CHANGES.md`](CHANGES.md) for the short version, and
[`XML_stackup_format.md`](XML_stackup_format.md#dielectric-loss-tangent--dispersive-materials) /
the [User's Guide](userguide_md_format/Using_OpenEMS_Python_with_IHP_SG13G2_v3.md#dielectric-loss-tangent-debye-dispersive-materials)
for the user-facing explanation). Addresses the request in
[issue #44](https://github.com/VolkerMuehlhaus/gds2openEMS/issues/44), "Explore implementation
of dielectric loss tangent using Debye/Lorentz model."

## 1. The problem

Every stackup material's `DielectricLossTangent` (tanδ) attribute was already parsed by
`util_stackup_reader.py` into `stackup_material.tand` — but `util_simulation_setup.py` only ever
forwarded `Permittivity` and `Conductivity` to the solver:

```python
CSX_material = CSX.AddMaterial(material.name, kappa=material.sigma, epsilon=material.eps)
```

`tand` was read, printed in debug output, and otherwise completely unused. Two stackups
differing only in a declared loss tangent (e.g. a ×30 difference) produced bit-for-bit identical
S-parameters. Every S21/insertion-loss number ever produced by this workflow for a lossy
dielectric was, silently, a best case (conductor-loss-only) number.

## 2. Why Debye, and why a *wideband* (multi-pole) Debye model

openEMS/CSXCAD exposes two dispersive material models: `CSPropDebyeMaterial` and
`CSPropLorentzMaterial` (the issue explicitly asks to explore both). The physically correct
choice is Debye, not Lorentz:

- **Debye relaxation** is the textbook mechanism for ordinary dielectric loss in polymers,
  PCB laminates, oxides and semiconductors at RF — a dipole/orientation-polarization response
  lagging the applied field. This is exactly the loss mechanism `DielectricLossTangent`
  represents.
- **Lorentz/Drude** models a *resonant* response (the CSXCAD header for
  `CSPropLorentzMaterial` itself says "Lorentz or Drude dispersive materials... Drude is a
  special case of Lorentz"). That's the right model for plasmas, metals' optical-band response,
  or genuine resonances — not for a flat, low-loss dielectric spec.

A **single** Debye pole can only be tuned to match the declared εr/tanδ exactly at one
frequency; away from that point it drifts, increasingly so the wider the simulated band. Since
`DielectricLossTangent` in the XML has no "measured at" frequency at all — it's meant to apply
across whatever band is simulated — a single pole is the wrong tool whenever the band spans more
than a small fraction of a decade.

The correct tool is the **wideband (multi-pole) Debye model**, the same family described by
Djordjevic and Sarkar for causal PCB-laminate dispersion: a sum of Debye poles, log-spaced
across (and a bit beyond) the band of interest, whose combined response tracks a roughly
constant εr and tanδ over many decades — as closely as the Kramers-Kronig relations allow (see
§4).

## 3. The fit: `util_debye_fit.fit_wideband_debye()`

Given `(eps_r, tand, f_start, f_stop)`:

1. **Pole ladder.** Poles are log-spaced across `[f_start, f_stop]`, extended by half a decade
   on each side (`extend_decades`) so the band of interest sits away from the ladder's own edge
   roughness. Pole density is `poles_per_decade` (default 4) — testing showed more poles doesn't
   measurably improve the fit, because the residual error is the physical Kramers-Kronig effect
   (§4), not discretization error. `f_start=0` (common for a Gaussian-excite "from DC" sweep) is
   replaced by `f_stop * floor_ratio` (default 1% of f_stop): fitting a flat loss tangent down to
   literal DC is both ill-defined for log-spaced poles and physically meaningless (every real
   lossy dielectric's loss mechanism turns off at low enough frequency).

2. **Linear least squares, not a nonlinear solve.** For *fixed* pole relaxation times, a Debye
   sum is *linear* in the per-pole weights (`eps_delta_i`) and the instantaneous permittivity
   (`eps_inf`): the only nonlinearity in the whole problem is the pole placement, which is fixed
   up front by the log-spaced ladder, not fitted. This turns the whole fit into an ordinary
   linear least-squares problem.

3. **Non-negative least squares (NNLS), not plain least squares.** Every unknown
   (`eps_inf`, each `eps_delta_i`) is physically required to be ≥ 0 — a negative pole weight or
   negative instantaneous permittivity would make the material locally active (gain) rather than
   lossy, which is both unphysical and numerically unstable in an explicit time-domain (FDTD)
   solver. `scipy.optimize.nnls` guarantees this by construction, rather than fitting
   unconstrained and hoping the result comes out non-negative.

4. **Relative, not absolute, error weighting.** The real part (target εr, e.g. ~4) and the
   imaginary part (target εr·tanδ, e.g. ~0.08) differ in magnitude by 1-2 orders of magnitude.
   Minimizing plain squared error would be dominated entirely by the real part and largely
   ignore the loss. Each row of the least-squares system is normalized by its own target value
   before solving, so the fit minimizes relative error on εr and on tanδ equally — the actual
   quantity we want to reproduce.

The result is `(eps_inf, poles)`, where `poles` is a list of `(delta_eps, relaxation_time)`
pairs — fed directly to `CSPropDebyeMaterial.SetDispersiveMaterialProperty()`.

## 4. The causality tradeoff (and why it's not a bug)

Any causal (physically realizable) dielectric response must obey the Kramers-Kronig relations,
which couple the real and imaginary parts of permittivity. A direct consequence: **a loss
tangent that is exactly flat over many decades is not physically realizable** together with a
real permittivity that is also exactly flat over those same decades. Something has to give.

Numerical testing of the fit (see the PR discussion / commit history for the actual sweep)
confirms this is a real physical limit, not a fitting weakness: adding more poles or more sample
points does not reduce the real-permittivity roll-off at the high end of a wide, lossy band — the
roll-off only shrinks if the band is narrowed or the loss tangent is smaller. For a typical PCB
dielectric (tanδ ≈ 0.02) over 2-3 decades, the roll-off is a few percent; for a much lossier
material (tanδ ≈ 0.07, e.g. a die-attach adhesive) over 3+ decades, it can reach ~15-20% at the
band edge. This matches the well-documented behavior of real lossy laminates (this is precisely
what the Djordjevic-Sarkar wideband model was built to capture, not an artifact of this
implementation).

**Practical implication for users:** if a simulated band spans many decades for a lossy
material, expect the fitted real permittivity to differ somewhat from the nominal
`Permittivity` value at the band edges — this is physically correct behavior, not something to
"fix" by asking for a better fit.

## 5. Verification performed

In order of increasing fidelity to the real code path:

1. **Unit-level fit testing** (`util_debye_fit.fit_wideband_debye()` alone): checked against
   several `(eps_r, tand, f_start, f_stop)` combinations spanning realistic PCB/adhesive
   material values (tanδ 0.001 to 0.07) and bands (sub-GHz to >100 GHz), confirming the fitted
   εr(f)/tanδ(f) track the nominal values to within a few percent across the band of interest,
   widening only as predicted by §4.
2. **CSXCAD object round-trip**: built a `CSPropDebyeMaterial` via `_create_CSX_material()`,
   read every dispersive parameter back out (`GetDispersionOrder()`,
   `GetDispersiveMaterialProperty()`), and confirmed `CSX.Write2XML()` serializes it into the
   exact `DebyeMaterial`/`EpsilonDelta_N`/`EpsilonRelaxTime_N` XML schema openEMS's C++ solver
   itself expects (i.e. not just a valid Python object, but a valid solver input).
3. **Full real-pipeline test**: ran stackup-XML → GDS/polygon → `setupSimulation()` →
   `addGeometry_to_CSX`/`addDielectrics_to_CSX` → `_create_CSX_material()` end to end on a real
   IHP SG13G2 stackup with one material's `DielectricLossTangent` changed from 0 to 0.02,
   confirming exactly that material (and nothing else) became a `DebyeMaterial` property while
   every other (tanδ=0) material was unaffected (same `Material` type and behavior as before).
4. **A real openEMS FDTD run**, not just model construction: a microstrip line on a lossy
   substrate (εr=3.66, tanδ=0.02) was simulated with and without the new dispersive model. The
   lossy run showed a measurable, physically sane extra insertion loss (~0.14 dB/cm at
   3.5 GHz — the right order of magnitude for an FR4-class laminate at that frequency) that the
   non-dispersive run cannot show at all, since conductivity-only loss is independent of a
   dielectric's loss tangent.
5. **Validated against a closed-form textbook prediction, not just a synthetic test case**: a
   single straight 50-ohm microstrip line (εr=4.3, tanδ=0.02, h=1.6mm - Pozar *Microwave
   Engineering* Table 3.1-style "typical FR4" values), with the 50-ohm width synthesized from
   the standard closed-form Hammerstad equations, was simulated with and without the new
   dispersive model and compared against the closed-form dielectric-attenuation formula from
   the same textbook chapter. The *difference* between the lossy and lossless simulated S21
   (isolating the dielectric-loss effect from the real-copper conductor loss present in both
   runs) matched the closed-form prediction to within 1.2% at 1 GHz, widening to 7.6% at 4 GHz
   - consistent with (not contradicting) the causality tradeoff in §4, since the textbook
   formula itself assumes a frequency-independent tanδ/εeff. See
   [`more_examples/textbook_microstrip_attenuation/README.md`](../more_examples/textbook_microstrip_attenuation/README.md)
   for the full derivation, numbers, and plot.

   (Two more ambitious worked examples - reproducing a published Rogers RO4350 hairpin filter
   and an RT/duroid dual-mode SIR filter exactly, with each publication's own simulated and
   measured S-parameters - were attempted first. Both coupled-resonator geometries, reconstructed
   from text dimensions alone without the original artwork, turned out subtly wrong (the FDTD
   result showed no real passband at all), and neither converged to a working filter within a
   reasonable time budget. They were dropped in favor of the textbook example above, where the
   simple geometry means there is nothing to get subtly wrong.)

## 6. What changed, concretely

- New: `workflow/modules/util_debye_fit.py` (`fit_wideband_debye()`).
- `workflow/modules/util_simulation_setup.py`: new `_create_CSX_material()` helper used at all
  three `CSX.AddMaterial()` call sites (geometry polygons, via-fill-factor-scaled polygons,
  background dielectric slabs); `setupSimulation()` now also reads `settings['fstart']`
  (`fstop` was already read, for mesh sizing) and accepts positional `fstart`/`fstop`.
- `pyproject.toml`: new dependency, `scipy` (for `scipy.optimize.nnls`).
- No XML schema change. No change to any existing stackup file's meaning - a stackup with
  `DielectricLossTangent="0"` (the default) is completely unaffected; this only activates for
  materials that already declared a nonzero loss tangent, which previously had zero effect.

## 7. Backward compatibility

- A material with `DielectricLossTangent = 0` (the default/unset value) is completely
  unaffected — identical `CSPropMaterial`, identical call, identical result.
- A material with a nonzero tanδ, simulated **without** `fstart`/`fstop` available (an existing
  model script that never passes them), keeps today's exact behavior: tanδ silently has no
  effect — except that `setupSimulation()` now prints one `NOTE:` per affected material, to make
  the previously-silent gap visible instead of hiding it twice.

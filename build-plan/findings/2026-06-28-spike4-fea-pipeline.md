# Finding — Spike 4: grounded FS pipeline validated against closed form

**Date:** 2026-06-28 · **Phase:** 0 · **Spike:** 4 (STOP gate) · **Type:** result
**Relates to:** existential risk #1 (safety physics uncomputable / LLM-hallucinated). This is the
direct rebuttal: a real, hands-off, converged, *correct* FS on the OSS stack.

## Question

Can the OSS stack (build123d → gmsh → CalculiX) produce a hands-off, converged, and **correct**
factor-of-safety — the number the original PRD had an LLM "Validator" hallucinate?

## Method

Pipeline (`packages/truth_plane/solvers/`): build123d solid → STEP → gmsh **2nd-order tets (C3D10)**
→ CalculiX linear static → parse `.frd` → tip deflection + max von Mises. Convergence study at
characteristic lengths 5/3/2 mm. **Oracle = Euler-Bernoulli beam theory** (a handbook formula, not
an FEA run).

Case: cantilever 100 × 10 × 10 mm, E = 210 000 MPa, ν = 0.3, tip load 100 N (−z), clamp min-x.
Closed form: δ = PL³/3EI = **0.1905 mm**; nominal σ = 6PL/wh² = **60.0 MPa**.

## Results

| char_len | nodes | elems | FEA tip δz | err vs analytic | max von Mises |
|---|---|---|---|---|---|
| 5.0 mm | 999 | 434 | 0.1902 mm | −0.2% | 60.0 MPa |
| 3.0 mm | 4408 | 2339 | 0.1904 mm | −0.0% | 60.2 MPa |
| 2.0 mm | 11329 | 6536 | 0.1905 mm | +0.0% | 61.7 MPa |

- **Deflection matches the closed form to <0.2%** → the *entire* chain is correct: gmsh meshing, the
  gmsh→CalculiX **C3D10 node-ordering permutation** `[0,1,2,3,4,5,6,7,9,8]`, the clamp/load BCs, the
  material, the lumped tip load, and the `.frd` parse. (A wrong node ordering or BC would not
  reproduce δ.)
- **FS converged:** von Mises drift over the last refinement is +2.5% (< 10% gate) → FS = 250/61.7 =
  **4.05** vs analytic 250/60 = 4.17 (ratio 0.97; FEA peak ≥ nominal from the mild clamp
  concentration, as expected).
- **Hands-off:** auto-mesh + geometric face selection (min-x clamp / max-x load by bounding box), no
  manual mesh interaction.

Encoded as 4 green tests (`tests/solvers/test_fs_cantilever.py`, `needs_solver`). Full container
suite: **17 passed**.

## Kill-criteria assessment (Spike 4)

| Criterion | Result |
|---|---|
| (3) round-trip is hands-off | ✅ met |
| (2) FS drift < 10% across refinement | ✅ met (+2.5% on this case) |
| (1) auto-mesh fails on > 15% of a 20-geometry set | ⬜ **not yet tested** (one geometry so far) |

## Honest caveats — what the FEA engineer must own

- **One smooth geometry validated.** The 20-geometry robustness sweep (kill criterion #1) is the
  remaining Spike-4 work; brackets with holes/fillets stress the mesher far more.
- **Singularities.** This smooth cantilever was well-behaved (+2.5%), but a sharp re-entrant corner
  (typical bracket) produces a **non-convergent** peak von Mises. The convergence gate then correctly
  returns **UNKNOWN (blocks export)** — it fails closed, which is the desired behavior — but real FS
  there needs stress linearization / a gauge section / a fillet. That methodology is FEA-engineer
  territory, not auto-pilot.
- **Scope:** linear-static, isotropic, single load case. Real printed-part FS additionally needs FDM
  anisotropy knockdowns, buckling, and modal — out of scope for *pipeline* validation.
- 2nd-order tets are mandatory (linear tets are far too stiff in bending and would give a wrong FS).

## Conclusion

**Spike 4 core PASSES for the validated case:** a grounded, hands-off, converged, *correct* FS is
deliverable on the OSS stack — no LLM in the numeric path. Existential risk #1 is materially retired
for linear-static FS. Remaining before the gate fully clears: the 20-geometry meshing-robustness
sweep, and FEA-engineer ownership of the FS methodology for singular / anisotropic real parts.

## Reproduce

```
docker run --rm -v <repo>:/app gtc-dev python -m pytest -q tests/solvers
```

# Spike 4 — One Hands-Off Gmsh+CalculiX Factor-of-Safety Round-Trip

**Type:** 🛑 STOP gate · **Status:** ⬜ Not started
**Owner:** FEA/simulation engineer (fractional/contract OK at this stage)
**Kill threshold written:** 2026-06-27 (before any spike code)

---

## The bet being proved

A grounded safety number (factor of safety) is **deliverable, hands-off, on the OSS stack**:
OCCT solid → Gmsh tet mesh (fully automated, zero manual mesh-touching) → CalculiX linear-static,
one load case → min FS = yield / max von-Mises → a **typed verdict** (number + convergence error
bar + an `unknown` state). This is what lets the Validator be a *router*, not an LLM — the scalar
comes from CalculiX, never an LLM token.

## Kill criteria (numeric, pre-committed)

The spike is **DEAD** (grounded numbers not deliverable on OSS → STOP / pivot to a commercial
solver) if **any** of:

- automated meshing **fails or needs manual repair on > 15%** of the 20-geometry robustness set, **OR**
- FS **drifts > 10%** across 3 mesh-refinement levels (i.e. it never converges), **OR**
- the round-trip **cannot be made hands-off** (requires a human to babysit meshing/solve per part).

## Method / protocol

1. Take the Spike 1 knuckle (STEP/B-rep) as the first geometry.
2. Drive OCCT → Gmsh → CalculiX entirely via CLI, no GUI, no manual mesh edits.
3. Compute min FS from yield / max von-Mises under one declared load + boundary condition.
4. **Convergence study:** re-run at 3 refinement levels; assert FS converges within 5%. A PASS must
   **never** be emitted on an unconverged mesh.
5. **Robustness:** run the same pipeline over a 20-geometry set (varied brackets/mounts) and record
   the auto-meshing success rate.
6. Emit the typed verdict; verify the `unknown` path fires when inputs are missing/invalid.

## Claude's role

- **Dev-time:** Claude writes the OCCT→Gmsh→CalculiX driver + the mesh-convergence harness, using an
  **MCP server wrapping the solver CLIs** so it can run-observe-iterate.
- **Runtime pattern to validate:** Claude is the **Validator ROUTER only** — it narrates CalculiX
  output into a typed verdict; the scalar comes from CalculiX, never an LLM token.

> ⚠️ **Reward-hacking hazard.** Letting Claude *autonomously* iterate a mesh/solve loop against a
> convergence check invites it to tune refinement until the number merely *looks* converged —
> reward-hacking the very gate meant to certify FS. The convergence oracle and the reference FS
> values must be **human-pinned** (closed-form / handbook / PE-verified — e.g. Euler-Bernoulli
> cantilever, Roark/Euler buckling cases), **never Claude's own run.**

## Risks specific to this spike

- **Determinism vs latency tension:** byte-identical hashes want `OMP_NUM_THREADS=1`, but
  single-threaded CalculiX/Gmsh on a real part can be wall-clock prohibitive vs the regen budget.
  Plan: single-thread on the determinism CI image, multi-thread in prod, reconcile via canonicalized
  hashes — don't conflate the two.
- **FDM correlation is downstream and harder than this spike** (see Phase 2 / critique R5): a
  *converged linear-static FS* is necessary but not sufficient for predicting *FDM-printed* failure
  (20–40% scatter). This spike only proves the FS pipeline, not physical correlation.

## Results (2026-06-28 — single validated case)

Pipeline built (`packages/truth_plane/solvers/{mesh,calculix,cases,fs}.py`) and validated against a
closed-form cantilever. Full finding: [findings/2026-06-28-spike4-fea-pipeline.md](../findings/2026-06-28-spike4-fea-pipeline.md).

| Field | Value |
|-------|-------|
| Auto-mesh success rate on 20-geo set | **100% (19/19)** ✅ — boxes/cylinders/L-brackets/slotted plates/holed brackets, hands-off (`tests/solvers/test_mesh_robustness.py`) |
| FS drift across 3 refinements | **+2.5%** (threshold: <10%) ✅ |
| Hands-off (zero manual mesh edits)? | **yes** ✅ (auto-mesh + geometric face selection) |
| Pipeline correctness | **tip deflection matches PL³/3EI to <0.2%** ✅ (validates mesh, C3D10 node order, BCs, material, load, .frd parse) |
| `unknown` path fires correctly? | **yes** — non-converged stress → `FsVerdict("UNKNOWN")` blocks (fails closed) |
| **Classification** | **PASS** — deflection-validated, FS converges, hands-off, 19/19 auto-mesh. Remaining caveat (not a blocker): FEA-engineer ownership of FS methodology for singular (re-entrant) / anisotropic (FDM) real parts |
| Escalation triggered? | No — OSS stack (gmsh+CalculiX) delivers; no commercial-solver pivot needed |

**Remaining before the gate fully clears:** the 20-geometry meshing-robustness sweep (kill criterion
#1), and FEA-engineer sign-off on the FS methodology where peak stress is singular (re-entrant
corners) or the material is anisotropic (FDM knockdowns). Tests: `tests/solvers/test_fs_cantilever.py`.

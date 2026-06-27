# Finding — OCCT determinism probe (mesh, Windows)

**Date:** 2026-06-27 · **Phase:** 0 · **Type:** harness probe (not the full gate)
**Relates to:** existential risk #3 (non-deterministic replay) · Verification Harness §1

## Question

Does the geometry kernel reproduce identical geometry run-to-run? Existential risk #3 says
event-sourced replay is only valid if the producer is deterministic — and the analysis flagged OCCT
as *not* guaranteed bit/topology-stable across versions/platforms. Before trusting any "exact
historical state" claim we need real data on how reproducible the kernel actually is.

## What was measured

- **Stack:** `build123d 0.10.0`, `cadquery-ocp 7.8.1.1` (OCCT 7.8.1), Python 3.10.11, **Windows 11**.
- **Method:** render a 4.5 mm × 20 mm cylindrical pin, tessellate at 0.05 mm deflection, hash a
  **canonical** mesh form (vertices rounded to 6 dp; each triangle = its 3 vertices sorted; triangle
  list sorted; sha256). Code: `packages/truth_plane/regen/{generator,canonical,probe}.py`.
- Ran the probe in **4 fresh subprocesses** + in-process repeats.

## Result

✅ **Cross-process deterministic — mesh AND STEP B-rep.** All 4 fresh processes produced identical
hashes: mesh `22320eeb…3d69d6`, canonical STEP B-rep `4eb40ae2…1a28b3`. In-process repeats match;
both hashes are change-sensitive (4.5 mm ≠ 5.0 mm), so this is "stable", not "constant".

**STEP canonicalization (added same day):** raw STEP export has exactly two volatile, non-geometric
fields — the FILE_NAME ISO timestamp, and a `NEXT_ASSEMBLY_USAGE_OCCURRENCE` id that is an OCCT
*session counter* (increments within a process, resets per fresh process). Both are normalized in
`canonical.canonical_step_text`. After that, the B-rep is byte-identical across fresh processes. The
full-gate anchor (`test_mesh_determinism.py`) is now a **real green cross-process test**, not an
xfail. Codified across `test_mesh_determinism.py` (the gate) + `test_mesh_probe.py` (sensitivity).

## What this does and does NOT prove

**Does:** for a simple primitive, OCCT 7.8.1 tessellation is reproducible across process restarts on
one fixed machine. That is the *necessary* baseline for replay/golden-hashing — and it's encouraging.

**Does NOT (still open):**
- ~~Mesh only, not the STEP B-rep.~~ ✅ **Resolved** — STEP B-rep is now canonicalized and reproducible
  cross-process; the anchor is a real green test.
- **Single machine / single OS.** ➜ **Now measured for x64** (see
  [cross-platform finding](2026-06-27-cross-platform-determinism.md)): the exact B-rep is identical
  on Win-x64 & Linux-x64, but the mesh tessellation is platform-scoped. *Cross-version* (OCCT
  7.5→7.8) and *arm64 / Apple-Silicon* remain unmeasured.
- **Trivial geometry.** No booleans/fillets/offsets — exactly OCCT's least-stable ops and where
  topological-naming (Spike 1) bites. Determinism of *those* is unproven.
- **No multithreading.** Determinism here was implicitly single-threaded; BLAS/OMP thread races are a
  known nondeterminism source (harness must pin `OMP_NUM_THREADS=1`).

## Next steps

1. Implement STEP B-rep canonicalization → flip the full-gate anchor from xfail to a real test.
2. Re-run the probe inside the **Linux dev container** and compare the hash to Windows — quantify the
   cross-platform gap (this is the data that decides how portable the fingerprint can be).
3. Extend the probe to a boolean'd part (bracket with a bolt hole) once the generator grows — couple
   to Spike 1.

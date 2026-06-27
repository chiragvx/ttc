# Finding — Cross-platform determinism: B-rep portable, mesh platform-scoped

**Date:** 2026-06-27 · **Phase:** 0 · **Type:** harness result (significant — architecture-shaping)
**Relates to:** existential risk #3 (non-deterministic replay) · builds on
[the within-platform probe](2026-06-27-determinism-probe.md)

## Question

The within-platform probe showed OCCT 7.8.1 reproduces a pin identically across fresh processes *on
one machine*. The real worry (risk #3) is **cross-platform** drift. Does the same geometry hash
identically on Windows-x64 and Linux-x64?

## Method

Built the canonical Linux image (`docker/Dockerfile.dev`, Python 3.12, **kernel libs pinned to match
Windows**: build123d 0.10.0 / cadquery-ocp 7.8.1.1 / OCCT 7.8.1). Ran the same probe
(`packages.truth_plane.regen.probe`) for the 4.5 mm pin and compared the canonical **mesh** and
**STEP B-rep** hashes against the Windows values.

## Result

| Artifact | Windows x64 | Linux x64 | Match? |
|---|---|---|---|
| **STEP B-rep** (canonical) | `4eb40ae2…1a28b3` | `4eb40ae2…1a28b3` | ✅ **IDENTICAL** |
| **mesh** (tessellation) | `22320eeb…3d69d6` | `67d4ab6e…e5bab4` | ❌ **DIFFERS** |
| portable toolchain fp | `36b31dc2…` | `32c67b6e…` | differs (expected*) |

\* the portable fingerprints differ only because Python is 3.10 vs 3.12 and gmsh is absent vs
4.13.1 — **not** a geometry difference. The geometry libs (build123d/OCCT) are identical.

Within-platform, both OSes are fully deterministic (the cross-process gate is green on both: 12/12).

## Interpretation

- **The exact B-rep is cross-platform deterministic.** STEP serializes the analytic geometry
  (canonical surfaces / NURBS control data) which OCCT emits identically across platforms once the
  timestamp + session-counter are canonicalized. **This is the strong, usable result.**
- **The tessellation is platform-dependent.** `BRepMesh` is an incremental floating-point mesher;
  its vertex positions/counts are sensitive to libm / compiler / FP codegen, which differ across
  OS toolchains even on the same x64 arch. So mesh hashes are **platform-scoped**, not portable.

## Architectural implications (act on these)

1. **Event-sourcing / replay must content-address the STEP B-rep, not the mesh.** The B-rep hash is
   the cross-platform-stable geometry identity. ➜ Encoded as a golden regression:
   `GOLDEN_PIN_BREP_SHA256` in `tests/determinism/test_mesh_determinism.py` (passes on Win + Linux).
2. **Mesh is a platform-scoped DERIVATION.** Any mesh that must be reproducible (a golden, a
   cached viewport asset keyed for comparison) must be tessellated on a **canonical platform** (the
   Linux CI image) OR have OS/arch folded into its fingerprint. Never use a mesh hash as a
   cross-platform identity. The live viewport mesh (Tier 1) can stay platform-local — it's not an
   identity, just a render.
3. The toolchain fingerprint's **full** variant (includes OS/arch) is the right key for mesh
   artifacts; the **portable** variant (versions only) is acceptable for B-rep artifacts.

## Still open

- **arm64 / Apple Silicon** — a *different architecture* may drift even the B-rep; unverified
  (hosted x64 CI + WSL2 are both x64). Needs a macOS-arm64 or arm64-Linux run.
- **Cross OCCT-version** stability (7.5→7.8 rewrote booleans/fillets) — the whole reason the
  fingerprint exists; only one version tested so far.
- **Boolean'd geometry** (brackets with holes/pockets) — couples to Spike 1; primitives only so far.

## Side result — Spike 4 chain is alive

In the image: `ccx` runs (`calculix-ccx`) and `gmsh 4.13.1` imports. The build123d → gmsh → CalculiX
chain is present and importable — the substrate for Spike 4 (the FS round-trip) is ready.

## Ops note

The image snapshots source at build time (`COPY . .`), so newly-added tests don't appear in an old
image — rebuild, or volume-mount the repo (`docker run -v "$PWD":/app …`) for local iteration. CI
checks out fresh each run, so it's a non-issue there.

# Linux dev / CI image

The canonical Linux environment — the determinism-fingerprint reference, and the substrate that
build123d/OCCT, Gmsh, CalculiX, and the Firecracker/gVisor sandbox require (the Windows dev box
can't host them). Phase 0 §3c.

## Build & run

```bash
make image            # build docker/Dockerfile.dev as gtc-dev
make ci               # run the test suite inside the image
make shell            # interactive shell
make spike4-smoke     # confirm build123d -> gmsh -> ccx are all present (Spike 4 groundwork)
```

(Or `docker build -f docker/Dockerfile.dev -t gtc-dev .` directly. No Docker on the Windows box yet —
build this on a Linux host / WSL2, or in CI.)

## What it pins

- Python **3.12** (the target runtime).
- `constraints/kernel-linux.txt`: build123d 0.10.0, cadquery-ocp 7.8.1.1 (OCCT 7.8.1), numpy 2.2.1,
  gmsh 4.13.1 — **matched to the Windows dev box** so the first cross-platform comparison isolates
  OS/arch as the only variable.
- CalculiX (`ccx`) from apt (`calculix-ccx`).
- `OMP_NUM_THREADS=1` + friends — single-thread for reproducible hashes (the gate; prod runs
  multi-thread — risk R6).

Changing any pin changes the toolchain fingerprint and is a deliberate golden-hash rebaseline event.

## The cross-platform determinism experiment (the reason this exists now)

Existential risk #3 says replay is only valid if the kernel is reproducible. The Windows probe showed
a 4.5 mm pin hashes identically across 4 processes — but **Windows ≠ Linux**, and cross-platform drift
is the real worry. To quantify it:

1. **Windows (already have):**
   ```
   python scripts/toolchain_fingerprint.py --portable   # -> 36b31dc2…
   python -m packages.truth_plane.regen.probe 4.5        # -> 22320eeb…3d69d6
   ```
2. **Linux container:**
   ```
   make ci-determinism    # prints the portable fingerprint + the mesh hash from inside the image
   ```
3. **Compare:**
   - *portable fingerprint matches* → kernel lib versions are identical, so any mesh-hash difference
     is genuinely OS/arch (libm/FMA/codegen), not a version mismatch.
   - *mesh hash matches too* → OCCT 7.8.1 is cross-platform reproducible for this case → the golden
     fingerprint can span OSes. Strong result.
   - *mesh hash differs* → determinism is **per-platform**; the fingerprint must include OS/arch and
     golden hashes are platform-scoped. Follow-up: spin a Python-3.10 Linux image to separate the
     Python-version variable from the OS variable.

Record the outcome as a new finding in `build-plan/findings/`.

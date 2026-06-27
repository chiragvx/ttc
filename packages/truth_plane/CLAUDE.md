# packages/truth_plane — the grounded, slow, async plane

Everything expensive and authoritative: OCCT B-rep regen + `regen/` (Jinja2 + build123d templater,
BRepCheck/ShapeFix, the post-compile round-trip verifier), and `solvers/` (Gmsh+CalculiX FS, slicer,
later the optimizer). **Runs as durable async jobs — never on the hot path, never re-invoked during
replay.** All of this is Linux-only (build123d/OCCT/Gmsh/CalculiX) and runs inside the sandbox.

Hard rules:
- The Validator is a **router**, not an LLM: it turns solver output into a typed verdict written to
  `ledger.derived.*`. The scalar comes from the solver, never an LLM token.
- A safety number is only valid if its mesh converged — never emit a PASS on an unconverged mesh.
- Golden/reference values come from handbook / closed-form / PE, never from Claude's own run.
- `solvers/` has the **validated** Spike-4 FS pipeline (`mesh` → `calculix` → `fs`, oracle in
  `cases`). 2nd-order tets (C3D10) are mandatory (linear tets are wrong in bending). Any FS change
  must keep `tests/solvers/test_fs_cantilever.py` green against the closed-form cantilever. FS
  methodology for singular/anisotropic real parts is FEA-engineer territory — do not self-certify it.
- `regen/` has the determinism probe; the full templated generator waits on Spike 1 (identity).

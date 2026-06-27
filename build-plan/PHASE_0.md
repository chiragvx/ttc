# Phase 0 — De-Risk Spikes (First 30 Days)

**Window:** Days 0–30 · **Status:** 🟡 In progress (started 2026-06-27)
**Exit gate:** Day-25 gate review — the two STOP gates + the scope-STOP must clear (or escalate)
**before any Phase 1 foundation code is written.**

---

## 1. Objective

Prove or kill the five keystone bets with **throwaway** spikes, each governed by a one-page
kill-criteria doc whose **numeric STOP threshold is written before the spike code exists**. Spike
code is throwaway *by contract* — survivors get rebuilt clean against a spec in Phase 1.

**Why throwaway matters:** the worst failure mode is "it limped, so we promoted it" — that's how
an unproven naming assumption becomes load-bearing. A drifted result is *signal*, not a nuisance.

---

## 2. The five spikes

| # | Spike | Type | STOP threshold (short form) | Owner | Status | Doc |
|---|-------|------|-----------------------------|-------|--------|-----|
| 1 | Topological identity | **STOP** | >5% silent wrong re-binds, or face-split needs manual annotation | OCCT engineer | ⬜ Not started | [SPIKE_1](spikes/SPIKE_1_topological_identity.md) |
| 2+3 | Delta→template codegen in killable sandbox | **scope-STOP** | >20% intents inexpressible as deltas; or sandbox can't kill / warm-restore >250 ms / egress not denied | Generalist + Claude | ⬜ Not started | [SPIKE_2_3](spikes/SPIKE_2_3_codegen_sandbox.md) |
| 4 | Gmsh+CalculiX FS round-trip | **STOP** | meshing fails >15% of 20-geo set, or FS drifts >10% across refinement, or not hands-off | FEA engineer | 🟢 **Core validated** (deflection matches closed form <0.2%; FS drift +2.5%; hands-off). 20-geo sweep + FEA sign-off pending | [SPIKE_4](spikes/SPIKE_4_solver_fs_roundtrip.md) |
| 5 | Two-plane latency | degrade-not-stop | proxy diverges >2–3% on mass/CG, or morph range too narrow | Generalist + Claude | ⬜ Not started | [SPIKE_5](spikes/SPIKE_5_two_plane_latency.md) |

Each spike runs in an isolated git worktree with a scoped subagent; a separate **judge subagent**
scores pass/fallback/stop mechanically against the pre-written criteria.

### Coupling note (from critique — these are NOT fully parallel)
Spike 1 and Spike 4 both need a working build123d generator for the **same** part (the knuckle),
and Spike 4 meshes the geometry Spike 1 produces. Build the shared knuckle generator **once**, first,
then fork the worktrees. Sequence: shared generator → (Spike 1 ∥ Spike 4) → (Spike 2+3 ∥ Spike 5).

---

## 3. Parallel workstreams (also start in the first 30 days)

These are **architecture-blocking** or harness foundations — they run alongside the spikes.

### 3a. Architecture-blocking decisions (resolve before stack-lock) — see `reference/PLAYBOOK.md §6`
| Decision | Action | Owner | Status |
|----------|--------|-------|--------|
| Topological-identity bet | = Spike 1 result (determines Python-shop vs C++/OCCT-FFI hire) | OCCT eng | ⬜ |
| AGPL slicer isolation boundary | Lock: unmodified sidecar, files+CLI only, network-isolated. Claude drafts "separate work" memo + SBOM/copyleft CI gate; **counsel signs aggregation theory** | Founder + counsel | ⬜ |
| Hosted-Claude vs air-gapped-vLLM seam | Build ONE `LLMProvider` abstraction from commit #1; CI lint fails on any Anthropic-SDK import outside it. File CJ/CCATS classification with export counsel using UAV example | Founder + counsel | ⬜ |
| OCCT LGPL relink (coupled to above) | Dynamic-link OCCT from first on-prem build; gate on-prem artifact on signed "LGPL-cleared" token | Counsel | ⬜ |

### 3b. Verification & determinism harness (first CI artifact) — see `reference/PLAYBOOK.md §5`
| Item | Action | Status |
|------|--------|--------|
| Executable ledger schema + export-gate tests | `ParameterDef` + hardened ledger + `evaluate_export_gates`; `test_export_gates.py` asserts missing FS → `EXPORT_BLOCKED`/`unknown`, FS-floor, HARD_LOCK round-trip + immutability, forbidden-target | ✅ **Done** (8 tests green) |
| Golden-geometry determinism gate | Cross-process gate (mesh+brep) + **cross-platform B-rep golden** (`GOLDEN_PIN_BREP_SHA256`, verified identical Win-x64 & Linux-x64). STEP canonicalized. 13/13 green | ✅ **Done** |
| Determinism — remaining scope | **x64 cross-platform answered**: exact B-rep portable ✅, mesh tessellation platform-scoped ❌ ([finding](findings/2026-06-27-cross-platform-determinism.md)). Still open: arm64, cross OCCT-version, boolean'd geometry (Spike 1) | 🟡 Partially answered |
| Toolchain fingerprint | `scripts/toolchain_fingerprint.py` — SHA-256 over build123d/OCP/numpy/gmsh versions + Python + OS/arch + OMP threads; full + portable variants. Verified on Windows | ✅ **Done** |
| Copyleft / slicer-isolation gate | `scripts/check_copyleft.py` — fails on AGPL in the project's dependency closure or any in-process slicer import; warns on LGPL. Closure-scoped (strict in CI's isolated venv) + classifier-based detection. Validated | ✅ **Done** |
| `LLMProvider`-only import lint | `scripts/check_llm_provider_imports.py` — fails on Anthropic-SDK import outside `packages/agents/llm_provider.py`. Validated | ✅ **Done** |
| GitHub Actions CI | `.github/workflows/ci.yml` — `host-checks` (ruff + gates + pure tests) & `kernel` (build image, determinism gate, Spike 4 smoke). All steps validated locally (host gates green; kernel job replicated via Docker) | 🟡 Authored & locally validated; runs on first push |

### 3c. People & partners (longest-lead — start week 1)
| Item | Action | Status |
|------|--------|--------|
| OCCT/build123d engineer | **Open search this week** — rarest/longest-lead hire; owns Spike 1. ⚠️ See risk R1 | ⬜ |
| FEA/simulation engineer | Fractional/contract OK until load-test milestone; owns Spike 4 | ⬜ |
| Design partner with a load frame | Start one conversation (robotics shop / university lab) for the prints-and-fits/load-test milestone | ⬜ |
| Linux dev substrate | Image **built & validated** on Docker Desktop/WSL2 (2.24 GB): full suite 12/12 in Linux, `ccx` + gmsh 4.13.1 present. R7 resolved for x64 (arm64 still open) | ✅ **Built & running** |

---

## 4. Risk adjustments carried from the critique

These materially change *how* we run Phase 0 (full list in `reference/playbook-critique.json`):

- **R1 — Identity spike needs its owner first.** Spike 1 sits in Claude's most dangerous zone
  (phantom OCP APIs) and its kill-criterion needs a ground-truth oracle. **Do not let
  generalists + Claude self-score it.** Hire/contract the OCCT engineer to hand-annotate the
  ~100-case ground-truth set before scoring.
- **R2 — The wedge does NOT defer identity risk.** A motor-mount bracket = booleans cut into
  template faces = the exact face-split case. Expect Spike 1 to bite on day one.
- **R3 — Review throughput is the binding constraint**, concentrated on the two specialists.
  Budget them as reviewers first, authors second.
- **R5 — FDM correlation is metrology, not wiring.** Measured-vs-predicted scatter is routinely
  20–40%, not 3%. Reframe the Phase 2 proof-point as "predicts failure within a *calibrated
  confidence band*"; pick a less stochastic hero part if possible.
- **R6 — Determinism vs latency tension.** Single-thread for byte-identical hashes conflicts with
  the 1–5 s regen budget. Plan: single-thread on the CI determinism image, multi-thread in prod,
  reconcile via canonicalized hashes (not bit-identity).
- **R7 — Dev box is Windows; substrate is Linux-only.** "Run locally in gVisor" isn't runnable as
  written. Standardize the Linux dev container day one (see 3c).
- **R-sandbox — 250 ms warm-restore budget may be inconsistent** with a large Python+OCCT memory
  footprint. Treat the 250 ms as a hypothesis to measure in Spike 2+3, not a given.

---

## 5. Definition of done (Day-25 gate review)

Each spike is classified **PASS / FALLBACK / STOP** against its pre-written criteria by the judge
subagent + the owning specialist. To exit Phase 0:

- [ ] Spike 1 (identity): PASS, or a decided escalation to C++ OCAF/TNaming (with hiring + timeline impact accepted)
- [ ] Spike 2+3 (codegen/sandbox): scope-STOP cleared — delta vocabulary covers ≥80% of realistic intents AND sandbox containment proven
- [ ] Spike 4 (solver): PASS, or a decided pivot to a commercial solver
- [ ] Spike 5 (latency): PASS or accepted DEGRADE fallback (rigid proxy + regen-on-release)
- [ ] All four architecture-blocking decisions (3a) have a documented direction
- [ ] The determinism harness (3b) is the first green/red CI artifact
- [ ] Both specialist searches open; one design-partner conversation started

> **Ambiguous-middle rule (from critique R-gov):** real research spikes often land at "works on
> 88%, fails ambiguously on the rest." That is NOT a clean pass — it is a `FALLBACK` requiring an
> explicit, written decision (narrow scope / escalate / accept-with-mitigation). Never "rationalize
> the limping result forward."

---

## 6. Progress log

| Date | Update |
|------|--------|
| 2026-06-27 | Phase 0 kicked off. Build-plan tracker structure created; reference docs (tech plan, playbook, gap analysis, critique) persisted to `reference/`. The 5 spike kill-criteria docs authored with numeric STOP thresholds. |
| 2026-06-27 | **Repo skeleton landed** (Monday actions #2, #4). Monorepo mirrors the two planes (`packages/{ledger,interactive_plane,truth_plane,agents,transport,frontend}`); root + per-module `CLAUDE.md` with the 3 inversions + DO-NOT-BUILD cut-list. Executable ledger spec built: `ParameterDef` (bounds/lock invariants enforced at construction), hardened `MasterParametricLedger` (`extra=forbid`, `derived` solver-only + `review` sign-off FSM), `DeltaProposal` (the only legal LLM emission) with forbidden-target guard, `evaluate_export_gates` (unknown-blocks-export). Closed-form interactive proxies + the single `LLMProvider` seam stubbed. **Tests: 8 passed, 1 strict-xfail** (determinism anchor). `pyproject.toml` configured. |
| 2026-06-27 | ⚠️ **Discovery:** `build123d` is already installed on the Windows dev box (`…/Python310/site-packages/build123d`). Means local geometry spikes are possible now — but Windows OCCT determinism ≠ the canonical Linux CI fingerprint, so the authoritative determinism gate still needs the Linux dev container. Pytest not previously installed; added it. |
| 2026-06-27 | **Determinism probe built & run** (`build123d 0.10.0` / OCCT 7.8.1, Windows). Canonical mesh hash of a 4.5 mm pin is **identical across 4 fresh processes** → real baseline for risk #3. 3 green tests added (`tests/determinism/test_mesh_probe.py`); deprecation noise filtered in pyproject. **Suite: 11 passed, 1 xfailed.** Caveats (still open): mesh-only not STEP, single OS, trivial geometry (no booleans/fillets), single-thread. Full finding: [findings/2026-06-27-determinism-probe.md](findings/2026-06-27-determinism-probe.md). |
| 2026-06-27 | **Toolchain-fingerprint tool + Linux dev/CI image authored** (unblocks R7 + Spike 4). `scripts/toolchain_fingerprint.py` (full+portable, verified on Windows: portable `36b31dc2…`). `docker/Dockerfile.dev` pins Python 3.12 + matched kernel libs + CalculiX `ccx`, single-thread for reproducible hashes; `.devcontainer/`, `constraints/kernel-linux.txt`, `Makefile`, `docker/README.md` (documents the cross-platform determinism experiment). **Cannot build here (no Docker/Linux on Windows)** — needs a Linux host/WSL2 or CI. Once built: `make ci-determinism` compares the Linux mesh hash to Windows `22320eeb…`. |
| 2026-06-27 | **STEP B-rep canonicalization done → determinism anchor flipped to a real green gate.** Found STEP's two volatile non-geometric fields (FILE_NAME timestamp + an OCCT `NEXT_ASSEMBLY_USAGE_OCCURRENCE` session counter); normalized both in `canonical.canonical_step_text`. Pin's canonical **mesh + B-rep** now identical across fresh processes (brep `4eb40ae2…`). Probe CLI emits both hashes as JSON; the xfail anchor is now a real cross-process test (mesh+brep). **Suite: 12 passed, 0 xfailed.** |
| 2026-06-28 | **Spike 4 core PASSES — grounded FS validated against closed form.** Built the OCCT→gmsh→CalculiX pipeline (`packages/truth_plane/solvers/{mesh,calculix,cases,fs}.py`): 2nd-order tets (C3D10), geometric BC face selection, `.frd` parse, convergence study → typed `FsVerdict` (OK/UNKNOWN, fails closed). Validated on a cantilever: **tip deflection matches PL³/3EI to <0.2%** (proves mesh, the gmsh→CalculiX node-ordering permutation, BCs, material, load, parse all correct); FS converged (+2.5% drift, < 10%), FS 4.05 vs analytic 4.17. Directly rebuts existential risk #1 (LLM-hallucinated safety numbers). 4 green `needs_solver` tests; **container suite 17 passed**, Windows 13 passed + 4 skipped. Remaining: 20-geo robustness sweep + FEA-engineer ownership of singular/anisotropic FS methodology. Finding: [findings/2026-06-28-spike4-fea-pipeline.md](findings/2026-06-28-spike4-fea-pipeline.md). |
| 2026-06-27 | **CI + gates + Linux image — built, run, and a major determinism result.** GitHub Actions `ci.yml` (host-checks + kernel jobs); `check_llm_provider_imports.py` + `check_copyleft.py` gates (the copyleft gate caught real bugs → rewrote to closure-scoped + classifier-based; validated strict in isolated venv). Fixed two build blockers: `[build-system]`/setuptools-find in pyproject (`pip install -e .`), and the headless-gmsh X-lib set in the Dockerfile. **Image built (2.24 GB), 12/12 in Linux, ccx+gmsh present.** **Cross-platform determinism: exact STEP B-rep IDENTICAL on Win-x64 & Linux-x64 (`4eb40ae2…`); mesh tessellation DIFFERS (platform-scoped).** Encoded `GOLDEN_PIN_BREP_SHA256` regression. Suite **13 passed**. Finding: [findings/2026-06-27-cross-platform-determinism.md](findings/2026-06-27-cross-platform-determinism.md). |

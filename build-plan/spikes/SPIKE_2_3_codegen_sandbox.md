# Spike 2+3 — Delta→Template Codegen inside a Killable Sandbox

**Type:** ⚠️ scope-STOP · **Status:** ⬜ Not started
**Owner:** Generalist + Claude (sandbox piece needs Linux/KVM substrate)
**Kill threshold written:** 2026-06-27 (before any spike code)

---

## The bet being proved

Two halves of the core safety inversion:

- **(A) Inverted codegen holds.** The LLM emits only **Pydantic-validated parameter deltas**; a
  deterministic **Jinja2 + build123d** templater renders the script. Real design intent is
  expressible this way for the wedge domain — we never need LLM-authored free Python.
- **(B) Containment is real.** Even a deterministic templater executes build123d/OCCT (C++ via
  pybind11), so execution must be sandboxed against uncatchable kernel crashes and RCE.

## Kill criteria (numeric, pre-committed)

**Part A — codegen vocabulary (scope-STOP):**
- Feed **30 realistic NL intents** to Sonnet via strict tool-use; measure the fraction **fully
  expressible** as deltas against the template library.
- **STOP if > 20%** of realistic intents require geometry the templates cannot parameterize
  (forcing LLM-authored code). → The safety inversion doesn't hold: **narrow the domain** or
  knowingly accept RCE (not acceptable for the product → narrow scope).

**Part B — sandbox containment (hard STOP):** containment fails (nothing ships) if **any** of:
- the host **cannot kill a spinning, uninterruptible C++ OCCT boolean** within the deadline via a
  host-side wall-clock `SIGKILL` (NOT a Python try/except — those don't catch `Standard_Failure` /
  access violations), **OR**
- warm snapshot-restore latency **> ~250 ms** (⚠️ treat as a hypothesis to measure, not a given —
  a large Python+OCCT memory footprint may not fit this; see risk), **OR**
- **egress is not fully denied** (a key-read / outbound-socket attempt succeeds).

## Method / protocol

**Part A:**
1. Define the `ParameterDelta` Pydantic schema (the *only* legal LLM emission).
2. Build a Jinja2 template library covering real wedge vocab: skin/rib thickness, pin dia,
   fastener pocket, slip-fit cutout, sectional split, lip-and-groove. (Aerospace-only vocab like
   airfoil/wingspan can be included to stress the vocabulary but is out of the wedge.)
3. Bind Sonnet to the schema with `tool_choice` forced + `strict:true`; feed 30 intents; classify
   each fully-expressible / partial / inexpressible.

**Part B:**
1. Run a known-degenerate OCCT boolean that spins uninterruptibly; assert host wall-clock SIGKILL
   reaps it within deadline.
2. Attempt env-var key read + outbound socket from inside the sandbox; assert both blocked
   (egress-deny netns, dropped caps, RLIMIT_AS/CPU).
3. Measure warm snapshot-restore latency over N cold/warm cycles.

## Claude's role

- **Runtime:** Sonnet 4.6 bound to the strict tool-use Pydantic schema (the schema IS the only
  boundary); a **rules-only validator (not an LLM)** clamps bounds/locks.
- **Dev-time:** Claude builds the template library + the gVisor/Firecracker harness AND generates a
  **prompt-injection red-team corpus** (poisoned airfoil strings, malicious `.dat` imports,
  jailbreak intents) as a *repeatable eval*, not a one-off.

> ⚠️ Forced/strict tool use guarantees output *shape*, not uncoercibility. A finite red-team corpus
> can only fail to find an exploit — it cannot *prove* the system can't be coerced. Keep it as a
> permanent regression eval; the injection surfaces (poisoned `.dat`, router glue, retrieval path)
> stay live threats.

## Risks specific to this spike

- **Substrate:** Firecracker needs Linux+KVM; gVisor is Linux. Not runnable on the Windows dev box
  as written — needs the standardized Linux dev container (Phase 0 §3c).
- **250 ms budget** may be inconsistent with restoring a large Python+OCCT memory image *and* then
  running a boolean the plan itself bounds at "100 ms–seconds." Measure honestly.

## Results (fill in)

| Field | Value |
|-------|-------|
| Intents fully expressible as deltas | _TBD_ / 30 (threshold: ≥80%) |
| Inexpressible intents | _TBD_ (list them) |
| Wall-clock SIGKILL reaps spinning boolean? | _yes/no, latency_ |
| Egress fully denied? | _yes/no_ |
| Warm restore latency | _TBD ms_ (threshold: <250 ms) |
| **Classification** | _PASS / FALLBACK / STOP_ |
| Decision & rationale | _TBD_ |

# Technical Addendum & Implementation Blueprint: AI-Guided Hardware Co-Modeling Platform

> **2026-07-02 — Schema shape revised.** The `domains` node no longer holds a typed block per part.
> Disciplines (structure/manufacturing/thermal) stay typed; **per-part geometry lives in a generic
> `domains.geometry: dict[str, ParameterDef]` bag** keyed by param name. Each subsystem declares its
> params ONCE via a `ParamSpec` list; ledger paths become `domains.geometry.<name>`. This makes
> adding a subsystem one small self-contained file (no central schema edit). Full record and rationale:
> [`build-plan/reference/SCALABLE_SUBSYSTEM_REFACTOR.md`](../build-plan/reference/SCALABLE_SUBSYSTEM_REFACTOR.md).
> The typed-per-part schema below is the ORIGINAL vision — preserved for history.

## 1. Master Parametric Ledger JSON Schema

This schema defines the single source of truth (`Agnostic Meta-Graph`) for the vehicle state, decoupling design intent from physical mesh generation.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "MasterParametricLedger",
  "type": "object",
  "required": ["project_metadata", "global_constraints", "domains"],
  "properties": {
    "project_metadata": {
      "type": "object",
      "required": ["project_id", "version_commit", "branch"],
      "properties": {
        "project_id": { "type": "string" },
        "version_commit": { "type": "string" },
        "branch": { "type": "string" }
      }
    },
    "global_constraints": {
      "type": "object",
      "required": ["target_range_km", "cruise_speed_kmh", "factor_of_safety"],
      "properties": {
        "target_range_km": { "type": "number" },
        "cruise_speed_kmh": { "type": "number" },
        "factor_of_safety": { "type": "number", "minimum": 1.0 }
      }
    },
    "domains": {
      "type": "object",
      "required": ["aerodynamics", "structure", "power_matrix", "landing_gear"],
      "properties": {
        "aerodynamics": {
          "type": "object",
          "properties": {
            "wingspan_mm": {
              "type": "object",
              "required": ["value", "lock_state"],
              "properties": {
                "value": { "type": "number" },
                "lock_state": { "type": "string", "enum": ["DYNAMIC", "HARD_LOCK"] },
                "bounds": {
                  "type": "array",
                  "items": { "type": "number" },
                  "minItems": 2,
                  "maxItems": 2
                }
              }
            },
            "airfoil_profile": { "type": "string" }
          }
        },
        "structure": {
          "type": "object",
          "properties": {
            "material_profile": { "type": "string" },
            "skin_thickness_mm": { "type": "number" },
            "internal_rib_spacing_mm": { "type": "number" }
          }
        },
        "power_matrix": {
          "type": "object",
          "properties": {
            "cell_type": { "type": "string" },
            "configuration": { "type": "string" },
            "total_cells": { "type": "integer" }
          }
        },
        "landing_gear": {
          "type": "object",
          "properties": {
            "front_pivot_pin_dia_mm": {
              "type": "object",
              "required": ["value", "lock_state"],
              "properties": {
                "value": { "type": "number" },
                "lock_state": { "type": "string", "enum": ["DYNAMIC", "HARD_LOCK"] },
                "bounds": { "type": "array", "items": { "type": "number" } }
              }
            }
          }
        }
      }
    }
  }
}

```

---

## 2. Core API Contracts & Event Architecture

The system communicates through lightweight state transitions and delta events over bidirectional transport interfaces.

### 2.1 Delta Event Mutator (Client → Server via WebSocket)

Sent whenever a user interacts with a bounded slider in the floating 3D HUD or side drawer.

```json
{
  "event_type": "PARAMETER_MUTATION_REQUEST",
  "timestamp": "2026-06-27T20:45:00Z",
  "payload": {
    "target_node": "domains.landing_gear.front_pivot_pin_dia_mm",
    "requested_value": 4.5,
    "set_lock": "HARD_LOCK"
  }
}

```

### 2.2 System Cascade Response (Server → Client via WebSocket)

Sent after the local background solver evaluates downstream physics and re-slices components.

```json
{
  "event_type": "PARAMETER_CASCADE_UPDATE",
  "timestamp": "2026-06-27T20:45:02Z",
  "payload": {
    "mutations_applied": [
      { "node": "domains.landing_gear.front_pivot_pin_dia_mm.value", "value": 4.5 },
      { "node": "domains.landing_gear.front_pivot_pin_dia_mm.lock_state", "value": "HARD_LOCK" }
    ],
    "cascades_applied": [
      { "node": "domains.structure.knuckle_wall_thickness_mm", "value": 2.2, "reason": "Structural thickening for 4.5mm pin" }
    ],
    "telemetry_delta": {
      "total_mass_g": 4650,
      "estimated_print_time_seconds": 151920,
      "cg_position_mac_percent": 34.2
    }
  }
}

```

---

## 3. Phased Implementation Milestones

```
[ Phase 1: Engine Foundation ] ──► [ Phase 2: AI Optimization Loop ] ──► [ Phase 3: Interactive UI Runtime ]
 (Local build123d + Ledger)           (Multi-Agent API + Slicer CLI)         (WebGL Viewport + HUD Elements)

```

### Phase 1: Core Compiler Foundation & Architecture (Weeks 1–4)

* Implement the local headless `build123d` geometric compilation pipeline.
* Build the local deterministic state machine that consumes the Master Parametric Ledger JSON.
* Establish file boundaries and automated slicing routines (lip-and-groove logic) inside the geometric builder.

### Phase 2: AI Synthesis & Slicer Optimization Loop (Weeks 5–8)

* Setup the multi-agent LLM orchestration layers (Strategic, Geometric, Validation).
* Connect the execution pipeline to headless open-source slicer engines via CLI handles to pull real-time print metrics.
* Deploy the continuous optimization loop monitoring weight and print-time targets ($I_{n} - I_{n-1} < 0.1\text{g}$).

### Phase 3: Interactive UI Layer Deployment (Weeks 9–12)

* Assemble the split-pane front-end framework.
* Map WebGL object selection paths to trigger context-aware floating HUD elements over specific component nodes.
* Connect the bidirectional WebSocket event loop to allow synchronized variable sliders to shift geometry smoothly.

---

## 4. Platform Success Metrics & Guardrails

### 4.1 System Performance Targets

* **Local Re-Compilation Latency:** Isolated sub-assembly parameter updates (e.g., thinning a local hinge pin bracket) must compile and push structural delta meshes to the viewport in under **150ms**.
* **Global Optimization Convergence:** Massive system balance tasks (e.g., rearranging the internal 21700 cell layout across the entire fuselage core) must resolve its multi-variable Pareto loop within **15 seconds**.
* **Telemetry Sync Overhead:** Real-time updates to the lower floor rail HUD metrics (Mass, Center of Gravity, Slicer time estimations) must run at **30Hz** during slider manipulation.

### 4.2 Engineering Safety Guardrails

* **The Structural Floor:** The system validation layer will block any model execution if an optimization step or user manual slider interaction drops the structural Factor of Safety ($FS$) below **$1.5$** or your explicit design target baseline.
* **The Aerospace Horizon:** If user-enforced structural selections (`HARD_LOCK` configurations) degrade flight aerodynamics to the point where your critical mission profile fails (e.g., range drops below 100km or stall speed exceeds acceptable runway limits), the telemetry HUD must flag a **Red Constraint Violation**, preventing physical export until resolved.
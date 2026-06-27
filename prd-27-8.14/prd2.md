## Product Requirements Document 2: AI Intelligence System, Skills & Token Planning

### 1. Orchestration Layer & Multi-Agent Specialization

The intelligence framework leverages specialized computational competencies to manage the design. Instead of handling everything in a single, open-ended context window, the problem is divided into discrete, targeted reasoning fields:

* **The Strategic Systems Engineer (Macro Layer):** Interprets high-level user goals (e.g., a 1000km range target using pure electric batteries). It translates these goals into physical constraints, maps the required airspeed profiles, determines the necessary high-altitude cruise strategy, and updates the core parameter matrix.
* **The Geometric Code Generator (Micro Layer):** Translates optimized system parameters into clean, precise `build123d` Python scripts. It interfaces directly with the shape kernel to create or modify local solid bodies.
* **The Structural Validator (Verification Layer):** Serves as an algorithmic gatekeeper. It runs background cross-checks on the geometry, evaluating local factor-of-safety margins, aeroelastic flutter limits, and mechanical clearance boundaries.

---

### 2. Analytical Intelligence & Objective Optimization

The system handles structural design through a multi-variable **Pareto Frontier** optimization loop. It continuously refines shapes by balancing performance boundaries against real-world limitations.

```
[ New State Matrix ] ──> [ FEA/Load Check ] ──> [ Slicer Validation ] ──> [ Convergence Check ]
                                                                                   │
       ┌─────────────────────────────── No ────────────────────────────────────────┘
       ▼
[ Iterate Shaving/Ribs ] ──> Loop Continues
       │
       ├─► Yes (Change < 0.1g) ──> [ Break Loop & Render to Viewport ]

```

#### 2.1 Weight & Strength Optimization Loop

The validation engine continuously runs rapid structural estimations on active components.

* **Load Path Tracing:** The AI maps expected flight bending moments and high-altitude aerodynamic twisting forces. It dynamically thins low-stress solid segments while adding rigid internal ribs to high-stress vectors.
* **Convergence Termination:** To prevent infinite compute loops when reducing weight, the engine evaluates the rate of weight change between cycles. The loop automatically breaks once the difference drops below a specific tolerance threshold ($\Delta W < 0.1\text{g}$), locking in the shape as numerically optimal.

#### 2.2 Manufacturing Optimization Loop

The intelligence engine adapts shapes specifically for efficient production.

* **Supportless Overhang Enforcement:** The geometric generator evaluates surface angles relative to the target print bed plane. It dynamically limits overhanging geometry to a maximum of $45^\circ\text{ to }50^\circ$, completely eliminating the print time and material waste of external breakaway supports.
* **Toolpath Optimizations:** For aerodynamic skins, the script coordinates directly with background slicer parameters to ensure continuous toolpaths (such as single-wall spiral extrusions), slicing assembly production times significantly.

---

### 3. Context & Token Management Strategy

Managing large-scale CAD files alongside live conversational interfaces requires aggressive token budgeting to prevent layout lag or context collapse.

* **JSON Graph Hydration:** Instead of constantly parsing raw text representations of 3D meshes or code blocks in the chat history, the chat context only retains the lightweight **Master Parametric Ledger JSON**.
* **Semantic Compaction:** Prior conversation histories are continuously summarized into structured "Design State Commits." Old, discarded code iterations are systematically stripped from the active context window, while the current physical boundaries are preserved as compact data nodes.

---

## Product Requirements Document 3: Contextual User Interface & Version Ledger

### 1. Workspace Philosophy

The platform workspace abandons the tool-heavy, spreadsheet-cluttered interface of legacy CAD in favor of a content-first **Split-Pane Design Environment**. The UI surfaces data only when it is contextually relevant, keeping the focus entirely on the physical product.

---

### 2. The Clean-Slate Workspace (Three-Zone Layout)

The visual interface is organized into three distinct operational regions:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [Project Horizon] v2.4.1 (Branch: strato-cruiser)       [Generate G-Code]│
├───────────────────────┬──────────────────────────────────────────────────┤
│                       │                                                  │
│                       │                                                  │
│   1. CONVERSATION     │             2. HIGH-PERFORMANCE                  │
│       SIDEBAR         │                 3D VIEWPORT                      │
│    (Intent Deck)      │               (80% Canvas)                       │
│                       │                                                  │
│                       │        ┌─────────────────────────┐               │
│                       │        │ 🔩 Pivot Pin Override   │               │
│                       │        ├─────────────────────────┤               │
│                       │        │ Dia:  ──●── 4.5mm [🔒]  │               │
│                       │        └─────────────────────────┘               │
│                       │                                                  │
├───────────────────────┴──────────────────────────────────────────────────┤
│ 3. REAL-TIME TELEMETRY HUD: CG: 34.2% MAC | Mass: 4.65kg | Print: 42h12m │
└──────────────────────────────────────────────────────────────────────────┘

```

#### 2.1 The Conversation Sidebar (Left 20%)

A streamlined interaction panel for entering design goals and viewing system logs. It displays high-level structural reasonings in clean, collapsible windows, keeping code execution hidden unless explicitly requested.

#### 2.2 The High-Performance 3D Viewport (Right 80%)

A hardware-accelerated WebGL workspace running a read-only representation of the product geometry.

* **No Direct Mesh Editing:** Users cannot manually grab vertices, warp lines, or manipulate surfaces. This protects the mathematical integrity of the underlying scripts.
* **Selection & Translucency:** Hovering over the workspace highlights distinct structural assemblies. Clicking an asset activates **Ghost Mode**, dropping the rest of the airframe to a 30% translucent opacity to expose internal clearance channels, spar placements, and mechanical paths.

#### 2.3 The Floating Contextual HUD

When a component is clicked inside the 3D viewport, a lightweight, floating micro-panel anchors itself directly to the coordinate space next to the cursor.

* **Exposed Bounded Sliders:** It surfaces only 1 to 3 critical driving parameters for that specific component (e.g., joint thickness or bracket length).
* **Hardware Safety Guards:** The sliders are physically bounded by the AI based on backend rules. A user can adjust the value within a safe operating window, but cannot push the slider past structural or clearance limits.
* **Hard-Lock Toggle:** Includes an inline lock icon. Toggling it freezes the value, changing its state to a permanent user constraint.

#### 2.4 The Slide-Out Drawer Panel

Docked as a thin vertical strip of icons on the right edge of the screen, clicking any icon slides open an engineering drawer. This drawer contains the full hierarchical system variable tree for macro-adjustments and detailed property tracing.

#### 2.5 The Real-Time Telemetry HUD (Floor Rail)

A low-profile persistent dashboard running along the bottom edge of the workspace canvas, outputting instantaneous calculations updated via fast local background scripts:

* **Center of Gravity (CG) Status:** A live horizontal bar charting static safety margins. It flashes amber if an adjustment pushes the layout into an unstable configuration.
* **Mass Budget Matrix:** A real-time breakdown of structural, payload, and power storage weight distributions.
* **Manufacturing Output Estimator:** Provides a direct, headless connection to the slicing engine to calculate total fabrication hours and material volume requirements instantly.
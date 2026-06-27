# packages/transport — placeholder (Phase 1)

The two-plane WebSocket protocol: binary MessagePack frames, geometry as Draco/meshopt glTF, the
three-tier wire contract (PARAM_MUTATION / PREVIEW_DELTA@30Hz / KERNEL_REGEN_COMPLETE / SOLVER_RESULT
with correlation IDs) **plus the NACK/rejection path the original PRD lacked** (what the server sends
when a mutation violates the FS floor or a HARD_LOCK). Do not build until Phase 1 — empty for now.

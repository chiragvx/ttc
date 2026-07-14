// Mirrors packages/transport/app.py::_instance_id_from_target — `instances.<id>.params.<name>` -> <id>;
// anything else (a discipline/cross-cutting path) -> null. Used to drive the chat's hover-highlight:
// a parameter delta targeting an instance's own param highlights that instance, same as an outliner row.
export function instanceIdFromNode(node: string): string | null {
  const parts = node.split(".");
  if (parts.length === 4 && parts[0] === "instances" && parts[2] === "params") return parts[1];
  return null;
}

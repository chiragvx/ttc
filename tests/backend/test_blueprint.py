"""Blueprint 3-view renderer (2026-07-19) — packages/truth_plane/regen/blueprint.py + GET /blueprint.

The foundational piece of the self-verifying build-loop harness: a labelled orthographic 3-view PNG
of the whole assembly, for the user and (later) the vision-validation step."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from packages.transport.app import create_app

HAS_B123D = importlib.util.find_spec("build123d") is not None
HAS_MPL = importlib.util.find_spec("matplotlib") is not None

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

pytestmark = pytest.mark.skipif(not (HAS_B123D and HAS_MPL), reason="needs build123d + matplotlib")


def _client():
    return TestClient(create_app())


def test_blueprint_empty_file_returns_a_placeholder_png():
    c = _client()
    r = c.get("/blueprint")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(_PNG_MAGIC)


def test_blueprint_renders_a_multi_part_assembly_png():
    c = _client()
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bwb_fuselage"})
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel",
                                   "x_mm": 250, "y_mm": 67, "z_mm": 8.7})
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel",
                                   "x_mm": -250, "y_mm": 67, "z_mm": 8.7})
    r = c.get("/blueprint")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(_PNG_MAGIC)
    # a real 3-part drawing is materially bigger than the empty placeholder
    assert len(r.content) > 20_000


def test_render_blueprint_returns_png_bytes_directly():
    from packages.truth_plane.regen.blueprint import render_blueprint
    from packages.transport.app import make_demo_ledger
    from packages.subsystems import add_instance

    led = make_demo_ledger()
    led = add_instance(led, "bracket", "b1")
    png = render_blueprint(led, title="test")
    assert isinstance(png, (bytes, bytearray))
    assert png.startswith(_PNG_MAGIC)


def test_a_broken_instance_is_skipped_not_fatal():
    # defensive: one instance whose build raises must not blank the whole drawing (same stance as
    # assembly.render_assembly) — the render still returns a valid PNG with the healthy part drawn.
    from packages.truth_plane.regen.blueprint import render_blueprint
    from packages.transport.app import make_demo_ledger
    from packages.subsystems import add_instance

    led = make_demo_ledger()
    led = add_instance(led, "bracket", "ok1")
    led = add_instance(led, "wing_panel", "boom1")
    # corrupt one instance so its builder hits a degenerate/missing-param path and raises
    led.instances["boom1"].params.clear()

    png = render_blueprint(led, title="resilience")
    assert png.startswith(_PNG_MAGIC)

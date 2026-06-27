# Convenience targets. Host targets (test/probe/fingerprint) run anywhere with Python+pydantic.
# Kernel/solver targets need the Linux image (docker/Dockerfile.dev).

IMAGE ?= gtc-dev

.PHONY: test probe fingerprint image shell ci ci-determinism spike4-smoke

# --- host (runs on the Windows dev box too) ---
test:
	python -m pytest -q -ra

probe:
	python -m packages.truth_plane.regen.probe 4.5

fingerprint:
	python scripts/toolchain_fingerprint.py --json

# --- Linux kernel/solver image ---
image:
	docker build -f docker/Dockerfile.dev -t $(IMAGE) .

shell: image
	docker run --rm -it $(IMAGE) bash

ci: image
	docker run --rm $(IMAGE) python -m pytest -q -ra

# Print the canonical mesh hash + portable fingerprint from inside the Linux image,
# to compare against the Windows values (see docker/README.md).
ci-determinism: image
	docker run --rm $(IMAGE) sh -c "\
	  python scripts/toolchain_fingerprint.py --portable && \
	  python -m packages.truth_plane.regen.probe 4.5"

# Smoke-check the solver chain is wired (Spike 4 groundwork): build123d -> gmsh -> ccx present.
spike4-smoke: image
	docker run --rm $(IMAGE) sh -c "ccx 2>&1 | head -1; python -c 'import gmsh; print(\"gmsh\", gmsh.__version__)'"

# App image — builds the SPA, then a Python runtime (build123d+gmsh+CalculiX) that serves the API +
# the built SPA from one origin, and can also run the Dramatiq worker. Used by docker-compose.

# --- frontend build ---
FROM node:22-slim AS frontend
WORKDIR /fe
COPY packages/frontend/package.json packages/frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY packages/frontend/ ./
RUN npm run build

# --- backend runtime (mirrors docker/Dockerfile.dev kernel libs, + serve/worker + SPA) ---
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        calculix-ccx ca-certificates libgomp1 \
        libgl1 libglu1-mesa libfontconfig1 \
        libx11-6 libxext6 libxrender1 libxfixes3 libxcursor1 libxinerama1 \
        libxft2 libxrandr2 libxi6 libxmu6 libsm6 libice6 \
    && rm -rf /var/lib/apt/lists/*

ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY constraints/kernel-linux.txt constraints/kernel-linux.txt
RUN pip install --upgrade pip && pip install -r constraints/kernel-linux.txt
COPY . .
RUN pip install -e ".[serve,worker]"
COPY --from=frontend /fe/dist /app/packages/frontend/dist

EXPOSE 8000
CMD ["uvicorn", "packages.transport.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

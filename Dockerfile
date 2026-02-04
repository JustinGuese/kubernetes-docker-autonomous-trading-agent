# Slim base — browser runs in a sidecar, not here
FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project metadata + lockfile for layer caching
COPY pyproject.toml uv.lock ./

# Install runtime deps (no dev extras)
RUN uv sync --no-dev

# Copy source
COPY core/         core/
COPY tools/        tools/
COPY policies/     policies/
COPY experiments/  experiments/
COPY main.py       main.py

# Activate the uv-created venv
ENV PATH=/app/.venv/bin:$PATH

# Run-once-and-exit
ENTRYPOINT ["python", "main.py"]

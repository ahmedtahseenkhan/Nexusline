FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Release images enforce the license; pass --build-arg PRODUCTION_BUILD=false to
# build an unenforced image for local development.
ARG PRODUCTION_BUILD=true

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install -e .

# Remaining project files (alembic config, migrations, etc.)
COPY . .

# Stamp the enforcement flag into the image. Must come after the COPY above,
# which would otherwise restore the unstamped build.py from the build context.
# The greps are the point: a silently failed sed would ship a client an image
# that never checks its license.
RUN set -eu; \
    if [ "$PRODUCTION_BUILD" != "true" ]; then exit 0; fi; \
    if ! grep -q 'BEGIN PUBLIC KEY' app/core/build.py; then \
      echo "BUILD FAILED: no vendor key embedded. Run: python -m app.tools.license keygen" >&2; \
      exit 1; \
    fi; \
    sed -i 's/^PRODUCTION_BUILD = False$/PRODUCTION_BUILD = True/' app/core/build.py; \
    grep -qx 'PRODUCTION_BUILD = True' app/core/build.py

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

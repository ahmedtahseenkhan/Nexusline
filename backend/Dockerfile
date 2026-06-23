FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install -e .

# Remaining project files (alembic config, migrations, etc.)
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

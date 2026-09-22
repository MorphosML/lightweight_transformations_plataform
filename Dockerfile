FROM python:3.12-slim

# Install system dependencies and Java (required for local PySpark execution)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    default-jre-headless \
    procps \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files first for optimal Docker layer caching
COPY pyproject.toml README.md /app/

# Install python packages with Spark support
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e '.[all]'

# Copy application source code
COPY src /app/src
COPY tests /app/tests

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "openflow_api.app:app", "--host", "0.0.0.0", "--port", "8000"]


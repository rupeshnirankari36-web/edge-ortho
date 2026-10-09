# Multi-stage Edge-Ortho Dockerfile
FROM python:3.12-slim-bookworm

# System dependencies for GDAL, OpenCV headless, and ExifTool
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    libgl1 \
    libglib2.0-0 \
    exiftool \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications first for Docker layer caching
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY configs/ ./configs/
COPY profiles/ ./profiles/

# Install edge-ortho package
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[dev]"

# Create mount points for data and outputs
RUN mkdir -p /app/data /app/outputs

ENTRYPOINT ["edge-ortho"]
CMD ["--help"]

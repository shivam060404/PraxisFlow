# Backend Production Dockerfile
# Multi-stage build for production

# ─── Builder Stage ───
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Generate Prisma client
COPY prisma/ ./prisma/
RUN prisma generate

# ─── Runtime Stage ───
FROM python:3.12-slim AS runtime

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r praxisflow && useradd -r -g praxisflow -u 1000 praxisflow

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/praxisflow/.local

# Copy Prisma client
COPY --from=builder /app/prisma ./prisma/

# Copy application code
COPY --chown=praxisflow:praxisflow app/ ./app/

# Create directories
RUN mkdir -p /app/logs /app/uploads /app/tmp && chown -R praxisflow:praxisflow /app

# Switch to non-root user
USER praxisflow

# Add local packages to PATH
ENV PATH=/home/praxisflow/.local/bin:$PATH

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
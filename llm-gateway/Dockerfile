# LLM Gateway Dockerfile
# Multi-stage build for production-ready LiteLLM Proxy

# ─── Build Stage ───
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

# ─── Runtime Stage ───
FROM python:3.12-slim AS runtime

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r litellm && useradd -r -g litellm -u 1000 litellm

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/litellm/.local

# Copy configuration
COPY litellm_config.yaml /app/litellm_config.yaml
COPY routing_policies.yaml /app/routing_policies.yaml

# Create directories for logs and cache
RUN mkdir -p /app/logs /app/cache && chown -R litellm:litellm /app

# Switch to non-root user
USER litellm

# Add local packages to PATH
ENV PATH=/home/litellm/.local/bin:$PATH

# Environment variables
ENV LITELLM_CONFIG=/app/litellm_config.yaml
ENV LITELLM_ROUTING_POLICIES=/app/routing_policies.yaml
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:4000/health/liveliness || exit 1

# Expose ports
EXPOSE 4000 4001

# Entry point
ENTRYPOINT ["litellm"]
CMD ["--config", "/app/litellm_config.yaml", "--host", "0.0.0.0", "--port", "4000", "--num-workers", "4"]
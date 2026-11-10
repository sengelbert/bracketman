# Containerfile for Bracketman - Localhost Deployment
FROM python:3.12-slim

# Install curl for container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency configuration
COPY pyproject.toml README.md ./
COPY requirements.txt ./

# Copy application source and assets
COPY src/ ./src/
COPY assets/ ./assets/
COPY configs/ ./configs/
COPY data/ ./data/
COPY .streamlit/ ./.streamlit/

# Install bracketman
RUN pip install --no-cache-dir .

# Create volume mount points for tournament data and exports
RUN mkdir -p /app/data/tournaments /app/output

EXPOSE 8503

# Health check against Streamlit health endpoint
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8503/_stcore/health || exit 1

ENTRYPOINT ["bracketman", "ui", "--headless", "--host", "0.0.0.0", "--port", "8503"]

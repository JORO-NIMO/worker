# Multi-stage lightweight production image for Autonomous Worker
FROM python:3.12-slim

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKER_CONFIG_PATH=/var/www/worker/config.json
ENV WORKER_DB_PATH=/var/www/worker/data/worker.db

# Install system dependencies needed for git, security tools, and proc inspection
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    procps \
    openssh-client \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /var/www/worker

# Copy dependency requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure data and logs directories exist and scripts are executable
RUN mkdir -p /var/www/worker/data /var/www/worker/logs && \
    chmod +x /var/www/worker/bin/* /var/www/worker/docker-entrypoint.sh

# Expose Dashboard & Agent Port
EXPOSE 8888

# Healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8888/login || exit 1

ENTRYPOINT ["/var/www/worker/docker-entrypoint.sh"]
CMD ["run-all"]

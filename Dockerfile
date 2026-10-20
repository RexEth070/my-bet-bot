# Lightweight Python 3.12 container for 24/7 cloud hosting
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Africa/Lagos

WORKDIR /app

# Install system dependencies (tzdata for African timezone scheduling)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose port for cloud health checks (Render, Koyeb, etc.)
EXPOSE 8080

# Health check command
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Run the Telegram bot
CMD ["python", "main.py"]

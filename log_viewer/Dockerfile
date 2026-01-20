FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (including curl for healthcheck)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create application structure
# Note: logs directory will be mounted from host, but create placeholder
RUN mkdir -p logs templates static

# Copy application files to correct locations
COPY app/log_viewer.py ./app/
COPY app/templates/ ./app/templates/
COPY app/static/ ./app/static/

# Create non-root user for security and set proper permissions
RUN useradd -m -u 1000 logviewer && \
    chown -R logviewer:logviewer /app

# Switch to non-root user
USER logviewer


HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${LOG_VIEWER_PORT}/health || exit 1

# Run the application
CMD ["python", "app/log_viewer.py"]
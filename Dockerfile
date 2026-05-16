# Use official Python runtime as base image
FROM python:3.13-slim

# Install system dependencies for Playwright and Chromium
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libxss1 \
    libasound2 \
    libxrandr2 \
    libxinerama1 \
    libgtk-3-0 \
    libgbm1 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxfixes3 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (chromium needed for scraper)
RUN playwright install chromium

# Copy project files
COPY . .

# Expose port 8080 (Cloud Run requirement)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/ui || exit 1

# Run the FastAPI app with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

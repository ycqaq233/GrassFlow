FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Install grassflow package
RUN pip install -e .

# Create config directory
RUN mkdir -p ~/.Grass/workflows

# Default entry point
ENTRYPOINT ["python", "-m", "tui.cli"]
CMD ["repl"]

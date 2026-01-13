# Multi-Stage Dockerfile for agentic-consult

# --- Base Stage (Shared Dependencies) ---
FROM python:3.11-slim as base
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy the entire monorepo
COPY . .

# Install the internal package + email-archive SDK
# Using git install for email-archive until it's a peer package
RUN pip install "email-archive @ git+https://github.com/krisrowe/gmail-extractor.git#subdirectory=email-archive"
RUN pip install -e .

# --- Analyzer Stage ---
FROM base as analyzer
# Default command: perform one-shot analysis
CMD ["python", "-m", "agentic_consult.email.analyzer"]

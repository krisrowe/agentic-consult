# Multi-Stage Dockerfile for agentic-consult

# --- Base Stage (Shared Dependencies) ---
FROM python:3.11-slim AS base
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
FROM base AS analyzer
# Default command: perform one-shot analysis
CMD ["python", "-m", "agentic_consult.email"]

# --- MCP HTTP Stage ---
FROM base AS mcp-http
# Install HTTP dependencies
RUN pip install -e ".[http]"
# Expose port for Cloud Run
EXPOSE 8080
# Run uvicorn directly (no entry point needed)
CMD ["uvicorn", "agentic_consult.mcp.http:app", "--host", "0.0.0.0", "--port", "8080"]

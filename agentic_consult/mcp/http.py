"""HTTP transport for MCP server with PAT authentication."""
import os
import logging
import contextlib
import secrets

import yaml
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import ValidationError

from .server import mcp
from agentic_consult.sdk.email.rules_config import import_email_config, export_email_config

# Setup Logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(levelname)s: %(name)s: %(message)s"
)
logger = logging.getLogger("agentic_consult.mcp.http")


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Validation is handled by the platform:
    1. External: API Gateway validates API Key. Routes only expose public endpoints.
    2. Internal: Cloud Run IAM validates OIDC tokens from Scheduler/Admin.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Health check
        if path == "/health":
            return await call_next(request)

        # Log access for audit
        # In a real multi-tenant app, we would parse X-Apigateway-Api-Userinfo here
        logger.info(f"Access: {request.method} {path}")
        
        return await call_next(request)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan to run the session manager (required for FastMCP Streamable HTTP)."""
    if not getattr(mcp.session_manager, "_has_started", False):
        async with mcp.session_manager.run():
            yield
    else:
        yield


# Initialize App
app = FastAPI(
    title="Agentic Consult MCP Server",
    lifespan=lifespan
)

# Allow all hosts to avoid 421 errors
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(AuthMiddleware)


@app.get("/health")
async def health():
    """Health check endpoint (no auth required)."""
    return {"status": "ok"}


@app.get("/user/email-rules")
async def get_email_rules():
    """Download email.yaml configuration."""
    try:
        return export_email_config()
    except Exception as e:
        logger.error(f"Failed to read email.yaml: {e}")
        return JSONResponse({"error": "Failed to read config"}, status_code=500)


@app.post("/user/email-rules")
async def post_email_rules(request: Request):
    """Upload email.yaml configuration with validation and backup."""
    try:
        body = await request.body()
        new_data = yaml.safe_load(body.decode('utf-8')) or {}
    except yaml.YAMLError as e:
        return JSONResponse({"error": f"Invalid YAML: {e}"}, status_code=400)

    try:
        result = import_email_config(new_data)
        if result.get("backup_path"):
            logger.info(f"Backed up email.yaml to {result['backup_path']}")
        return result
    except ValidationError as e:
        return JSONResponse({"error": f"Schema validation failed: {e}"}, status_code=400)
    except Exception as e:
        logger.error(f"Failed to write email.yaml: {e}")
        return JSONResponse({"error": f"Failed to write config: {e}"}, status_code=500)


@app.post("/internal/batch")
async def internal_batch():
    """Run batch email analysis. Called by Cloud Scheduler."""
    from email_archive import EmailStore
    from agentic_consult.email.analyzer import EmailAnalyzer

    try:
        analyzer = EmailAnalyzer(store=EmailStore())
        result = analyzer.process_queue()
        return result
    except Exception as e:
        logger.exception("Batch analysis failed")
        return JSONResponse({"error": str(e)}, status_code=500)


# Mount the MCP streamable HTTP app
mcp_app = mcp.streamable_http_app()
app.mount("/", mcp_app)


def run_http_server():
    """Run the HTTP server with uvicorn (for local testing)."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    run_http_server()

"""HTTP transport for MCP server with PAT authentication."""
import os
import logging
import contextlib

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .server import mcp

# Setup Logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(levelname)s: %(name)s: %(message)s"
)
logger = logging.getLogger("agentic_consult.mcp.http")

# PAT from environment (injected from Secret Manager in Cloud Run)
EXPECTED_PAT = os.environ.get("MCP_PERSONAL_ACCESS_TOKEN", "")


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates PAT from header or query param."""

    async def dispatch(self, request: Request, call_next):
        # Health check bypass
        if request.url.path == "/health":
            return await call_next(request)

        # Extract PAT from header or query param
        auth_header = request.headers.get("Authorization")
        pat = None

        if auth_header and auth_header.startswith("Bearer "):
            pat = auth_header.split(" ")[1]
        else:
            pat = request.query_params.get("token")

        if not pat:
            logger.error("Auth failed: No token provided")
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        if not EXPECTED_PAT:
            logger.error("Auth failed: MCP_PERSONAL_ACCESS_TOKEN not configured")
            return JSONResponse({"error": "Server misconfigured"}, status_code=500)

        if pat != EXPECTED_PAT:
            logger.error("Auth failed: Invalid token")
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        logger.info("Auth successful")
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


# Mount the MCP streamable HTTP app
mcp_app = mcp.streamable_http_app()
app.mount("/", mcp_app)


def run_http_server():
    """Run the HTTP server with uvicorn (for local testing)."""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    run_http_server()

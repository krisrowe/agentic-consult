# Cloud Deployment Design

Architecture and design rationale for the cloud deployment system.

For operational commands and usage, see [README.md](README.md).

## Overview

The email triage system uses a **Private Cloud Run** backend fronted by a **Public API Gateway**.

```
  INTERNET                                  GCP PROJECT (Private Network)
┌──────────┐                            ┌──────────────────────────────┐
│  Client  │  https://gateway/sse?key=X │                              │
│ (Claude/ │ ──────────────────────────►│        API Gateway           │
│  Gemini) │                            │      (Public Facade)         │
└──────────┘                            └──────────────┬───────────────┘
                                                       │
                                                       │ (OIDC Auth)
                                                       ▼
┌──────────┐                            ┌──────────────────────────────┐
│  Cloud   │                            │         consult-mcp          │
│ Scheduler│ ──────────────────────────►│     (Cloud Run Service)      │
│          │        (OIDC Auth)         │          [PRIVATE]           │
└──────────┘                            └──────────────────────────────┘
```

### Security Layers

1.  **Public Access (API Gateway):**
    *   **Mechanism:** API Key validation (`?key=AIza...`).
    *   **Access:** Only clients with a valid API Key can pass the gateway.
    *   **Routes:** Only `/sse` and `/messages` are exposed. Internal paths are blocked.

2.  **Service Access (Cloud Run):**
    *   **Mechanism:** IAM (`roles/run.invoker`).
    *   **Access:** Only the **API Gateway Service Account** and **Cloud Scheduler Service Account** have permission to invoke the container. Direct internet access is denied.

3.  **Application Access (Code):**
    *   **User Endpoints:** Trusted (if they pass Gateway).
    *   **Internal Endpoints:** Trusted (if they pass IAM).

## Repository Responsibilities

| Repo | Artifact | Responsibility |
|------|----------|----------------|
| `gmail-extractor` | `gcr.io/.../gmex-fetcher` | Fetch emails from Gmail |
| `agentic-consult` | `gcr.io/.../consult-mcp` | MCP server logic |
| `agentic-consult` | Terraform + CLI | Deploy and manage infrastructure |

## Deployment Automation (`./cloud deploy`)

The deployment script is a "Zero-Install" bridge between GitHub (Source) and GCP (Run).

1.  **Identity:** Automatically uses the `terraform-deployer` Service Account (setup via `init`).
2.  **Image Transfer:**
    *   Checks if target image exists in GCR/Artifact Registry.
    *   If missing, checks GitHub Container Registry (GHCR).
    *   **Bridge:** Triggers **Cloud Build** to pull from GHCR and push to GCR.
    *   **Optimization:** Waits for GitHub Actions to finish building the image before transferring.
3.  **Terraform:**
    *   Runs `terraform apply` using the specific git SHA as the image tag.
    *   Updates Cloud Run, API Gateway, and Scheduler.

## User Authentication Flow

**Admin Persona (Cloud Owner):**
1.  Runs `./cloud init` (as self) to set up Org Policies and Service Accounts.
2.  Runs `./cloud deploy` (as SA) to launch infrastructure.
3.  Runs `./cloud user-auth export` to get connection info.

**User Persona (Agent Consumer):**
1.  Installs CLI: `pipx install agentic-consult`.
2.  Imports credentials: `cat creds.yaml | consult remote auth import`.
3.  Registers agent: `consult remote register`.
4.  Connects: `https://gateway-url/sse?key=API_KEY`.

## Secrets Management

| Secret ID | Description | Used By |
|-----------|-------------|---------|
| `gemini-api-key` | AI Model Access | MCP Server |
| `gmail-token` | Gmail OAuth Access | MCP Server, Fetcher |

*   **API Key:** The Gateway API Key is a managed **Resource** (Terraform), not a Secret Manager secret. It is retrieved via `gcloud` for export.

## Terraform Architecture

*   **Providers:** `google`, `google-beta` (for API Gateway).
*   **State:** Local `terraform.tfstate` (committed to repo? NO. `.gitignore`d).
    *   *Note:* Remote state (GCS) is disabled by default to simplify setup but can be enabled.
*   **Decoupling:** Terraform logic is self-contained. `deploy.py` calculates variables (image tags) and passes them in.
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  # GCS backend for remote state storage - TEMPORARILY DISABLED due to billing issue
  # TODO: Re-enable once GCS auth issue resolved
  # backend "gcs" {}
}

# 1. Input Variables
# Passed via -var flags from CLI. See deploy/DESIGN.md "CLI/Terraform Decoupling".
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "bucket_name" {
  description = "GCS bucket name for email archive"
  type        = string
}

variable "service_delete_protection" {
  description = "Enable deletion protection for Cloud Run jobs"
  type        = bool
  default     = false
}

variable "mcp_image" {
  description = "Full URL for MCP image (e.g. gcr.io/proj/img:tag or ghcr.io/...)"
  type        = string
}

variable "fetcher_image" {
  description = "Full URL for fetcher image"
  type        = string
}

locals {
  project_id  = var.project_id
  bucket_name = var.bucket_name
  region      = "us-central1"
}

provider "google" {
  project = local.project_id
  region  = local.region
}

provider "google-beta" {
  project = local.project_id
  region  = local.region
}

# 2. Shared Storage (GCS)
# Managed by ./cloud init (Bootstrapping Infrastructure)
data "google_storage_bucket" "data_bucket" {
  name = local.bucket_name
}

# 2b. Updateable App Resources
# Syncs app resources to GCS config/app/ folder for hot-patching without image rebuilds.
# See DESIGN.md section 15 and deploy/config-resources.json for manifest.

locals {
  repo_root        = "${path.module}/../.."
  config_resources = jsondecode(file("${path.module}/../config-resources.json"))

  # Build map of resources for for_each
  resource_map = {
    for r in local.config_resources.resources : basename(r.path) => {
      path    = r.path
      restart = r.restart
    }
  }

  # Files requiring restart - compute combined hash
  restart_files = [for name, r in local.resource_map : "${local.repo_root}/${r.path}" if r.restart]
}

resource "google_storage_bucket_object" "app_resource" {
  for_each = local.resource_map

  name   = "config/app/${each.key}"
  bucket = data.google_storage_bucket.data_bucket.name
  source = "${local.repo_root}/${each.value.path}"

  # Infer content type from extension
  content_type = endswith(each.key, ".json") ? "application/json" : "text/plain"
}

# 3. Service Account
resource "google_service_account" "analyzer_sa" {
  account_id   = "consult-analyzer-sa"
  display_name = "Consult Analyzer Service Account"
}

# IAM: SA needs to read/write GCS and read Secrets
resource "google_storage_bucket_iam_member" "gcs_admin" {
  bucket = data.google_storage_bucket.data_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.analyzer_sa.email}"
}

# Project owners need explicit object access with uniform bucket-level access
resource "google_storage_bucket_iam_member" "gcs_owner_access" {
  bucket = data.google_storage_bucket.data_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "projectOwner:${local.project_id}"
}

# Grant access to the secrets by name (assuming they were created by CLI init)
resource "google_project_iam_member" "secret_accessor" {
  project = local.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.analyzer_sa.email}"
}

# Grant ability to invoke Cloud Run jobs (needed for scheduler)
resource "google_project_iam_member" "run_invoker" {
  project = local.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.analyzer_sa.email}"
}

# 3b. Batch Auth Token (for scheduler -> MCP internal endpoints)
# Change rotation_trigger to force token regeneration
resource "random_password" "batch_token" {
  length  = 32
  special = false

  keepers = {
    rotation_trigger = "1"
  }
}

resource "google_secret_manager_secret" "batch_auth_token" {
  secret_id = "batch-auth-token"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "batch_auth_token" {
  secret      = google_secret_manager_secret.batch_auth_token.id
  secret_data = random_password.batch_token.result
}

# 4a. Cloud Run Job: Fetcher (gmex)
resource "google_cloud_run_v2_job" "fetcher_job" {
  name                = "gmex-fetcher"
  location            = local.region
  deletion_protection = var.service_delete_protection

  template {
    template {
      service_account = google_service_account.analyzer_sa.email

      containers {
        image = var.fetcher_image

        env {
          name  = "EMAIL_ARCHIVE_DATA_DIR"
          value = "/mnt/gcs/email-archive"
        }

        # Gmail OAuth credentials - point to mounted secret file
        env {
          name  = "GOOGLE_APPLICATION_CREDENTIALS"
          value = "/secrets/gmail-token/credentials.json"
        }

        volume_mounts {
          name       = "gcs-volume"
          mount_path = "/mnt/gcs"
        }

        volume_mounts {
          name       = "gmail-token"
          mount_path = "/secrets/gmail-token"
        }
      }

      volumes {
        name = "gcs-volume"
        gcs {
          bucket = data.google_storage_bucket.data_bucket.name
        }
      }

      volumes {
        name = "gmail-token"
        secret {
          secret = "gmail-token"
          items {
            version = "latest"
            path    = "credentials.json"
          }
        }
      }
    }
  }
}

# 4b. Cloud Run Service: MCP Server (HTTP endpoint)
resource "google_cloud_run_v2_service" "mcp_service" {
  name                = "consult-mcp"
  location            = local.region
  deletion_protection = var.service_delete_protection

  template {
    service_account = google_service_account.analyzer_sa.email

    containers {
      image = var.mcp_image

      env {
        name  = "EMAIL_ARCHIVE_DATA_DIR"
        value = "/mnt/gcs/email-archive"
      }

      env {
        name  = "CONSULT_CONFIG_DIR"
        value = "/mnt/gcs/config"
      }

      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = "gemini-api-key"
            version = "latest"
          }
        }
      }

      env {
        name = "MCP_PERSONAL_ACCESS_TOKEN"
        value_source {
          secret_key_ref {
            secret  = "mcp-access-token"
            version = "latest"
          }
        }
      }

      env {
        name  = "TRIAGE_DISABLE_CHAT"
        value = "true"
      }

      # Batch auth token (for scheduler -> /internal/* endpoints)
      env {
        name = "BATCH_AUTH_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.batch_auth_token.secret_id
            version = "latest"
          }
        }
      }

      # Gmail OAuth credentials for label operations (archive, mark review)
      env {
        name  = "GOOGLE_APPLICATION_CREDENTIALS"
        value = "/secrets/gmail-token/credentials.json"
      }

      # Combined hash of restart-required app resources (see DESIGN.md section 15)
      # Changes to restart:true resources in config-resources.json trigger Cloud Run restart
      env {
        name  = "CONFIG_RESOURCES_MD5"
        value = md5(join("", [for f in local.restart_files : filemd5(f)]))
      }

      volume_mounts {
        name       = "gcs-volume"
        mount_path = "/mnt/gcs"
      }

      volume_mounts {
        name       = "gmail-token"
        mount_path = "/secrets/gmail-token"
      }

      ports {
        container_port = 8080
      }
    }

    volumes {
      name = "gcs-volume"
      gcs {
        bucket = data.google_storage_bucket.data_bucket.name
      }
    }

    volumes {
      name = "gmail-token"
      secret {
        secret = "gmail-token"
        items {
          version = "latest"
          path    = "credentials.json"
        }
      }
    }
  }
}

# --- API Gateway (Public Facade) ---

# Enable required APIs
resource "google_project_service" "apigateway" {
  project = local.project_id
  service = "apigateway.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "servicecontrol" {
  project = local.project_id
  service = "servicecontrol.googleapis.com"
  disable_on_destroy = false
}

# The API Resource
resource "google_api_gateway_api" "mcp_api" {
  provider = google-beta
  api_id   = "consult-mcp-api"
  project  = local.project_id
  depends_on = [google_project_service.apigateway]
}

# The API Config (Immutable - changes create new one)
resource "google_api_gateway_api_config" "mcp_cfg" {
  provider = google-beta
  api      = google_api_gateway_api.mcp_api.api_id
  project  = local.project_id
  
  openapi_documents {
    document {
      path = "openapi.yaml"
      contents = base64encode(templatefile("${path.module}/openapi.yaml.tftpl", {
        mcp_url = google_cloud_run_v2_service.mcp_service.uri
      }))
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# The Gateway (Deployment)
resource "google_api_gateway_gateway" "mcp_gw" {
  provider = google-beta
  api_config = google_api_gateway_api_config.mcp_cfg.id
  gateway_id = "consult-mcp-gw"
  project    = local.project_id
  region     = "us-central1"
}

# IAM: Gateway SA needs to invoke Cloud Run
data "google_project" "current" {
  project_id = local.project_id
}

resource "google_cloud_run_service_iam_member" "gateway_invoker" {
  service  = google_cloud_run_v2_service.mcp_service.name
  location = google_cloud_run_v2_service.mcp_service.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-apigateway.iam.gserviceaccount.com"
}

# 5a. Trigger: Fetcher (runs every 30 mins at :00, :30)
resource "google_cloud_scheduler_job" "periodic_fetch" {
  name             = "trigger-email-fetch"
  description      = "Triggers the gmex fetcher job every 30 minutes"
  schedule         = "0,30 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://${local.region}-run.googleapis.com/v2/projects/${local.project_id}/locations/${local.region}/jobs/${google_cloud_run_v2_job.fetcher_job.name}:run"

    oauth_token {
      service_account_email = google_service_account.analyzer_sa.email
    }
  }

  # Allow schedule to be changed via Console without terraform overwriting it
  lifecycle {
    ignore_changes = [schedule]
  }
}

# 5b. Trigger: Batch Analysis (runs every 30 mins, offset by 5min from fetch)
resource "google_cloud_scheduler_job" "periodic_analysis" {
  name             = "trigger-email-analysis"
  description      = "Triggers batch email analysis on MCP service"
  schedule         = "5,35 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "600s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.mcp_service.uri}/internal/batch"

    headers = {
      "Authorization" = "Bearer ${random_password.batch_token.result}"
    }
  }

  # Allow schedule to be changed via Console without terraform overwriting it
  lifecycle {
    ignore_changes = [schedule]
  }

  depends_on = [google_secret_manager_secret_version.batch_auth_token]
}
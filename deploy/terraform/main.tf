terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
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

locals {
  project_id  = var.project_id
  bucket_name = var.bucket_name
  region      = "us-central1"

  # Image references
  analyzer_image = "gcr.io/${local.project_id}/consult-analyzer:latest"
  fetcher_image  = "gcr.io/${local.project_id}/gmex-fetcher:latest"
}

provider "google" {
  project = local.project_id
  region  = local.region
}

# 2. Shared Storage (GCS)
resource "google_storage_bucket" "data_bucket" {
  name          = local.bucket_name
  location      = "US"
  force_destroy = false
  
  labels = {
    "agentic-consult" = "default"
  }
  
  uniform_bucket_level_access = true
}

# 3. Service Account
resource "google_service_account" "analyzer_sa" {
  account_id   = "consult-analyzer-sa"
  display_name = "Consult Analyzer Service Account"
}

# IAM: SA needs to read/write GCS and read Secrets
resource "google_storage_bucket_iam_member" "gcs_admin" {
  bucket = google_storage_bucket.data_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.analyzer_sa.email}"
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

# 4a. Cloud Run Job: Fetcher (gmex)
resource "google_cloud_run_v2_job" "fetcher_job" {
  name     = "gmex-fetcher"
  location = local.region

  template {
    template {
      service_account = google_service_account.analyzer_sa.email

      containers {
        image = local.fetcher_image

        env {
          name  = "EMAIL_ARCHIVE_DATA_DIR"
          value = "/mnt/gcs/email-archive"
        }

        # Gmail OAuth credentials (JSON blob stored in Secret Manager)
        env {
          name = "GOOGLE_APPLICATION_CREDENTIALS"
          value_source {
            secret_key_ref {
              secret  = "gmail-oauth-credentials"
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = "gcs-volume"
          mount_path = "/mnt/gcs"
        }
      }

      volumes {
        name = "gcs-volume"
        gcs {
          bucket = google_storage_bucket.data_bucket.name
        }
      }
    }
  }
}

# 4b. Cloud Run Job: Analyzer
resource "google_cloud_run_v2_job" "analyzer_job" {
  name     = "consult-analyzer"
  location = local.region

  template {
    template {
      service_account = google_service_account.analyzer_sa.email

      containers {
        image = local.analyzer_image

        env {
          name  = "EMAIL_ARCHIVE_DATA_DIR"
          value = "/mnt/gcs/email-archive"
        }
        
        # Point directly to secret names for env var injection
        env {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = "gemini-api-key"
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = "gcs-volume"
          mount_path = "/mnt/gcs"
        }
      }

      volumes {
        name = "gcs-volume"
        gcs {
          bucket = google_storage_bucket.data_bucket.name
        }
      }
    }
  }
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
    uri         = "https://${google_cloud_run_v2_job.fetcher_job.location}-run.googleapis.com/apis/run.googleapis.com/v1/${google_cloud_run_v2_job.fetcher_job.id}:run"

    oauth_token {
      service_account_email = google_service_account.analyzer_sa.email
    }
  }

  # Allow schedule to be changed via Console without terraform overwriting it
  lifecycle {
    ignore_changes = [schedule]
  }
}

# 5b. Trigger: Analyzer (runs every 30 mins at :05, :35 - after fetcher)
resource "google_cloud_scheduler_job" "periodic_analysis" {
  name             = "trigger-email-analysis"
  description      = "Triggers the agentic-consult analyzer job every 30 minutes"
  schedule         = "5,35 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://${google_cloud_run_v2_job.analyzer_job.location}-run.googleapis.com/apis/run.googleapis.com/v1/${google_cloud_run_v2_job.analyzer_job.id}:run"

    oauth_token {
      service_account_email = google_service_account.analyzer_sa.email
    }
  }

  # Allow schedule to be changed via Console without terraform overwriting it
  lifecycle {
    ignore_changes = [schedule]
  }
}
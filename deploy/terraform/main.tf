terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    external = {
      source  = "hashicorp/external"
      version = "2.3.1"
    }
  }
}

# 1. Resolve Project & Bucket Context
data "external" "project_info" {
  program = ["python3", "-m", "agentic_consult.cli.main", "cloud", "config", "resolve"]
  working_dir = "${path.module}/../../"
}

locals {
  project_id  = data.external.project_info.result.project_id
  bucket_name = data.external.project_info.result.bucket_name
  region      = "us-central1"
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

# 4. Cloud Run Job: Analyzer
resource "google_cloud_run_v2_job" "analyzer_job" {
  name     = "consult-analyzer"
  location = local.region

  template {
    template {
      service_account = google_service_account.analyzer_sa.email

      containers {
        image = "gcr.io/${local.project_id}/consult-analyzer:latest"

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

# 5. Hourly Trigger
resource "google_cloud_scheduler_job" "hourly_analysis" {
  name             = "trigger-email-analysis"
  description      = "Triggers the agentic-consult analyzer job every hour"
  schedule         = "0 * * * *"
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
}
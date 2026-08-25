terraform {
  required_version = ">= 1.14"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
    # Cloudflare provider re-enable when CLOUDFLARE_API_TOKEN is set:
    # cloudflare = {
    #   source  = "cloudflare/cloudflare"
    #   version = "~> 4.0"
    # }
  }
}

# Reads GITHUB_TOKEN from environment automatically
provider "github" {
  owner = var.github_owner
}

# Cloudflare — uncomment when token is ready, and rename cloudflare.tf.disabled → cloudflare.tf
# provider "cloudflare" {}

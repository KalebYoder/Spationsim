variable "github_owner" {
  description = "GitHub username"
  type        = string
  default     = "KalebYoder"
}

variable "server_ip" {
  description = "Public IP address of the game server"
  type        = string
}

variable "domain_name" {
  description = "Primary domain name (e.g. spationsim.com)"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID — found on the domain's Overview page in the Cloudflare dashboard"
  type        = string
}

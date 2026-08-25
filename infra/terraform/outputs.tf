output "repository_url" {
  description = "GitHub repository URL"
  value       = github_repository.spationsim.html_url
}

output "repository_clone_url" {
  description = "Git clone URL"
  value       = github_repository.spationsim.ssh_clone_url
}

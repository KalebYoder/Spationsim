resource "github_repository" "spationsim" {
  name        = "Spationsim"
  description = "Space-based browser nation simulator"
  visibility  = "public"

  has_issues   = true
  has_projects = false
  has_wiki     = false

  delete_branch_on_merge = true
}


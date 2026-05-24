#!/bin/bash
# Run this once to install the GitHub Actions self-hosted runner.
# Usage: bash setup-runner.sh <GITHUB_TOKEN>
# Get your token from: https://github.com/KalebYoder/spationsim/settings/actions/runners/new
set -e

TOKEN=$1
if [ -z "$TOKEN" ]; then
  echo "Usage: bash setup-runner.sh <GITHUB_TOKEN>"
  exit 1
fi

RUNNER_VERSION="2.321.0"
RUNNER_DIR="$HOME/actions-runner"

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

curl -fsSL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
  | tar xz

./config.sh \
  --url https://github.com/KalebYoder/spationsim \
  --token "$TOKEN" \
  --name "spationsim-home" \
  --labels self-hosted \
  --work /home/kaleb/actions-runner-work \
  --unattended

# Install as a systemd service so it survives reboots
sudo ./svc.sh install
sudo ./svc.sh start

echo ""
echo "Runner installed and started."
echo "Check status: sudo systemctl status actions.runner.KalebYoder-spationsim.spationsim-home"

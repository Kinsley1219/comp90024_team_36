#!/bin/bash
# COMP90024 Team 36
# One-click deployment script for Reddit Fission functions
# Run this script from the project root directory: bash backend/fission/deploy.sh

set -e  # Exit immediately if any command fails

# Configuration
ENV_NAME="python-39"       # Fission Python 3.9 environment name
PKG_NAME="reddit-pkg"      # Fission package name
APP_NS="comp90024"         # Kubernetes namespace

echo "=== Step 1: Building zip package ==="
# Must build zip from inside the function directory to avoid path issues
(
  cd backend/fission/reddit
  zip -r reddit.zip .
  mv reddit.zip ../
)

echo "=== Step 2: Creating Fission Python 3.9 environment (if not exists) ==="
# Using Python 3.9 environment for compatibility with newer packages
fission env create \
  --name ${ENV_NAME} \
  --builder fission/python-builder-3.9 \
  --image fission/python-env-3.9 \
  2>/dev/null || echo "Environment ${ENV_NAME} already exists, skipping."

echo "=== Step 3: Creating or updating Fission package ==="
# Try to create first, update if already exists
fission package create \
  --name ${PKG_NAME} \
  --sourcearchive backend/fission/reddit.zip \
  --env ${ENV_NAME} \
  --buildcmd "./build.sh" \
  2>/dev/null || \
fission package update \
  --name ${PKG_NAME} \
  --sourcearchive backend/fission/reddit.zip \
  --buildcmd "./build.sh"

echo "=== Step 4: Waiting for package build to complete ==="
sleep 10
fission package info --name ${PKG_NAME}

echo "=== Step 5: Creating harvest function (Timer-driven) ==="
# reddit-harvest is triggered by a timer every 5 minutes
fission fn create \
  --name reddit-harvest \
  --env ${ENV_NAME} \
  --pkg ${PKG_NAME} \
  --entrypoint "reddit_harvest.main" \
  --fntimeout 120 \
  2>/dev/null || \
fission fn update \
  --name reddit-harvest \
  --pkg ${PKG_NAME} \
  --entrypoint "reddit_harvest.main"

echo "=== Step 6: Creating Timer Trigger (every 5 minutes) ==="
# This is the core event-driven trigger - fires every 5 minutes automatically
fission timer create \
  --name reddit-timer \
  --function reddit-harvest \
  --cron "@every 5m" \
  2>/dev/null || echo "Timer reddit-timer already exists, skipping."

echo "=== Step 7: Creating API function (HTTP-driven) ==="
# reddit-api is triggered by HTTP requests from Jupyter Notebook
fission fn create \
  --name reddit-api \
  --env ${ENV_NAME} \
  --pkg ${PKG_NAME} \
  --entrypoint "reddit_api.main" \
  2>/dev/null || \
fission fn update \
  --name reddit-api \
  --pkg ${PKG_NAME} \
  --entrypoint "reddit_api.main"

echo "=== Step 8: Creating HTTP Triggers for API endpoints ==="
# Each route maps a URL path to the reddit-api function
fission route create --name reddit-posts    --method GET \
  --url /api/reddit/posts     --function reddit-api 2>/dev/null || true
fission route create --name reddit-stats    --method GET \
  --url /api/reddit/stats     --function reddit-api 2>/dev/null || true
fission route create --name reddit-sentiment --method GET \
  --url /api/reddit/sentiment --function reddit-api 2>/dev/null || true

echo ""
echo "=== Deployment complete ==="
echo "To test the harvest function manually:"
echo "  fission fn test --name reddit-harvest --timeout=120s"
echo ""
echo "To test the API (requires kubectl port-forward):"
echo "  kubectl port-forward service/router -n fission 9090:80 &"
echo "  curl http://localhost:9090/api/reddit/stats"
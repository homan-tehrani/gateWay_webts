#!/bin/bash
set -e

echo "Deploying version: $IMAGE_TAG"
echo "Project: $CI_PROJECT_NAME"
echo "Registry: $DOCKER_REG/$CI_PROJECT_NAMESPACE/$CI_PROJECT_NAME"


echo "Starting Pull..."
docker compose pull

echo "Starting Up..."
docker compose up -d

echo "Cleaning up old images..."
docker system prune -f

echo "Deployment completed successfully!"

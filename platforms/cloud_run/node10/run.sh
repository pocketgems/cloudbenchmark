#!/usr/bin/env bash
set -o errexit
set -o nounset
runtime='node10'
tag=${runtime}:0.1
time docker build -t $tag -f Dockerfile.${runtime} ../.. &&
  PORT=8080 && docker run \
   -p 8080:${PORT} \
   -e PORT=${PORT} \
   $tag

#!/usr/bin/env bash
set -o errexit
set -o nounset
if [ $# -ne 1 ]; then
    echo "usage: ./run.sh RUNTIME"
    exit 1
fi
runtime=$1
if [ ! -f "Dockerfile.${runtime}" ]; then
    echo "Dockerfile.${runtime} not found"
    exit 1
fi
time docker build -t ${runtime}:test -f Dockerfile.${runtime} .. &&
  PORT=8080 && docker run \
   -p 8080:${PORT} \
   -e PORT=${PORT} \
   ${runtime}:test

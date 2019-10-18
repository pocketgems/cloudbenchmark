#!/usr/bin/env bash
set -o errexit
set -o nounset
if [ $# -ne 2 ]; then
    echo "usage: ./run.sh PROJECTID RUNTIME"
    exit 1
fi
project=$1
runtime=$2
if [ ! -f "Dockerfile.${runtime}" ]; then
    echo "Dockerfile.${runtime} not found"
    exit 1
fi
time docker build -t ${runtime}:test -f Dockerfile.${runtime} .. &&
  PORT=8080 && docker run \
   -p 8080:${PORT} \
   -e PORT=${PORT} \
   -e GAE_APPLICATION=${project} \
   ${runtime}:test

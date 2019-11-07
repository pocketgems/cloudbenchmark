#!/usr/bin/env bash
set -o errexit
set -o nounset
LOCALPORT=8080
IMAGE=fargate-node10:test
time docker build -t ${IMAGE} -f Dockerfile ../.. &&
  PORT=${LOCALPORT} && docker run \
   --cpus=1 \
   -p ${LOCALPORT}:${PORT} \
   -e PORT=${PORT} \
   ${IMAGE}

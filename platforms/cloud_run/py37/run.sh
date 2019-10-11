#!/usr/bin/env bash
set -o errexit
set -o nounset
runtime=$1
if [ $runtime != 'py3' -a $runtime != 'pypy3' ]; then
    echo 'runtime must be py3 or pypy3'
    exit 1
fi
time docker build -t ${runtime}slim:0.2 -f Dockerfile.${runtime} ../.. &&
  PORT=8080 && docker run \
   -p 8080:${PORT} \
   -e PORT=${PORT} \
   -v `pwd`/../serviceaccount.json:/tmp/gcpkeys.json:ro \
   ${runtime}slim:0.2

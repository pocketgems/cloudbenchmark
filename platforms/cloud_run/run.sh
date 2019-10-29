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
if [ ${runtime} = "node10" ]; then
    LOCALPORT=8080
    VER=
else
    LOCALPORT=8081
    VER=gevent
fi
time docker build -t ${runtime}:test -f Dockerfile.${runtime} .. &&
  PORT=${LOCALPORT} && docker run \
   --cpus=1 \
   -p ${LOCALPORT}:${PORT} \
   -e PORT=${PORT} \
   -e GAE_APPLICATION=${project} \
   -e GAE_VERSION=${VER} \
   ${runtime}:test

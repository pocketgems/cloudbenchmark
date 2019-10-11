#!/usr/bin/env bash
time docker build -t py3slim:0.2 -f Dockerfile.py3 . &&
  PORT=8080 && docker run \
   -p 8080:${PORT} \
   -e PORT=${PORT} \
   -v `pwd`/../serviceaccount.json:/tmp/gcpkeys.json:ro \
   py3slim:0.2

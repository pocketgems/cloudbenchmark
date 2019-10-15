#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o xtrace

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd ${SCRIPTDIR}/..
cp cloud_run/py37/Dockerfile.py3 Dockerfile
time gcloud builds submit
time gcloud beta run deploy testpy3 --image gcr.io/benchmarkgcp2/testpy3kaniko:latest --platform gke --cluster test-n1-highcpu-2 --cluster-location us-central1-a --concurrency=80 --max-instances 1 --timeout 900 --cpu 1 --memory 256Mi
time gcloud beta run deploy testpy3 --image gcr.io/benchmarkgcp2/testpy3kaniko:latest --platform gke --cluster test-n2-highcpu-2 --cluster-location us-central1-a --concurrency=80 --max-instances 1 --timeout 900 --cpu 1 --memory 256Mi

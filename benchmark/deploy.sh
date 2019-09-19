#!/usr/bin/env bash
set -o xtrace

gcloud functions deploy runBenchmark --runtime nodejs10 --trigger-http --timeout=330 --region=us-central1 --quiet

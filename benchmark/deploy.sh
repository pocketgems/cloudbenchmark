#!/usr/bin/env bash
set -o xtrace

gcloud functions deploy runBenchmark --runtime nodejs10 --trigger-http --timeout=330 --region=us-central1 --quiet

zip aws_function.zip index.js benchmark.js node_modules
aws lambda create-function --function-name run-benchmark \
    --zip-file fileb://aws_function.zip \
    --handler index.handler \
    --runtime nodejs10.x \
    --role arn:aws:iam::637628279320:role/lambda-benchmarker
aws lambda update-function-configuration --function-name run-benchmark \
    --timeout 900

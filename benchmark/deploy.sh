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

# make the function accessible over HTTP (wow ...)
REGION=us-west-2
ACCOUNT=637628279320
aws apigateway create-rest-api --name RunBenchmark
read API  # get ID from previous output
aws apigateway create-resource --rest-api-id $API  --path-part RunBenchmark
aws apigateway get-resources --rest-api-id $API
read RESOURCEPARENTID  # get ID from previous output
aws apigateway create-resource --rest-api-id $API  --path-part RunBenchmark \
    --parent-id $RESOURCEPARENTID
read RESOURCE  # get from previous output
aws apigateway put-method --rest-api-id $API --resource-id $RESOURCE \
    --http-method POST --authorization-type NONE
aws apigateway put-integration --rest-api-id $API --resource-id $RESOURCE \
    --http-method POST --type AWS --integration-http-method POST \
    --uri arn:aws:apigateway:$REGION:lambda:path/2015-03-31/functions/arn:aws:lambda:$REGION:$ACCOUNT:function:run-benchmark/invocations
aws apigateway put-method-response --rest-api-id $API \
    --resource-id $RESOURCE --http-method POST \
    --status-code 200 --response-models application/json=Empty
aws apigateway put-integration-response --rest-api-id $API \
    --resource-id $RESOURCE --http-method POST \
    --status-code 200 --response-templates application/json=""
aws apigateway create-deployment --rest-api-id $API --stage-name prod
aws lambda add-permission --function-name run-benchmark \
    --statement-id apigateway-test-2 --action lambda:InvokeFunction \
    --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:$REGION:$ACCOUNT:$API/*/POST/RunBenchmark"
aws lambda add-permission --function-name run-benchmark \
    --statement-id apigateway-prod-2 --action lambda:InvokeFunction \
    --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:$REGION:$ACCOUNT:$API/prod/POST/RunBenchmark"

# curl -X POST -d '{"project":"benchmarkgcp2","service":"py37","version":"falcon-gunicorn-default-dbtx","test":"dbtx","c":10,"n":10}' https://$API.execute-api.$REGION.amazonaws.com/prod/RunBenchmark
#"Fri, 08 Nov 2019 01:53:50 GMT\tpy37\tfalcon-gunicorn-default-dbtx\tdbtx\t2.73224043715847\t1.23167\t1419\t1478\t2201\t2213\t0\t3.66\t0\t0"

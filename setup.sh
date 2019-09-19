#!/usr/bin/env bash
# You need gcloud command-line tools installed. This script will create
# resources that incur billing charges. Delete the project this script creates
# when you're done with it!
set -o errexit
set -o nounset

if [ $# -ge 1 ]; then
    PROJECTNAME=$1
else
    rndint=$((RANDOM % 1000000))
    echo "What do you want to name your project? e.g., benchmarkgcp$rndint"
    read PROJECTNAME
fi
PROJECTNAME="$(echo -e "${PROJECTNAME}" | tr -d '[:space:]')"
if [ -z $PROJECTNAME ]; then
    echo "project name is required"
    exit 1
fi

pip install --upgrade google-auth-oauthlib requests requests-futures
gcloud components install beta
gcloud components update

gcloud organizations list
echo "What organization ID do you want your new project to belong to?"
read ORGID
ORGID="$(echo -e "${ORGID}" | tr -d '[:space:]')"

gcloud beta billing accounts list
echo "What billing account ID do you want your new project to use?"
read ACCOUNTID
ACCOUNTID="$(echo -e "${ACCOUNTID}" | tr -d '[:space:]')"

set -o xtrace
gcloud auth application-default login
gcloud projects create $PROJECTNAME --set-as-default --organization $ORGID
gcloud beta billing projects link $PROJECTNAME --billing-account=$ACCOUNTID

gcloud app create --region=us-central
./platforms/gae_standard/deploy.py $PROJECTNAME
pushd benchmark
./deploy.sh
popd

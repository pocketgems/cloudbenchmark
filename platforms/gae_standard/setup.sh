#!/usr/bin/env bash
set -o errexit
set -o nounset

PROJECTNAME=$1
if [ -z $PROJECTNAME ]; then
    echo "missing project name"
    exit 1
fi

sudo pip install --upgrade google-auth-oauthlib requests
brew install wrk
gcloud config set project $PROJECTNAME
gcloud auth application-default login
./deploy.py $PROJECTNAME

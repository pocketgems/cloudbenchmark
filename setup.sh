#!/usr/bin/env bash
# You need gcloud command-line tools installed. This script will create
# resources that incur billing charges. Delete the project this script creates
# when you're done with it!
set -o errexit
set -o nounset

if [ $# -ge 1 ]; then
    PROJECTNAME=$1
else
    rndint=$((RANDOM % 100000))
    echo "What do you want to name your project? e.g., bmarkgcp$rndint"
    read PROJECTNAME
fi
PROJECTNAME="$(echo -e "${PROJECTNAME}" | tr -d '[:space:]')"
if [ -z $PROJECTNAME ]; then
    echo "project name is required"
    exit 1
fi
pnamesz=${#PROJECTNAME}
if [ $pnamesz -gt 13 ]; then
    # if it is too long, then some of the targeted urls' hostnames will be
    # longer than allowed on GAE (<version>-dot-<service>-dot-<project> must
    # be less than 64 characters)
    echo "project name cannot be longer than 13 characters"
    exit 1
fi

pip install --upgrade google-auth-oauthlib requests
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
echo "Please go turn on dedicated memcache for your GAE app ... done?"
read ignore

echo "Please be patient; setting up Memorystore (Redis) is quite slow ..."
gcloud services enable redis.googleapis.com
gcloud redis instances create testcluster --size=1 --region=us-central1 \
    --zone=us-central1-a --tier=STANDARD
redishost="$(gcloud redis instances describe testcluster --region=us-central1 \
                    | fgrep host | cut -d: -f2 | cut -d' ' -f2)"
redisport="$(gcloud redis instances describe testcluster --region=us-central1 \
                    | fgrep port | cut -d: -f2 | cut -d' ' -f2)"
redisnet="$(gcloud redis instances describe testcluster --region=us-central1 \
                    | fgrep authorizedNetwork | cut -d: -f2 | cut -d' ' -f2)"

gcloud services enable vpcaccess.googleapis.com
gcloud beta compute networks vpc-access connectors create conntest \
    --network default --region us-central1 --range 10.8.0.0/28

vpcname="$(gcloud beta compute networks vpc-access connectors describe \
                  conntest --region us-central1 \
                    | fgrep name | cut -d: -f2 | cut -d' ' -f2)"
py37cfgFN=./platforms/gae_standard/py37/template-generated.yaml
cp ./platforms/gae_standard/py37/template.yaml $py37cfgFN
echo "vpc_access_connector:" >> $py37cfgFN
echo "  name: $vpcname" >> $py37cfgFN
echo "env_variables:" >> $py37cfgFN
echo "  REDIS_HOST: \"$redishost\"" >> $py37cfgFN
echo "  REDIS_PORT: \"$redisport\"" >> $py37cfgFN

echo "setting up Cloud Tasks ..."
gcloud services enable cloudtasks.googleapis.com
gcloud services enable tasks.googleapis.com
gcloud iam service-accounts create testcloudtasks
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:testcloudtasks@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/cloudtasks.admin"
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:testcloudtasks@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/appengine.appViewer"
gcloud iam service-accounts keys create \
    platforms/gae_standard/py37/cloudtasksaccount.json \
    --iam-account testcloudtasks@$PROJECTNAME.iam.gserviceaccount.com
gcloud tasks queues create testpy3 \
     --max-concurrent-dispatches=0 \
     --max-attempts=0
gcloud tasks queues create test \
     --max-concurrent-dispatches=0 \
     --max-attempts=0

./platforms/gae_standard/deploy.py $PROJECTNAME
pushd benchmark
./deploy.sh
popd

echo "creating datastore entities for benchmarking ..."
for start in `seq 0 1000 9000`; do
    if [ $start -ne 0 ]; then
        echo "   $start done"
    fi
    curl -d "s=$start&n=1000" -X POST https://webapp-f1-solo-dbindir-dot-py27-dot-$PROJECTNAME.appspot.com/test/dbindir
done
echo '   done creating entites!'

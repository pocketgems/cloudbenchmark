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

pip install --upgrade google-auth-oauthlib requests boto3
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

# second gen runtimes need to be connected to the VPC where redis is running
# and told how to connect to it
vpcname="$(gcloud beta compute networks vpc-access connectors describe \
                  conntest --region us-central1 \
                    | fgrep name | cut -d: -f2 | cut -d' ' -f2)"
generatedYamlFN=./tmp-generated.yaml
echo "vpc_access_connector:" > $generatedYamlFN
echo "  name: $vpcname" >> $generatedYamlFN
echo "env_variables:" >> $generatedYamlFN
echo "  REDIS_HOST: \"$redishost\"" >> $generatedYamlFN
echo "  REDIS_PORT: \"$redisport\"" >> $generatedYamlFN
secondGenRuntimes=('py37' 'node10' 'node12')
for start in `seq 0 2`; do
    runtime=${secondGenRuntimes[$start]}
    cat ./platforms/gae_standard/${runtime}/template.yaml $generatedYamlFN \
        > ./platforms/gae_standard/${runtime}/template-generated.yaml
done
rm generatedYamlFN
# cloud run needs redis connection info too
echo "ENV REDIS_HOST $redishost" > ./platforms/cloud_run/.redis_info
echo "ENV REDIS_PORT $redisport" >> ./platforms/cloud_run/.redis_info

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
# routing override is specified because app_engine_routing seems to be broken
# and ignored when used from managed cloud run (works fine from GAE though)
gcloud tasks queues create testpy3 \
     --max-concurrent-dispatches=0 \
     --max-attempts=0 \
      --routing-override='service:py3,version:txtaskhandler'
gcloud tasks queues create test \
     --max-concurrent-dispatches=0 \
     --max-attempts=0


### setup for GKE
# create service account for our GKE clusters to use to access datastore, task
# queue, redis and stackdriver
gcloud iam service-accounts create forcloudrun
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:forcloudrun@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/cloudtasks.enqueuer"
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:forcloudrun@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:forcloudrun@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/redis.editor"
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:forcloudrun@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/logging.logWriter"
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:forcloudrun@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/monitoring.metricWriter"
gcloud projects add-iam-policy-binding $PROJECTNAME \
    --member "serviceAccount:forcloudrun@$PROJECTNAME.iam.gserviceaccount.com" \
    --role "roles/stackdriver.resourceMetadata.writer"
# need to be able to access builds in order to deploy them
gsutil iam ch serviceAccount:forcloudrun@${PROJECTNAME}.iam.gserviceaccount.com:objectViewer gs://artifacts.${PROJECTNAME}.appspot.com
gcloud iam service-accounts keys create \
    platforms/cloud_run/serviceaccount.json \
    --iam-account forcloudrun@$PROJECTNAME.iam.gserviceaccount.com
# enable GKE
gcloud components install kubectl --quiet
gcloud services enable container.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable logging.googleapis.com
gcloud services enable monitoring.googleapis.com
gcloud services enable stackdriver.googleapis.com
# put our clusters in the same region and zone as our benchmarker
machineTypes=('n1-highcpu-2' 'n2-highcpu-2')
for start in `seq 0 1`; do
    machineType=${machineTypes[$start]}
    if [ $machineType == 'c2-standard-4' ]; then
        zone='us-central1-b'  # not available in zone a yet
    else
        zone='us-central1-a'
    fi
    clusterName=cluster-$machineType
    # Istio addon no longer required as of 1.13.10-gke.8+
    gcloud beta container clusters create $clusterName \
           --machine-type=$machineType \
           --addons=HorizontalPodAutoscaling,HttpLoadBalancing,Istio,CloudRun \
           --scopes cloud-platform \
           --metadata disable-legacy-endpoints=true \
           --enable-ip-alias \
           --no-issue-client-certificate \
           --no-enable-basic-auth \
           --enable-autorepair \
           --enable-autoupgrade \
           --enable-stackdriver-kubernetes \
           --zone=$zone \
           --enable-autoscaling \
           --min-nodes=0 \
           --max-nodes=100 \
           --num-nodes=3 \
           --service-account=forcloudrun@benchmarkgcp2.iam.gserviceaccount.com
done
# clusters take some time to startup, so we create the clusters and then we try
# to get their IPs later
sleep 60
for start in `seq 0 1`; do
    machineType=${machineTypes[$start]}
    if [ $machineType == 'c2-standard-4' ]; then
        zone='us-central1-b'  # not available in zone a yet
    else
        zone='us-central1-a'
    fi
    clusterName=cluster-$machineType
    # get the public IP address through which we can access our service
    kubectl get service istio-ingressgateway --namespace istio-system \
            --cluster gke_${PROJECTNAME}_${zone}_${clusterName} \
            --output='jsonpath={.status.loadBalancer.ingress[0].ip}' \
            > platforms/cloud_run/clusterip_${machineType}.txt
    # don't need this (default) addon
    gcloud container clusters update $clusterName --update-addons=KubernetesDashboard=DISABLED
done

# cloud run
gcloud services enable run.googleapis.com
# alpha required to be able to update cloud run service yamls
gcloud components install alpha --quiet


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

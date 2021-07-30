#!/bin/bash

set -ex

IMAGE=portal-to-jira-sync
TAG=${1:-latest}
PUSH=${2:-false}
REGISTRY=default-route-openshift-image-registry.apps.shift.cloud.lab.eng.bos.redhat.com:443
#NS=portal-to-jira-sync
NS=openshift

echo building $IMAGE:$TAG

container=$(buildah from python3:latest)
echo "building container with id $container"
buildah config --label maintainer="David Critch <dcritch@gmail.com>" $container
buildah copy $container /home/davidc/code/external/rht/t5g-field-support-team-utils /srv/
buildah copy $container sync.sh /opt/sync.sh
buildah config --workingdir /srv $container
buildah run $container pip3 install -U pip
buildah run $container pip3 install -r /srv/bin/telco5g-jira-requirements.txt
#buildah config --entrypoint /opt/startup.sh $container
#buildah config --port 8080 $container
buildah commit --format docker $container $IMAGE:$TAG

if [[ $PUSH == "true" ]]; then
  echo pushing to $REGISTRY
  buildah tag $IMAGE:$TAG $REGISTRY/$NS/$IMAGE:$TAG
  buildah login -u $(oc whoami) -p $(oc whoami -t) --tls-verify=false $REGISTRY
  buildah push $REGISTRY/$NS/$IMAGE:$TAG
fi

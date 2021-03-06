#!/bin/bash

set -ex

IMAGE=t5gweb
TAG=${1:-latest}
PUSH=${2:-false}
NS=t5g-web

echo building $IMAGE:$TAG

container=$(buildah from registry.access.redhat.com/ubi8/python-39)
echo "building container with id $container"
buildah config --label maintainer="David Critch <dcritch@redhat.com.com>" $container
buildah copy $container ../src/ /srv/
buildah config --workingdir /srv $container
buildah run $container pip3 install .
buildah run $container pip3 install pylint
buildah run $container npm ci --prefix t5gweb/static
buildah config --port 8080 $container
buildah commit --format docker $container $IMAGE:$TAG


if [[ $PUSH == "true" ]]; then
  REGISTRY=${REGISTRY:-$(oc get route/default-route -n openshift-image-registry -o json | jq -r .spec.host)}
  echo pushing to $REGISTRY
  buildah tag $IMAGE:$TAG $REGISTRY/$NS/$IMAGE:$TAG
  buildah login -u $(oc whoami) -p $(oc whoami -t) --tls-verify=false $REGISTRY
  buildah push --tls-verify=false $REGISTRY/$NS/$IMAGE:$TAG
  oc scale --replicas=0 deployment/t5gweb -n $NS
  oc scale --replicas=1 deployment/t5gweb -n $NS
fi

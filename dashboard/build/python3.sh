#!/bin/bash

set -ex

container=$(buildah from registry.redhat.io/ubi8/ubi-minimal)
echo "building container with id $container"
buildah config --label maintainer="David Critch <dcritch@gmail.com>" $container
buildah run $container microdnf -y install python3-pip gcc redhat-rpm-config python3-devel
buildah commit --format docker $container python3:latest

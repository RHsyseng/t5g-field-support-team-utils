#!/bin/bash

set -x

podman run -it -v ./cfg:/srv/cfg:Z localhost/portal-to-jira-sync /bin/bash

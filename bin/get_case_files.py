#!/usr/bin/env python
#
# requires the following environment variables to be set:
#   PORTAL_TOKEN: offline token for RH sso
#   ATTACH_URL: endpoint for case attachments
#
#

import os
import sys

import requests

sso_url = (
    "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"
)
offline_token = os.environ.get("PORTAL_TOKEN")
endpoint_url = os.environ.get("ATTACH_URL")

if offline_token is None or endpoint_url is None:
    sys.exit("please set PORTAL_TOKEN and an ATTACH_URL env variables")
if len(sys.argv) == 2:
    case = sys.argv[1]
else:
    sys.exit("no case specified")

data = {
    "grant_type": "refresh_token",
    "client_id": "rhsm-api",
    "refresh_token": offline_token,
}
r = requests.post(sso_url, data=data)
token = r.json()["access_token"]

attachment_url = "{}/{}/attachments/".format(endpoint_url, case)
headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
r = requests.get(attachment_url, headers=headers)

for file in r.json():
    print("{}: {}".format(file["fileName"], file["link"]))
    link = requests.get(file["link"], headers=headers)
    with open(file["fileName"], "wb") as handle:
        handle.write(link.content)
        handle.close()

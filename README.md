# T5G Field Support Team Utils

This repository contains utilities to help the SysDesEng Telco5G Field Support Team.

## telco5g-jira

This directory contains a script to parse an email that contains a Saleforce
Telco5G Open case report. After the script parses the email, it then parses a
Jira board for existing cases and reports on any new cases that need Jira cards
created based upon the case priority (Normal, High, and Urgent).

If desired, the script will also create the Jira cards for the new cases.

Link to script usage: [telco5g-jira.py readme](https://github.com/RHsyseng/t5g-field-support-team-utils/blob/main/telco5g-jira.py.md)

## Dashboard Development Setup

In the `dashboard` directory, you can use the `Dockerfile` and `docker-compose.yml` to
set up a development environment.

Note: If you are only interested in the frontend, you can comment out everything in
`docker-compose.yml` under the "Backend" header, except for the "volumes" section at
the bottom.

Prerequisites:

- [Podman](https://podman.io/get-started) or [Docker](https://docs.docker.com/engine/install/)
- [podman-compose](https://podman-desktop.io/docs/compose/setting-up-compose) or [docker-compose](https://docs.docker.com/compose/)

### Steps

1. If you are interested in setting up the backend services, fill out `cfg/sample.env`
with any relevant details.
2. Run `cd dashboard` and `podman-compose up -d`

After it's built, you can access the dashboard at <localhost:8080/home>, and the Flower
frontend at <localhost:8000>.

## CI

This project has a CI that is triggered on every push.

Note: There are some environment variables which needed to be set in the GitLab:
Jira_Pass - The Jira details to Connect to the board
OCP_USER & OCP_PASS - Connection detilas to our LAB OCP
Offline_token - API token to connect to customer portal

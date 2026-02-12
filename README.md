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

1. If you are interested in setting up the backend services, copy `cfg/sample.env` into `cfg/local.env` and fill out with your details.

2. Run `cd dashboard` and `podman-compose up -d`

After it's built, you can access the dashboard at <localhost:8080/home>, and the Flower
frontend at <localhost:8000>.

The `docker-compose.yml` file creates a bind mount so that any changes you make locally will immediately be reflected inside of the container. For example, if you change some text inside of `dashboard/src/t5gweb/templates/ui/index.html`, it will immediately be visible at localhost:8080/home. This can be helpful when you are developing new features.

Another volume is created for `/srv/t5gweb/static/node_modules/`. Without this volume, the container will use your local node_modules folder, and you'll need to locally install npm packages. The volume uses the packages from the container, while still allowing you to make local changes elsewhere in the code.

If you want to add a new JS package, you'll need to add it to `package.json` and `package-lock.json` , which are located in `dashboard/src/t5gweb/static/`. Then you need to remove the relevant volume (`podman volume rm dashboard_dashboard-ui_<HASH>`) and rebuild the image.


Please see our [CONTRIBUTING.md](https://github.com/RHsyseng/t5g-field-support-team-utils/blob/main/CONTRIBUTING.md) for further development help.
## CI

This project has a CI that is triggered on every push.

Note: There are some environment variables which needed to be set in the GitLab:
Jira_Pass - The Jira details to Connect to the board
OCP_USER & OCP_PASS - Connection detilas to our LAB OCP
Offline_token - API token to connect to customer portal

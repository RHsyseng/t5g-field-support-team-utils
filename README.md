# T5G Field Support Team Utils

This repository contains utilities to help the SysDesEng Telco5G Field Support Team.

## telco5g-jira

This directory contains a script to parse an email that contains a Saleforce
Telco5G Open case report. After the script parses the email, it then parses a
Jira board for existing cases and reports on any new cases that need Jira cards
created based upon the case priority (Normal, High, and Urgent).

If desired, the script will also create the Jira cards for the new cases.

Link to script usage: [telco5g-jira.py readme](https://github.com/RHsyseng/t5g-field-support-team-utils/blob/main/telco5g-jira.py.md)

## CI

This project has a CI that is triggered on every push.

Note: There are some environment variables which needed to be set in the GitLab:
Jira_Pass - The Jira details to Connect to the board
OCP_USER & OCP_PASS - Connection detilas to our LAB OCP
Offline_token - API token to connect to customer portal

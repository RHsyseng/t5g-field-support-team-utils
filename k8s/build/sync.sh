#!/bin/bash
if [[ -f /srv/cfg/t5g.cfg ]]; then
  python3 /app/bin/telco5g-jira.py /srv/cfg/t5g.cfg
else
  echo "config file not found"
fi

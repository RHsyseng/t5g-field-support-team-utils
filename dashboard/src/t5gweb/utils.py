"""utils.py: utility functions for the t5gweb"""

import datetime
import json
import logging
import os
import random
import re
import smtplib
from email.message import EmailMessage

import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def email_notify(ini, message_content, recipient=None, subject=None):
    """send an email to notify the team of a new case"""

    body = ""
    for card in message_content:
        body += message_content[card]["full_message"]

    msg = EmailMessage()
    msg.set_content(body)

    msg["Subject"] = ini[subject] if subject else ini["subject"]
    msg["From"] = ini["from"]
    msg["To"] = ini[recipient] if recipient else ini["to"]
    sendmail = smtplib.SMTP(ini["smtp"])
    sendmail.send_message(msg)
    sendmail.quit()


def exists_or_zero(data, key):
    """hack for when a new data point is added -> history does not exist"""
    if key in data.keys():
        return data[key]
    return 0


def get_random_member(team, last_choice=None):
    """Randomly pick a team member and avoid picking the same person twice in a row"""

    if len(team) > 1:
        if last_choice is not None:
            team = [member for member in team if member != last_choice]
        current_choice = random.choice(team)
    elif len(team) == 1:
        current_choice = team[0]
    else:
        logging.warning("No team variable is available, cannot assign case.")
        current_choice = None

    return current_choice


def get_token(offline_token):
    """get a portal access token"""
    # https://access.redhat.com/articles/3626371
    data = {
        "grant_type": "refresh_token",
        "client_id": "rhsm-api",
        "refresh_token": offline_token,
    }
    url = (
        "https://sso.redhat.com"
        "/auth/realms/redhat-external/protocol/openid-connect/token"
    )
    response = requests.post(url, data=data, timeout=5)
    # It returns 'application/x-www-form-urlencoded'
    token = response.json()["access_token"]
    return token


def read_config(file):
    """
    Takes a filename as input and reads the values into a dictionary.
    file should be in the format of "key: value" pairs. no value will
    simply set the key in the dictionary.
    e.g.
        debug
        email : me@redhat.com, you@redhat.com
        email: me@redhat.com, you@redhat.com
        email:me@redhat.com, you@redhat.com
    """

    cfg_dict = {}
    with open(file, encoding="utf-8") as filep:
        for line in filep:
            if not line.startswith("#") and not line.startswith(";"):
                cfg_pair = line.split(":", 1)
                key = cfg_pair[0].replace("\n", "").strip()

                if len(cfg_pair) > 1:
                    value = cfg_pair[1].replace("\n", "").strip()
                    cfg_dict[key] = value
                elif len(key) > 0:
                    cfg_dict[key] = True
    return cfg_dict


def read_env_config(keys):
    """read configuration values from OS environment variables"""
    ecfg = {}

    for key in keys:
        if "t5g_" + key in os.environ:
            ecfg[key] = os.environ.get("t5g_" + key)

    return ecfg


def set_cfg():
    """generate the working config"""
    # Set the default configuration values
    cfg = set_defaults()

    # Override the defaults and configuration file settings
    # with any environmental settings
    trcfg = read_env_config(cfg.keys())
    for key, value in trcfg.items():
        cfg[key] = value

    # env overrides
    cfg["team"] = json.loads(os.environ.get("team")) if os.environ.get("team") else None
    # sources
    cfg["offline_token"] = os.environ.get("offline_token")  # portal
    cfg["redhat_api"] = os.environ.get("redhat_api")  # redhat api url
    cfg["query"] = os.environ.get("case_query")
    cfg["max_portal_results"] = os.environ.get("max_portal_results")
    cfg["bz_key"] = os.environ.get("bz_key")
    cfg["sheet_id"] = os.environ.get("sheet_id")
    cfg["jira_escalations_project"] = os.environ.get("jira_escalations_project")
    cfg["jira_escalations_label"] = os.environ.get("jira_escalations_label")
    # email
    cfg["smtp"] = os.environ.get("smtp_server")
    cfg["from"] = os.environ.get("source_email")
    cfg["to"] = os.environ.get("notification_email")
    cfg["subject"] = os.environ.get("email_subject")
    cfg["alert_email"] = os.environ.get("alert_email")
    # slack
    cfg["slack_token"] = os.environ.get("slack_token")
    cfg["high_severity_slack_channel"] = os.environ.get("high_severity_slack_channel")
    cfg["low_severity_slack_channel"] = os.environ.get("low_severity_slack_channel")

    # jira
    cfg["sprintname"] = os.environ.get("jira_sprint")
    cfg["server"] = os.environ.get("jira_server")
    cfg["project"] = os.environ.get("jira_project")
    cfg["component"] = os.environ.get("jira_component")
    cfg["board"] = os.environ.get("jira_board")
    cfg["jira_query"] = os.environ.get("jira_query")
    cfg["max_jira_results"] = os.environ.get("max_jira_results")
    cfg["password"] = os.environ.get("jira_pass")
    cfg["labels"] = (
        os.environ.get("jira_labels").split(",")
        if os.environ.get("jira_labels")
        else []
    )
    if os.environ.get("sla_settings"):
        cfg["sla_settings"] = json.loads(os.environ.get("sla_settings"))
    # sso
    cfg["rbac"] = os.environ.get("rbac").split(",") if os.environ.get("rbac") else []
    cfg["max_to_create"] = os.environ.get("max_to_create")
    return cfg


def set_defaults():
    """set default configuration values"""
    defaults = {}
    defaults["smtp"] = "localhost"
    defaults["from"] = "dashboard@example.com"
    defaults["to"] = ""
    defaults["alert_email"] = "root@localhost"
    defaults["subject"] = "New Card(s) Have Been Created to Track Issues"
    defaults["sprintname"] = ""
    defaults["server"] = ""
    defaults["project"] = ""
    defaults["component"] = ""
    defaults["board"] = ""
    defaults["email"] = ""
    defaults["type"] = "Story"
    defaults["labels"] = ""
    defaults["priority"] = "High"
    defaults["points"] = 3
    defaults["password"] = ""
    defaults["card_action"] = "none"
    defaults["debug"] = "False"
    defaults["team"] = []
    defaults["fields"] = [
        "case_account_name",
        "case_summary",
        "case_number",
        "case_status",
        "case_owner",
        "case_severity",
        "case_createdDate",
        "case_lastModifiedDate",
        "case_bugzillaNumber",
        "case_description",
        "case_tags",
        "case_product",
        "case_version",
        "case_closedDate",
    ]
    defaults["slack_token"] = ""
    defaults["high_severity_slack_channel"] = ""
    defaults["low_severity_slack_channel"] = ""
    defaults["max_jira_results"] = 1000
    defaults["max_portal_results"] = 5000
    defaults["sla_settings"] = {
        "days": {"Urgent": 14, "High": 20, "Normal": 90, "Low": 180},
        "partners": [],
    }
    return defaults


def slack_notify(ini, notification_content):
    """notify the team of new cases via slack"""
    logging.warning("Notifying team on slack")
    logging.warning(notification_content)

    client = WebClient(token=ini["slack_token"])

    for card in notification_content:
        body = notification_content[card]["body"]

        user_id = None
        if notification_content[card]["assignee"]:
            for member in ini["team"]:
                if member["name"] == notification_content[card]["assignee"]:
                    user_id = member["slack_user"]

        # Add ping
        if user_id:
            body = re.sub(
                r"It is initially being tracked by.*",
                f"It is initially being tracked by <@{user_id}>",
                body,
                1,
            )

        # Get severity #. Ex: "3 (Normal)" => "3"
        severity = re.search(r"\d+", notification_content[card]["severity"])
        description = notification_content[card]["description"]

        # Posting Summaries + reply with Description
        if severity and int(severity.group()) < 3:
            channel = ini["high_severity_slack_channel"]
        else:
            channel = ini["low_severity_slack_channel"]
        try:
            message = client.chat_postMessage(channel=channel, text=body)
            client.chat_postMessage(
                channel=channel, text=description, thread_ts=message["ts"]
            )
        except SlackApiError as slack_error:
            logging.warning("failed to post to slack: %s", slack_error)


def make_pie_dict(stats):
    """get the code simplified"""
    return {
        "by_severity": (
            list(stats["by_severity"].keys()),
            list(stats["by_severity"].values()),
        ),
        "by_status": (
            list(stats["by_status"].keys()),
            list(stats["by_status"].values()),
        ),
    }


def get_fake_data(path="data/fake_data.json"):
    """Retrieve fake data from JSON file

    Args:
        path (str, optional): Path to JSON. Defaults to "data/fake_data.json".

    Returns:
        dict: Dictionary that contains deserialized JSON data
    """
    path = os.path.abspath(path)
    with open(path, encoding="utf-8") as fake_data:
        data = json.load(fake_data)
    return data


def make_headers(token):
    """Builds the HTTP headers for API requests

    Args:
        token(str): A valid bearer token

    Returns:
        dict: valid headers for use with the requests module
    """
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    return headers


def format_date(the_date):
    """Converts a date string in to the required format

    Args:
        date(str): A date stored as a string

    Returns:
        datetime.date: A datetime object
    """
    formatted_date = datetime.datetime.strptime(the_date, "%Y-%m-%dT%H:%M:%SZ")
    return formatted_date

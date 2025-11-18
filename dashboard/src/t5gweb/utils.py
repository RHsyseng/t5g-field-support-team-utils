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
    """Send email notification about new cases or updates

    Composes and sends an email using SMTP with content from multiple cards.
    Concatenates all card messages into a single email body.

    Args:
        ini: Configuration dictionary containing SMTP settings (smtp, from, to,
            subject)
        message_content: Dictionary of card messages, each containing a
            'full_message' key with the message text
        recipient: Optional config key for recipient email address. If None,
            uses 'to' from ini. Defaults to None.
        subject: Optional config key for email subject. If None, uses 'subject'
            from ini. Defaults to None.

    Returns:
        None. Sends email via SMTP and closes connection.
    """

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
    """Safely retrieve value from dictionary or return 0 if missing

    Helper function to handle cases where historical data points don't exist
    yet in statistics dictionaries. Returns 0 as a safe default for numeric
    data.

    Args:
        data: Dictionary to retrieve value from
        key: Key to look up in the dictionary

    Returns:
        The value if key exists, 0 otherwise
    """
    if key in data.keys():
        return data[key]
    return 0


def get_random_member(team, last_choice=None):
    """Randomly select a team member for case assignment

    Selects a random team member from the provided list, with logic to avoid
    assigning to the same person consecutively when multiple team members are
    available.

    Args:
        team: List of team member dictionaries
        last_choice: Previously selected team member to avoid reselecting.
            Defaults to None.

    Returns:
        dict: Randomly selected team member dictionary, or None if team is empty
    """

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
    """Exchange offline token for Red Hat Portal access token

    Uses the Red Hat SSO service to exchange a refresh token (offline token)
    for a short-lived access token. See:
    https://access.redhat.com/articles/3626371

    Args:
        offline_token: Red Hat offline/refresh token for authentication

    Returns:
        str: Bearer access token for Red Hat Portal API requests
    """
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
    """Read configuration from a key-value file

    Parses a configuration file with key-value pairs separated by colons.
    Keys without values are set to True. Lines starting with # or ; are
    treated as comments and ignored.

    Args:
        file: Path to configuration file

    Returns:
        dict: Configuration dictionary with parsed key-value pairs
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
    """Read configuration values from environment variables

    Retrieves configuration values from environment variables prefixed with
    't5g_'. Only reads values for keys provided in the input list.

    Args:
        keys: List of configuration key names to look up (without t5g_ prefix)

    Returns:
        dict: Configuration dictionary with values from environment variables
    """
    ecfg = {}

    for key in keys:
        if "t5g_" + key in os.environ:
            ecfg[key] = os.environ.get("t5g_" + key)

    return ecfg


def set_cfg():
    """Generate complete configuration from defaults and environment variables

    Creates the working configuration by combining default values with
    environment variable overrides. Loads settings for Red Hat Portal API,
    JIRA, email, Slack, PostgreSQL, and SAML authentication.

    Returns:
        dict: Complete configuration dictionary with all settings including:
            - API credentials and endpoints (Portal, JIRA, Bugzilla)
            - Email and Slack notification settings
            - Team member assignments
            - Database connection parameters
            - RBAC and authentication settings
            - Query and result limits
    """
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

    # postgres
    cfg["POSTGRESQL_USER"] = os.environ.get("POSTGRESQL_USER")
    cfg["POSTGRESQL_PASSWORD"] = os.environ.get("POSTGRESQL_PASSWORD")
    cfg["POSTGRESQL_SERVICE_HOST"] = os.environ.get("POSTGRESQL_SERVICE_HOST")
    cfg["POSTGRESQL_SERVICE_PORT"] = os.environ.get("POSTGRESQL_SERVICE_PORT")
    cfg["POSTGRESQL_DATABASE"] = os.environ.get("POSTGRESQL_DATABASE")
    # sso
    cfg["rbac"] = os.environ.get("rbac").split(",") if os.environ.get("rbac") else []
    cfg["max_to_create"] = os.environ.get("max_to_create")
    return cfg


def set_defaults():
    """Set default configuration values for the application

    Defines default values for all configuration parameters including SMTP
    settings, JIRA fields, team settings, API limits, and SLA thresholds.
    These defaults can be overridden by environment variables.

    Returns:
        dict: Dictionary containing default configuration values for:
            - Email settings (SMTP, from, to, subject)
            - JIRA settings (server, project, component, board, etc.)
            - Portal API field lists
            - Slack settings
            - API result limits
            - SLA day thresholds by severity level
    """
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
    """Send Slack notifications for new cases

    Posts notifications to Slack channels based on case severity. High/urgent
    severity cases (1-2) go to high_severity_slack_channel, others go to
    low_severity_slack_channel. Mentions assignees using their Slack user ID
    and posts case descriptions as threaded replies.

    Args:
        ini: Configuration dictionary containing slack_token, team info, and
            channel settings
        notification_content: Dictionary of card notifications, each containing
            'body', 'assignee', 'severity', and 'description' keys

    Returns:
        None. Posts messages to Slack channels via API.
    """
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
    """Transform statistics into format suitable for pie chart rendering

    Converts statistics dictionary into a simplified structure with separate
    keys and values lists for by_severity and by_status categories, suitable
    for chart libraries.

    Args:
        stats: Statistics dictionary containing 'by_severity' and 'by_status'
            sub-dictionaries

    Returns:
        dict: Dictionary with 'by_severity' and 'by_status' keys, each
            containing a tuple of (labels_list, values_list)
    """
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


def format_comment(comment):
    """Format a JIRA comment for HTML display with clickable links

    Converts JIRA text formatting to HTML by:
    - Converting plain URLs to clickable anchor tags
    - Converting JIRA [text|url] link syntax to HTML anchor tags
    - Setting links to open in new tabs (target='_blank')

    Args:
        comment: JIRA comment object with body attribute

    Returns:
        str: HTML-formatted comment body with clickable links
    """
    body = comment.body
    body = re.sub(
        (
            r"(?<!\||\s)\s*?((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))"
            r"([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?)"
        ),
        '<a href="' + r"\g<0>" + "\" target='_blank'>" + r"\g<0>" "</a>",
        body,
    )
    body = re.sub(
        (
            r'\[([\s\w!"#$%&\'()*+,-.\/:;<=>?@[^_`{|}~]*?\s*?)\|\s*?'
            r"((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))"
            r"([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?[\s]*)\]"
        ),
        '<a href="' + r"\2" + "\" target='_blank'>" + r"\1" + "</a>",
        body,
    )
    return body

"""libtelco5g: functions for t5gweb"""

from __future__ import print_function

import datetime
import json
import logging
import re
import statistics
import time
from urllib.parse import urlparse

import redis
import requests
from jira import JIRA
from jira.exceptions import JIRAError
from slack_sdk import WebClient
from t5gweb.utils import (
    email_notify,
    exists_or_zero,
    format_date,
    get_random_member,
    get_token,
    make_headers,
    set_cfg,
    slack_notify,
)

# for portal to jira mapping
portal2jira_sevs = {
    "1 (Urgent)": "Critical",
    "2 (High)": "Major",
    "3 (Normal)": "Normal",
    "4 (Low)": "Minor",
}

# card status mappings
status_map = {
    "New": "New",
    "To Do": "Backlog",
    "Open": "Debugging",
    "In Progress": "Eng Working",
    "Code Review": "Backport",
    "QE Review": "Ready To Close",
    "Blocked": "Blocked",
    "Won't Fix / Obsolete": "Done",
    "Done": "Done",
    "Closed": "Done",
}


def jira_connection(cfg):
    """Initiate a connection to the JIRA server

    Creates and returns an authenticated JIRA connection using token-based
    authentication from the configuration.

    Args:
        cfg: Configuration dictionary containing 'server' (JIRA server URL)
            and 'password' (authentication token)

    Returns:
        JIRA: Authenticated JIRA connection object
    """

    logging.warning("attempting to connect to jira...")
    jira = JIRA(server=cfg["server"], token_auth=cfg["password"])

    return jira


def get_project_id(conn, name):
    """Take a project name and return its JIRA project object

    Retrieves a JIRA project object by name, which contains project metadata
    including components, description, ID, key, and name.

    Args:
        conn: JIRA connection object
        name: Project name to look up

    Returns:
        Project: JIRA project object with the following notable fields:
            - components: List of JIRA component objects
            - description: Project description string
            - id: Numerical string identifier
            - key: Project key string (e.g., 'KNIECO')
            - name: Full project name (e.g., 'KNI Ecosystem')
    """

    project = conn.project(name)
    logging.warning("project: %s", project)
    return project


def get_board_id(conn, name):
    """Take a board name as input and return its JIRA board object

    Retrieves a JIRA board object by name from the list of matching boards.

    Args:
        conn: JIRA connection object
        name: Board name to search for

    Returns:
        Board: JIRA board object with the following notable fields:
            - id: Numerical string identifier
            - name: Board name (e.g., 'My Stuff To Do')
    """

    boards = conn.boards(name=name)
    logging.warning("board: %s", boards[0])
    return boards[0]


def get_previous_card(conn, cfg, case):
    """Find the first existing JIRA card associated with a case number

    Searches for JIRA issues in the configured project that have the case
    number in their summary field.

    Args:
        conn: JIRA connection object
        cfg: Configuration dictionary containing project information
        case: Case number to search for

    Returns:
        Issue: First matching JIRA issue object, or None if no match found
    """
    previous_issues_query = f"project = {cfg['project']} AND summary ~ '{case}'"
    previous_issues = conn.search_issues(previous_issues_query)
    if len(previous_issues) > 0:
        return previous_issues[0]
    return None


def get_latest_sprint(conn, bid, sprintname):
    """Take a board id and return the current active sprint

    Retrieves the first active sprint for a given board.

    Args:
        conn: JIRA connection object
        bid: Board ID to query
        sprintname: Sprint name pattern (not currently used in implementation)

    Returns:
        Sprint: JIRA sprint object with the following notable fields:
            - id: Numerical string identifier
            - name: Sprint name (e.g., 'ECO Labs & Field Sprint 188')
    """

    sprints = conn.sprints(bid, state="active")
    return sprints[0]


def get_last_sprint(conn, bid, sprintname):
    """Get the previous sprint based on current sprint number

    Finds the sprint immediately preceding the current active sprint by
    decrementing the sprint number from the current sprint name.

    Args:
        conn: JIRA connection object
        bid: Board ID to query
        sprintname: Sprint name pattern to match

    Returns:
        Sprint: JIRA sprint object for the previous sprint, or None if not found
    """
    this_sprint = get_latest_sprint(conn, bid, sprintname)
    sprint_number = re.search(r"\d*$", this_sprint.name)[0]
    last_sprint_number = int(sprint_number) - 1
    board = conn.sprints(bid)  # still seems to return everything?
    last_sprint_name = sprintname + ".*" + str(last_sprint_number)

    for b in board:
        if re.search(last_sprint_name, b.name):
            return b


def get_sprint_summary(conn, bid, sprintname, team):
    """Print summary of completed cards per team member for the last sprint

    Queries JIRA for completed cards in the previous sprint and prints the
    count of completed cards for each team member.

    Args:
        conn: JIRA connection object
        bid: Board ID to query
        sprintname: Sprint name pattern
        team: List of team member dictionaries containing 'jira_user' and 'name'

    Returns:
        None. Prints completion statistics to stdout.
    """
    last_sprint = get_last_sprint(conn, bid, sprintname)
    sid = last_sprint.id

    for member in team:
        user = member["jira_user"]
        user = user.replace("@", "\\u0040")
        completed_cards = conn.search_issues(
            "sprint="
            + str(sid)
            + " and assignee = "
            + str(user)
            + ' and status = "DONE"',
            0,
            1000,
        ).iterable
        print("%s completed %d cards" % (member["name"], len(completed_cards)))


def get_card_summary():
    """Generate summary counts of cards by status

    Retrieves cached cards and counts how many are in each status category.

    Returns:
        dict: Dictionary with counts for each status:
            - backlog: Count of cards in Backlog status
            - debugging: Count of cards in Debugging status
            - eng_working: Count of cards in Eng Working status
            - backport: Count of cards in Backport status
            - ready_to_close: Count of cards in Ready To Close status
            - done: Count of cards in Done status
    """
    cards = redis_get("cards")
    backlog = [card for card in cards if cards[card]["card_status"] == "Backlog"]
    debugging = [card for card in cards if cards[card]["card_status"] == "Debugging"]
    eng_working = [
        card for card in cards if cards[card]["card_status"] == "Eng Working"
    ]
    backport = [card for card in cards if cards[card]["card_status"] == "Backport"]
    ready_to_close = [
        card for card in cards if cards[card]["card_status"] == "Ready To Close"
    ]
    done = [card for card in cards if cards[card]["card_status"] == "Done"]

    summary = {}
    summary["backlog"] = len(backlog)
    summary["debugging"] = len(debugging)
    summary["eng_working"] = len(eng_working)
    summary["backport"] = len(backport)
    summary["ready_to_close"] = len(ready_to_close)
    summary["done"] = len(done)
    return summary


def get_case_number(link, pfilter="cases"):
    """Extract case number from Red Hat Support Case URL

    Parses Red Hat support case URLs and extracts the case number from
    various URL formats including fragment-based and path-based formats.

    Args:
        link: Red Hat support case URL (e.g.,
            'https://access.redhat.com/support/cases/0123456' or
            'https://access.redhat.com/support/cases/#/case/0123456')
        pfilter: URL filter type, currently only 'cases' is supported.
            Defaults to 'cases'.

    Returns:
        str: Case number if found, empty string otherwise
    """
    parsed_url = urlparse(link)

    if pfilter == "cases":
        if "cases" in parsed_url.path and parsed_url.netloc == "access.redhat.com":
            if len(parsed_url.fragment) > 0 and "case" in parsed_url.fragment:
                return parsed_url.fragment.split("/")[2]
            if len(parsed_url.path) > 0 and "cases" in parsed_url.path:
                return parsed_url.path.split("/")[3]
    return ""


def add_watcher_to_case(cfg, case, username, token):
    """Add a new watcher to a Red Hat support case

    Makes a POST request to the Red Hat Portal API to add a user as a watcher
    (notified user) on a support case.

    Args:
        cfg: Configuration dictionary containing 'redhat_api' endpoint
        case: Case number to add watcher to
        username: SSO username of the user to add as a watcher
        token: Red Hat API authentication token

    Returns:
        bool: True if user was successfully added as watcher, False otherwise
    """

    logging.warning(f"Adding watcher {username} to case {case}")
    # Add the new watcher to the list of notified users
    payload = {"user": [{"ssoUsername": username}]}

    # Send the POST request to add the watcher
    headers = make_headers(token)
    url = f"{cfg['redhat_api']}/v1/cases/{case}/notifiedusers"
    response = requests.post(url, headers=headers, json=payload)

    # Check the response status code.
    if response.status_code != 201:
        logging.error(
            f"Failed to add user {username} as a watcher - case {case}: {response}"
        )
        return False
    else:
        logging.warning(f"User {username} added as a watcher - case {case}")

    # If the request is successful, return True
    return True


def create_cards(cfg, new_cases, action="none"):
    """Create JIRA cards for new support cases

    Processes a list of new cases and creates corresponding JIRA cards,
    assigns them to team members, adds watchers, and generates notifications.

    Args:
        cfg: Configuration dictionary containing JIRA settings, team info,
            and notification settings
        new_cases: List of case numbers that need JIRA cards created
        action: Action to perform. Must be 'create' to actually create cards,
            otherwise returns empty results. Defaults to 'none'.

    Returns:
        tuple: A 3-tuple containing:
            - notification_content: Dictionary of notification messages keyed by
              card key
            - new_cards: Dictionary of created card data keyed by card key
            - novel_cases: List of case numbers for which cards were created
    """
    if action != "create":
        return {}, {}, []

    # Setup connections and get prerequisites
    context = _setup_card_creation_context(cfg)
    cases = redis_get("cases")

    # Filter cases that need cards
    novel_cases = _filter_novel_cases(new_cases, context["created_cases"])

    # Process each case
    new_cards = {}
    notification_content = {}

    for case in novel_cases:
        result = _process_single_case(case, cases, context, cfg)
        if result:
            new_cards[result["card_key"]] = result["card_data"]
            notification_content[result["card_key"]] = result["notification"]

    return notification_content, new_cards, novel_cases


def _setup_card_creation_context(cfg):
    """Setup all connections and get required data for card creation

    Initializes JIRA connection, retrieves board and sprint information,
    and gets list of already created cases.

    Args:
        cfg: Configuration dictionary containing JIRA connection parameters,
            board name, sprint name, and API credentials

    Returns:
        dict: Context dictionary containing:
            - jira_conn: Active JIRA connection object
            - board: JIRA board object
            - token: Red Hat API authentication token
            - sprint: Current active sprint object
            - created_cases: List of case numbers that already have cards

    Raises:
        ValueError: If no sprintname is defined in configuration
    """
    logging.warning("Setting up card creation context...")

    jira_conn = jira_connection(cfg)
    board = get_board_id(jira_conn, cfg["board"])
    token = get_token(cfg["offline_token"])

    if not cfg["sprintname"]:
        raise ValueError("No sprintname is defined.")

    sprint = get_latest_sprint(jira_conn, board.id, cfg["sprintname"])
    created_cards = get_issues_in_sprint(cfg, sprint, jira_conn)
    created_cases = [card["fields"]["summary"].split(":")[0] for card in created_cards]

    return {
        "jira_conn": jira_conn,
        "board": board,
        "token": token,
        "sprint": sprint,
        "created_cases": created_cases,
    }


def _filter_novel_cases(new_cases, created_cases):
    """Filter out cases that already have cards

    Compares the list of new cases against already created cases and returns
    only those that don't have existing cards.

    Args:
        new_cases: List of case numbers that potentially need cards
        created_cases: List of case numbers that already have JIRA cards

    Returns:
        list: Case numbers that need new cards created
    """
    novel_cases = []
    for case in new_cases:
        if case in created_cases:
            logging.warning(f"Card already exists for {case}, moving on.")
        else:
            novel_cases.append(case)
    return novel_cases


def _notify_slack_error(cfg, case, error_msg):
    """Send a Slack notification when JIRA card creation fails.

    Posts an error message to the low severity Slack channel to alert the team
    that a card could not be created for a case.

    Args:
        cfg: Configuration dictionary containing slack_token and channel settings
        case: Case number that failed
        error_msg: Error message describing the failure
    """
    if not cfg.get("slack_token") or not cfg.get("low_severity_slack_channel"):
        logging.warning("Cannot notify Slack: missing token or channel config")
        return

    try:
        client = WebClient(token=cfg["slack_token"])
        message = (
            f":warning: Failed to create JIRA card for case {case}\n"
            f"Error: {error_msg[:200]}"  # Truncate long error messages
        )
        client.chat_postMessage(
            channel=cfg["low_severity_slack_channel"],
            text=message,
        )
    except Exception as slack_err:
        logging.error(f"Failed to send Slack error notification: {slack_err}")


def _process_single_case(case, cases, context, cfg):
    """Process a single case and create its JIRA card

    Handles the complete workflow for creating a JIRA card from a case,
    including checking for old cases, assigning, adding watchers, creating
    the card, and generating notifications.

    Args:
        case: Case number to process
        cases: Dictionary of all case data
        context: Context dictionary from _setup_card_creation_context
        cfg: Configuration dictionary

    Returns:
        dict: Dictionary containing 'card_key', 'card_data', and 'notification'
            if successful, None if case was handled by reopening existing card
    """
    # Handle old cases with potential previous cards
    if _is_old_case(cases[case]):
        if _handle_old_case(case, context, cfg):
            return None  # Case was handled by reopening existing card

    # Determine assignee
    assignee = _determine_assignee(case, cases, cfg)

    # Add watcher if needed
    if assignee and assignee.get("notifieduser", "true") == "true":
        add_watcher_to_case(cfg, case, assignee["jira_user"], context["token"])

    # Create the card
    card_info = _build_card_info(case, cases, cfg, assignee)
    try:
        new_card = _create_jira_card(card_info, context["jira_conn"])
    except JIRAError as e:
        logging.error(f"Failed to create JIRA card for case {case}: {e}")
        _notify_slack_error(cfg, case, str(e))
        return None

    # Post-process the card
    _post_process_card(new_card, case, cases, context, cfg)

    # Generate notification content
    notification = generate_notification_content(cfg, assignee, new_card, case, cases)

    # Build card data for return
    card_data = _build_card_data(new_card, case, cases, cfg, assignee)

    return {
        "card_key": new_card.key,
        "card_data": card_data,
        "notification": notification,
    }


def _is_old_case(case_data):
    """Check if case is older than 15 days

    Compares case creation date against current date to determine if case
    is considered "old" (created more than 15 days ago).

    Args:
        case_data: Dictionary containing case information including 'createdate'

    Returns:
        bool: True if case is older than 15 days, False otherwise
    """
    case_creation_date = datetime.datetime.strptime(
        case_data["createdate"], "%Y-%m-%dT%H:%M:%SZ"
    )
    date_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return case_creation_date < date_now - datetime.timedelta(days=15)


def _handle_old_case(case, context, cfg):
    """Handle old cases by checking for and reopening previous cards

    Searches for existing JIRA cards associated with the case and reopens
    them if found, rather than creating a new card.

    Args:
        case: Case number to check
        context: Context dictionary containing JIRA connection and sprint info
        cfg: Configuration dictionary

    Returns:
        bool: True if previous card was found and reopened, False otherwise
    """
    previous_issue = get_previous_card(context["jira_conn"], cfg, case)
    if previous_issue:
        logging.warning(
            f"Updating: {previous_issue.key} rather than creating new card."
        )
        context["jira_conn"].add_issues_to_sprint(
            context["sprint"].id, [previous_issue.key]
        )
        context["jira_conn"].transition_issue(previous_issue, "11")
        context["jira_conn"].add_comment(
            previous_issue,
            f"Case {case} seems to have been reopened. The dashboard found "
            "this card linked to the case and reopened it automatically.",
        )
        return True
    return False


def _determine_assignee(case, cases, cfg):
    """Determine who should be assigned to the case

    Matches case to team member based on account assignment. If no match is
    found, assigns randomly to a team member using round-robin logic.

    Args:
        case: Case number to assign
        cases: Dictionary of all case data
        cfg: Configuration dictionary containing team member information

    Returns:
        dict: Team member dictionary with assignment info, or None if no team
            configured
    """
    if not cfg["team"]:
        return None

    # Try to match by account
    for member in cfg["team"]:
        for account in member["accounts"]:
            if account.lower() in cases[case]["account"].lower():
                member["displayName"] = member["name"]
                return member

    # No match found, assign randomly
    last_choice = redis_get("last_choice")
    assignee = get_random_member(cfg["team"], last_choice)
    redis_set("last_choice", json.dumps(assignee))
    assignee["displayName"] = assignee["name"]
    return assignee


def _build_card_info(case, cases, cfg, assignee):
    """Build the card info dictionary for JIRA card creation

    Constructs the fields dictionary required to create a JIRA issue,
    including project, type, components, priority, labels, summary,
    description, and assignee.

    Args:
        case: Case number for the card
        cases: Dictionary of all case data
        cfg: Configuration dictionary with JIRA field defaults
        assignee: Team member dictionary, or None if unassigned

    Returns:
        dict: JIRA issue fields dictionary ready for card creation
    """
    priority = portal2jira_sevs[cases[case]["severity"]]

    severity = cases[case]["severity"]
    account = cases[case]["account"]
    status = cases[case]["status"]
    description = cases[case]["description"]

    full_description = (
        "This card was automatically created from the Case Dashboard Sync Job.\r\n"
        "\r\n"
        f"This card was created because it had a severity of {severity}\r\n"
        f"The account for the case is {account}\r\n"
        f"The case had an internal status of: {status}\r\n"
        "\r\n*Description:* \r\n\r\n"
        f"{description}\r\n"
    )

    summary = f"{case}: {cases[case]['problem']}"

    card_info = {
        "project": {"key": cfg["project"]},
        "issuetype": {"name": cfg["type"]},
        "components": [{"name": cfg["component"]}],
        "priority": {"name": priority},
        "labels": cfg["labels"],
        "summary": summary[:253] + ".." if len(summary) > 253 else summary,
        "description": (
            full_description[:253] + ".."
            if len(full_description) > 253
            else full_description
        ),
    }

    if assignee:
        card_info["assignee"] = {"name": assignee["jira_user"]}

    return card_info


def _create_jira_card(card_info, jira_conn):
    """Create the JIRA card

    Creates a new JIRA issue using the provided card information and sets
    the ticket tracking field.

    Args:
        card_info: Dictionary containing JIRA issue fields
        jira_conn: Active JIRA connection object

    Returns:
        Issue: Newly created JIRA issue object
    """
    logging.warning(f"Creating card for case {card_info['summary'].split(':')[0]}")
    new_card = jira_conn.create_issue(fields=card_info)
    new_card.update(fields={"customfield_12317313": "TRACK"})
    logging.warning(f"Created {new_card.key}")
    return new_card


def _post_process_card(new_card, case, cases, context, cfg):
    """Handle post-creation card processing: sprint, status, links

    Performs post-creation steps including adding the card to the sprint,
    updating status if needed, and adding support case and bugzilla links.

    Args:
        new_card: Newly created JIRA issue object
        case: Case number associated with the card
        cases: Dictionary of all case data
        context: Context dictionary containing sprint information
        cfg: Configuration dictionary
    """
    # Add to sprint
    if cfg["sprintname"]:
        logging.warning(f"Moving card to sprint {context['sprint'].id}")
        context["jira_conn"].add_issues_to_sprint(context["sprint"].id, [new_card.key])

    # Update status
    if new_card.fields.status.name not in ["New", "To Do"]:
        logging.warning('Moving card from backlog to "To Do" column')
        context["jira_conn"].transition_issue(new_card.key, "To Do")

    # Add links
    _add_card_links(new_card, case, cases, context["jira_conn"])


def _add_card_links(new_card, case, cases, jira_conn):
    """Add support case and bugzilla links to the card

    Adds web links to the JIRA card for the Red Hat support case and any
    associated bugzilla bugs.

    Args:
        new_card: JIRA issue object to add links to
        case: Case number to link
        cases: Dictionary of all case data
        jira_conn: Active JIRA connection object
    """
    # Support case link
    logging.warning(f"Adding link to support case {case}")
    jira_conn.add_simple_link(
        new_card.key,
        {
            "url": f"https://access.redhat.com/support/cases/{case}",
            "title": "Support Case",
        },
    )

    # Bugzilla link if exists
    if "bug" in cases[case]:
        bug_id = cases[case]["bug"]
        logging.warning(f"Adding link to BZ {bug_id}")
        jira_conn.add_simple_link(
            new_card.key,
            {
                "url": f"https://bugzilla.redhat.com/show_bug.cgi?id={bug_id}",
                "title": f"BZ {bug_id}",
            },
        )


def _build_card_data(new_card, case, cases, cfg, assignee):
    """Build the card data dictionary for return

    Constructs a standardized card data dictionary from the JIRA card and
    case information.

    Args:
        new_card: Newly created JIRA issue object
        case: Case number for the card
        cases: Dictionary of all case data
        cfg: Configuration dictionary
        assignee: Team member dictionary

    Returns:
        dict: Complete card data dictionary with all relevant fields
    """
    tags = cases[case].get("tags", [])
    bz = cases[case].get("bug", [])

    return {
        "card_status": status_map[new_card.fields.status.name],
        "card_created": new_card.fields.created,
        "account": cases[case]["account"],
        "summary": f"{case}: {cases[case]['problem']}",
        "description": cases[case]["description"],
        "comments": None,
        "assignee": assignee,
        "case_number": case,
        "tags": tags,
        "labels": cfg["labels"],
        "bugzilla": bz,
        "severity": re.search(r"[a-zA-Z]+", cases[case]["severity"]).group(),
        "priority": new_card.fields.priority.name,
        "case_status": cases[case]["status"],
        "escalated": False,
        "crit_sit": False,
    }


def generate_notification_content(cfg, assignee, new_card, case, cases):
    """Generate notification message for email's and Slack

    Args:
        cfg (dict): Pre-configured settings
        assignee (dict): Information about the card's assignee
        new_card (str): Name of created JIRA card
        case (str): ID of relevant case
        cases (dict): Contains further information about cases

    Returns:
        dict: Notification message and extra information to construct slack message.
    """
    if assignee:
        assignee_section = f"It is initially being tracked by {assignee['name']}."
    else:
        assignee_section = "It is not assigned to anyone."
    notification_content = {}
    notification_content["body"] = (
        f"A JIRA issue ({cfg['server']}/browse/{new_card}) has been created"
        f" for a new case:\n"
        f"Case #: {case} (https://access.redhat.com/support/cases/{case})\n"
        f"Account: {cases[case]['account']}\n"
        f"Summary: {cases[case]['problem']}\n"
        f"Severity: {cases[case]['severity']}\n"
        f"{assignee_section}\n"
    )
    notification_content["severity"] = cases[case]["severity"]
    notification_content["description"] = f"Description: {cases[case]['description']}\n"
    notification_content["assignee"] = assignee["name"] if assignee else None
    notification_content["full_message"] = (
        notification_content["body"]
        + "\n"
        + notification_content["description"]
        + "\n===========================================\n\n"
    )
    return notification_content


def redis_set(key, value):
    """Store a key-value pair in Redis cache

    Connects to the Redis server and stores the provided value under the
    specified key.

    Args:
        key: Redis key name
        value: Value to store (should be JSON-serialized string for complex data)
    """
    logging.warning("syncing {}..".format(key))
    r_cache = redis.Redis(host="redis")
    r_cache.mset({key: value})
    logging.warning("{}....synced".format(key))


def redis_get(key):
    """Retrieve a value from Redis cache

    Connects to the Redis server and retrieves the value for the specified
    key. JSON-decodes the value if it exists.

    Args:
        key: Redis key name to retrieve

    Returns:
        dict or other: Deserialized value from Redis, or empty dict if key
            doesn't exist or connection fails
    """
    logging.warning("fetching {}..".format(key))
    r_cache = redis.Redis(host="redis")
    try:
        data = r_cache.get(key)
    except redis.exceptions.ConnectionError:
        logging.warning("Couldn't connect to redis host, setting data to None")
        data = None
    if data is not None:
        data = json.loads(data.decode("utf-8"))
    else:
        data = {}
    logging.warning("{} ....fetched".format(key))

    return data


def get_case_from_link(jira_conn, card):
    """Extract case number from JIRA card's remote links

    Searches through a JIRA card's remote links to find the support case link
    and extracts the case number from it.

    Args:
        jira_conn: Active JIRA connection object
        card: JIRA card key or object to search

    Returns:
        str: Case number if found, None otherwise
    """
    links = jira_conn.remote_links(card)
    for link in links:
        t = jira_conn.remote_link(card, link)
        if t.raw["object"]["title"] == "Support Case":
            case_number = get_case_number(t.raw["object"]["url"])
            if len(case_number) > 0:
                return case_number
    return None


def generate_stats(account=None, engineer=None):
    """Generate comprehensive statistics from cached cards and cases

    Analyzes cached card and case data to generate statistics including
    counts by customer, engineer, severity, status, high priority cases,
    escalations, open/closed case trends, and bug tracking metrics.

    Args:
        account: Optional account name to filter statistics. Defaults to None
            (all accounts).
        engineer: Optional engineer name to filter statistics. Defaults to None
            (all engineers).

    Returns:
        dict: Statistics dictionary containing:
            - by_customer: Dict of case counts per customer
            - by_engineer: Dict of case counts per engineer
            - by_severity: Dict of case counts per severity level
            - by_status: Dict of case counts per status
            - high_prio: Count of high/urgent severity cases
            - escalated: Count of escalated cases
            - open_cases: Total open cases count
            - weekly_closed_cases: Cases closed in last 7 days
            - weekly_opened_cases: Cases opened in last 7 days
            - daily_closed_cases: Cases closed in last day
            - daily_opened_cases: Cases opened in last day
            - no_updates: Cases with no updates in last 7 days
            - no_bzs: Cases without bugzilla or JIRA issues
            - bugs: Dict with 'unique' and 'no_target' bug counts
            - crit_sit: Count of critical situation cases
            - total_escalations: Total escalated and crit_sit cases
    """

    logging.warning("generating stats")
    start = time.time()

    cards = redis_get("cards")
    cases = redis_get("cases")
    bugs = redis_get("bugs")
    issues = redis_get("issues")

    if account is not None:
        logging.warning("filtering cases for {}".format(account))
        cards = {c: d for (c, d) in cards.items() if d["account"] == account}
        cases = {c: d for (c, d) in cases.items() if d["account"] == account}
    if engineer is not None:
        logging.warning("filtering cases for {}".format(engineer))
        cards = {
            c: d for (c, d) in cards.items() if d["assignee"]["displayName"] == engineer
        }

        # get case number and assignee from cards so that we can determine which cases
        # belong to the engineer
        temp_cases = {}
        for case, details in cases.items():
            for card in cards:
                if (
                    case == cards[card]["case_number"]
                    and cards[card]["assignee"]["displayName"] == engineer
                ):
                    temp_cases[case] = details
        cases = temp_cases

    today = datetime.date.today()

    customers = [cards[card]["account"] for card in cards]
    engineers = [
        cards[card]["assignee"]["displayName"]
        for card in cards
        if cards[card]["assignee"]["displayName"] is not None
    ]
    severities = [cards[card]["severity"] for card in cards]
    statuses = [cards[card]["case_status"] for card in cards]

    stats = {
        "by_customer": {c: 0 for c in customers},
        "by_engineer": {e: 0 for e in engineers},
        "by_severity": {s: 0 for s in severities},
        "by_status": {s: 0 for s in statuses},
        "high_prio": 0,
        "escalated": 0,
        "open_cases": 0,
        "weekly_closed_cases": 0,
        "weekly_opened_cases": 0,
        "daily_closed_cases": 0,
        "daily_opened_cases": 0,
        "no_updates": 0,
        "no_bzs": 0,
        "bugs": {"unique": 0, "no_target": 0},
        "crit_sit": 0,
        "total_escalations": 0,
    }

    for card, data in cards.items():
        account = data["account"]
        engineer = data["assignee"]["displayName"]
        severity = data["severity"]
        status = data["case_status"]

        stats["by_status"][status] += 1

        if status != "Closed":
            stats["by_customer"][account] += 1
            if engineer is not None:
                stats["by_engineer"][engineer] += 1
            stats["by_severity"][severity] += 1
            if severity == "High" or severity == "Urgent":
                stats["high_prio"] += 1
            if cards[card]["escalated"]:
                stats["escalated"] += 1
            if cards[card]["crit_sit"]:
                stats["crit_sit"] += 1
            if cards[card]["escalated"] or cards[card]["crit_sit"]:
                stats["total_escalations"] += 1
            if cards[card]["bugzilla"] is None and cards[card]["issues"] is None:
                stats["no_bzs"] += 1

    for case, data in cases.items():
        if data["status"] == "Closed":
            if (today - (format_date(data["closeddate"]).date())).days < 7:
                stats["weekly_closed_cases"] += 1
            if (today - format_date(data["closeddate"]).date()).days <= 1:
                stats["daily_closed_cases"] += 1
        else:
            stats["open_cases"] += 1
            if (today - format_date(data["createdate"]).date()).days < 7:
                stats["weekly_opened_cases"] += 1
            if (today - format_date(data["createdate"]).date()).days <= 1:
                stats["daily_opened_cases"] += 1
            if (today - format_date(data["last_update"]).date()).days < 7:
                stats["no_updates"] += 1

    all_bugs = {}
    no_target = {}
    if bugs:
        for case, bzs in bugs.items():
            if case in cases and cases[case]["status"] != "Closed":
                for bug in bzs:
                    all_bugs[bug["bugzillaNumber"]] = bug
                    if is_bug_missing_target(bug):
                        no_target[bug["bugzillaNumber"]] = bug

    if issues:
        for case, jira_bugs in issues.items():
            if case in cases and cases[case]["status"] != "Closed":
                for issue in jira_bugs:
                    all_bugs[issue["id"]] = issue
                    if is_bug_missing_target(issue):
                        no_target[issue["id"]] = issue

    stats["bugs"]["unique"] = len(all_bugs)
    stats["bugs"]["no_target"] = len(no_target)

    end = time.time()
    logging.warning("generated stats in {} seconds".format((end - start)))

    return stats


def is_bug_missing_target(item):
    """Determine whether the BZ or Jira Bug is missing a target

    Args:
        item (Dict): Dictionary containing information about BZ/Jira Bug

    Returns:
        bool: Whether or not the item is missing a target
    """
    if "target_release" in item:
        return item["target_release"][0] == "---"
    else:
        # Return true if fix_versions is None/Not Found or if it's "---"
        return item.get("fix_versions") is None or (
            item.get("fix_versions") and item["fix_versions"][0] == "---"
        )


def plot_stats():
    """Prepare historical statistics data for plotting

    Retrieves cached historical statistics and transforms them into x and y
    value lists suitable for time-series plotting.

    Returns:
        tuple: A 2-tuple containing:
            - x_values: List of date strings
            - y_values: Dictionary of metric name to value lists, including:
                escalated, open_cases, new_cases, closed_cases, no_updates,
                no_bzs, bugs_unique, bugs_no_tgt, high_prio, crit_sit, and
                total_escalations
    """
    historical_stats = redis_get("stats")
    x_values = [day for day in historical_stats]
    y_values = {
        "escalated": [],
        "open_cases": [],
        "new_cases": [],
        "closed_cases": [],
        "no_updates": [],
        "no_bzs": [],
        "bugs_unique": [],
        "bugs_no_tgt": [],
        "high_prio": [],
        "crit_sit": [],
        "total_escalations": [],
    }
    for day, stat in historical_stats.items():
        y_values["escalated"].append(exists_or_zero(stat, "escalated"))
        y_values["open_cases"].append(exists_or_zero(stat, "open_cases"))
        y_values["new_cases"].append(exists_or_zero(stat, "daily_opened_cases"))
        y_values["closed_cases"].append(exists_or_zero(stat, "daily_closed_cases"))
        y_values["no_updates"].append(exists_or_zero(stat, "no_updates"))
        y_values["no_bzs"].append(exists_or_zero(stat, "no_bzs"))
        y_values["bugs_unique"].append(exists_or_zero(stat["bugs"], "unique"))
        y_values["bugs_no_tgt"].append(exists_or_zero(stat["bugs"], "no_target"))
        y_values["high_prio"].append(exists_or_zero(stat, "high_prio"))
        y_values["crit_sit"].append(exists_or_zero(stat, "crit_sit"))
        y_values["total_escalations"].append(exists_or_zero(stat, "total_escalations"))

    return x_values, y_values


def generate_histogram_stats(account=None, engineer=None):
    """
    Calculates histogram statistics for resolved and relief times of cards.

    Args:
        account (str, optional): Filter cards by account. Defaults to None.

    Returns:
        dict: A dictionary containing histogram statistics for resolved / relief times.
              The structure of the dictionary is as follows:
              {
                  "Resolved": {
                      "<severity1>": {
                          "data": [<time1>, <time2>, ...],
                          "mean": <mean of data>,
                          "median": <median of data>
                      },
                      "<severity2>": {
                          "data": [<time1>, <time2>, ...],
                          "mean": <mean of data>,
                          "median": <median of data>
                      },
                      ...
                  },
                  "Relief": {
                      "<severity1>": {
                          "data": [<time1>, <time2>, ...],
                          "mean": <mean of data>,
                          "median": <median of data>
                      },
                      "<severity2>": {
                          "data": [<time1>, <time2>, ...],
                          "mean": <mean of data>,
                          "median": <median of data>
                      },
                      ...
                  }
              }
              The times are represented as the number of days until resolution / relief.
    """
    seconds_per_day = 60 * 60 * 24
    base_dictionary = {
        "Urgent": {"data": [], "mean": None, "median": None},
        "High": {"data": [], "mean": None, "median": None},
        "Normal": {"data": [], "mean": None, "median": None},
        "Low": {"data": [], "mean": None, "median": None},
    }
    cards = redis_get("cards")
    if account is not None:
        logging.warning(f"filtering cards for {account}")
        cards = {c: d for (c, d) in cards.items() if d["account"] == account}

    if engineer is not None:
        logging.warning(f"filtering cards for {engineer}")
        cards = {
            c: d for (c, d) in cards.items() if d["assignee"]["displayName"] == engineer
        }

    histogram_data = {
        "Resolved": base_dictionary,
        "Relief": base_dictionary,
    }

    # Iterate over each entry in the input dictionary
    for card, details in cards.items():
        severity = details.get("severity")
        resolved_at = details.get("resolved_at")
        relief_at = details.get("relief_at")
        case_created = details.get("case_created")

        # Add time to resolution to the "Resolved" dictionary, indexed by severity
        if resolved_at is not None:
            if isinstance(resolved_at, int):
                # Timestamp is provided w/ empty milliseconds, so divide by 1000
                resolved_at = datetime.datetime.fromtimestamp(resolved_at / 1000)
            else:
                resolved_at = format_date(resolved_at)
            days_until_resolved = (
                resolved_at - format_date(case_created)
            ).total_seconds() / seconds_per_day
            histogram_data["Resolved"][severity]["data"].append(days_until_resolved)

        # Add time to relief to the "Relief" dictionary, indexed by severity
        if relief_at is not None:
            if isinstance(relief_at, int):
                # Timestamp is provided w/ empty milliseconds, so divide by 1000
                relief_at = datetime.datetime.fromtimestamp(relief_at / 1000)
            else:
                relief_at = format_date(relief_at)
            days_until_relief = (
                relief_at - format_date(case_created)
            ).total_seconds() / seconds_per_day
            histogram_data["Relief"][severity]["data"].append(days_until_relief)

    # Calculate mean and median for each severity level
    for status in ["Resolved", "Relief"]:
        for severity in histogram_data[status]:
            data = histogram_data[status][severity]["data"]
            if data:
                histogram_data[status][severity]["mean"] = statistics.mean(data)
                histogram_data[status][severity]["median"] = statistics.median(data)

    return histogram_data


def sync_priority(cfg):
    """Synchronize JIRA card priorities with case severities

    Finds cards where the JIRA priority doesn't match the case severity and
    updates them to be in sync. Only processes non-Done cards.

    Args:
        cfg: Configuration dictionary containing JIRA connection parameters

    Returns:
        dict: Dictionary of out-of-sync cards that were updated, keyed by
            card key
    """
    cards = redis_get("cards")
    sev_map = {
        re.search(r"[a-zA-Z]+", k).group(): v for k, v in portal2jira_sevs.items()
    }
    out_of_sync = {
        card: data
        for (card, data) in cards.items()
        if data["card_status"] != "Done"
        and data["priority"] != sev_map[data["severity"]]
    }
    for card, data in out_of_sync.items():
        new_priority = sev_map[data["severity"]]
        logging.warning(
            "{} has priority of {}, but case is {}".format(
                card, data["priority"], data["severity"]
            )
        )
        logging.warning("updating {} to a priority of {}".format(card, new_priority))
        jira_conn = jira_connection(cfg)
        oos_issue = jira_conn.issue(card)
        oos_issue.update(fields={"priority": {"name": new_priority}})
    return out_of_sync


def get_issues_in_sprint(cfg, sprint, jira_conn, max_results=1000):
    """Get all issues in a specified sprint with specified labels

    Args:
        cfg (dict): Pre-configured settings
        sprint (jira.resources.Sprint): JIRA sprint
        jira_conn (jira.client.JIRA): JIRA connection object. Contains auth info
        max_results (int, optional): Max # of issues to pull from sprint.
            Defaults to 1000.

    Returns:
       dict: All cards in sprint with associated info
    """
    jira_query = (
        "sprint=" + str(sprint.id) + ' AND labels = "' + cfg["jira_query"] + '"'
    )
    cards = jira_conn.search_issues(
        jql_str=jira_query, json_result=True, maxResults=max_results
    )
    return cards["issues"]


def sync_portal_to_jira():
    """Synchronize Red Hat Portal cases to JIRA by creating missing cards

    Identifies cases from the Red Hat Portal that don't have corresponding
    JIRA cards and creates them. Sends email and Slack notifications for
    newly created cards. Includes safety check to prevent mass card creation.

    Returns:
        dict: Dictionary containing 'cards_created' count
    """
    cfg = set_cfg()

    start = time.time()
    cases = redis_get("cases")
    cards = redis_get("cards")

    open_cases = [case for case in cases if cases[case]["status"] != "Closed"]
    card_cases = [cards[card]["case_number"] for card in cards]
    logging.warning("found {} cases in JIRA".format(len(card_cases)))
    new_cases = [case for case in open_cases if case not in card_cases]
    logging.warning("new cases: {}".format(new_cases))

    response = {"cards_created": 0}

    if len(new_cases) > int(cfg["max_to_create"]):
        max_warning_message = (
            f"Warning: more than {cfg['max_to_create']} cases ({len(new_cases)}) "
            f"will be created, so refusing to proceed. Please check log output\n"
        )
        logging.warning(max_warning_message)
        notification_content = {
            "High New Case Count Detected": {
                "full_message": (f"{max_warning_message}\nNew cases: {new_cases}\n")
            }
        }
        cfg["to"] = cfg["alert_email"]
        cfg["subject"] = "High New Case Count Detected"
        email_notify(cfg, notification_content)
    elif len(new_cases) > 0:
        logging.warning("need to create {} cases".format(len(new_cases)))
        notification_content, new_cards, novel_cases = create_cards(
            cfg, new_cases, action="create"
        )
        if notification_content:
            logging.warning("notifying team about new JIRA cards")
            if len(new_cards) != len(notification_content):
                logging.warning("# of notifications does not match number of new cards")
            cfg["subject"] += ": {}".format(", ".join(novel_cases))
            email_notify(cfg, notification_content)
            if cfg["slack_token"] and (
                cfg["high_severity_slack_channel"] or cfg["low_severity_slack_channel"]
            ):
                slack_notify(cfg, notification_content)
            else:
                logging.warning("no slack token or channel specified")
            cards.update(new_cards)
            redis_set("cards", json.dumps(cards))
        response = {"cards_created": len(new_cases)}
    else:
        logging.warning("no new cards required")

    end = time.time()
    logging.warning("synced to jira in {} seconds".format(end - start))
    return response


def main():
    """Main entry point for the libtelco5g module

    Currently a placeholder that prints the module name.
    """
    print("libtelco5g")


if __name__ == "__main__":
    main()

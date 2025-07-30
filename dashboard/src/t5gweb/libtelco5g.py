#! /usr/bin/python -W ignore

"""
This script takes a configuration file name as its only argument.
Not passing a configuration file as an option will cause the script
to use its default settings and any environmental settings.

Setting set in the environment override the ones in the configuration file.
"""

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
from t5gweb.utils import (email_notify, exists_or_zero, format_date,
                          get_random_member, get_token, make_headers, set_cfg,
                          slack_notify)

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
    """initiate a connection to the JIRA server"""

    logging.warning("attempting to connect to jira...")
    jira = JIRA(server=cfg["server"], token_auth=cfg["password"])

    return jira


def get_project_id(conn, name):
    """Take a project name and return its id
    conn    - Jira connection object
    name    - project name

    Returns Jira object.
    Notable fields:
        .components  - list of Jira objects
            [<JIRA Component: name='ABC', id='12333847'>,...]
        .description - string
        .id          - numerical string
        .key         - string
            KNIECO
        .name        - string
            KNI Ecosystem
    """

    project = conn.project(name)
    logging.warning("project: %s", project)
    return project


def get_board_id(conn, name):
    """Take a board name as input and return its id
    conn    - Jira connection object
    name    - board name

    Returns Jira object.
    Notable fields:
        .id          - numerical string
        .name        - string
            KNI ECO Labs & Field
    """

    boards = conn.boards(name=name)
    logging.warning("board: %s", boards[0])
    return boards[0]


def get_previous_card(conn, cfg, case):
    """Take a case number and return first card that has the case number in the summary
    conn    - Jira connection object
    Return previous owner jira username
    """
    previous_issues_query = f"project = {cfg['project']} AND summary ~ '{case}'"
    previous_issues = conn.search_issues(previous_issues_query)
    if len(previous_issues) > 0:
        return previous_issues[0]
    return None


def get_latest_sprint(conn, bid, sprintname):
    """Take a board id and return the current sprint
    conn    - Jira connection object
    name    - board id

    Returns Jira object.
    Notable fields:
        .id          - numerical string
        .name        - string
            ECO Labs & Field Sprint 188
    """

    sprints = conn.sprints(bid, state="active")
    return sprints[0]


def get_last_sprint(conn, bid, sprintname):
    this_sprint = get_latest_sprint(conn, bid, sprintname)
    sprint_number = re.search(r"\d*$", this_sprint.name)[0]
    last_sprint_number = int(sprint_number) - 1
    board = conn.sprints(bid)  # still seems to return everything?
    last_sprint_name = sprintname + ".*" + str(last_sprint_number)

    for b in board:
        if re.search(last_sprint_name, b.name):
            return b


def get_sprint_summary(conn, bid, sprintname, team):
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
    """Accepts RH Support Case URL and returns the case number
    - https://access.redhat.com/support/cases/0123456
    - https://access.redhat.com/support/cases/#/case/0123456
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
    """
    Add a new watcher to a Red Hat support case.

    :param cfg: The configuration dictionary.
    :param case: The case number.
    :param username: The SSO username of the user to add as a watcher.
    :param token: The Red Hat API token.

    :return: True if the user was successfully added as a watcher, False otherwise.
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
    """
    cfg    - configuration
    cases  - dictionary of all cases
    needed - list of cases that need a card created
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
    """Setup all connections and get required data for card creation"""
    """Generated by: Cursor"""
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
    """Filter out cases that already have cards"""
    """Generated by: Cursor"""
    novel_cases = []
    for case in new_cases:
        if case in created_cases:
            logging.warning(f"Card already exists for {case}, moving on.")
        else:
            novel_cases.append(case)
    return novel_cases


def _process_single_case(case, cases, context, cfg):
    """Process a single case and create its JIRA card"""
    """Generated by: Cursor"""
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
    new_card = _create_jira_card(card_info, context["jira_conn"])

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
    """Check if case is older than 15 days"""
    """Generated by: Cursor"""
    case_creation_date = datetime.datetime.strptime(
        case_data["createdate"], "%Y-%m-%dT%H:%M:%SZ"
    )
    date_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return case_creation_date < date_now - datetime.timedelta(days=15)


def _handle_old_case(case, context, cfg):
    """Handle old cases by checking for and reopening previous cards"""
    """Generated by: Cursor"""
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
    """Determine who should be assigned to the case"""
    """Generated by: Cursor"""
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
    """Build the card info dictionary for JIRA card creation"""
    """Generated by: Cursor"""
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
    """Create the JIRA card"""
    """Generated by: Cursor"""
    logging.warning(f"Creating card for case {card_info['summary'].split(':')[0]}")
    new_card = jira_conn.create_issue(fields=card_info)
    new_card.update(fields={"customfield_12317313": "TRACK"})
    logging.warning(f"Created {new_card.key}")
    return new_card


def _post_process_card(new_card, case, cases, context, cfg):
    """Handle post-creation card processing: sprint, status, links"""
    """Generated by: Cursor"""
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
    """Add support case and bugzilla links to the card"""
    """Generated by: Cursor"""
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
    """Build the card data dictionary for return"""
    """Generated by: Cursor"""
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
    logging.warning("syncing {}..".format(key))
    r_cache = redis.Redis(host="redis")
    r_cache.mset({key: value})
    logging.warning("{}....synced".format(key))


def redis_get(key):
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
    links = jira_conn.remote_links(card)
    for link in links:
        t = jira_conn.remote_link(card, link)
        if t.raw["object"]["title"] == "Support Case":
            case_number = get_case_number(t.raw["object"]["url"])
            if len(case_number) > 0:
                return case_number
    return None


def generate_stats(account=None, engineer=None):
    """generate some stats"""

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
    engineers = [cards[card]["assignee"]["displayName"] for card in cards]
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
    print("libtelco5g")


if __name__ == "__main__":
    main()

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
from t5gweb.utils import exists_or_zero, get_random_member, get_token

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
    return boards[0]


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

    # Add the new watcher to the list of notified users
    payload = {"user": [{"ssoUsername": username}]}

    # Send the POST request to add the watcher
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
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

    email_content = []
    new_cards = {}

    logging.warning("attempting to connect to jira...")
    jira_conn = jira_connection(cfg)
    board = get_board_id(jira_conn, cfg["board"])

    # Obtain the authentication token for RedHat Api
    token = get_token(cfg["offline_token"])

    if cfg["sprintname"] and cfg["sprintname"] != "":
        sprint = get_latest_sprint(jira_conn, board.id, cfg["sprintname"])

    cases = redis_get("cases")

    for case in new_cases:
        assignee = None

        if cfg["team"]:
            for member in cfg["team"]:
                for account in member["accounts"]:
                    if account.lower() in cases[case]["account"].lower():
                        assignee = member
            if assignee is None:
                last_choice = redis_get("last_choice")
                assignee = get_random_member(cfg["team"], last_choice)
                redis_set("last_choice", json.dumps(assignee))
            assignee["displayName"] = assignee["name"]

            # Check if the user wants to be notified
            notifieduser = assignee.get("notifieduser", "true")
            # Add the user as a watcher only if they want to be notified
            if notifieduser == "true" and case:
                logging.warning(
                    f"Adding watcher {assignee['jira_user']} to case {case}"
                )
                add_watcher_to_case(cfg, case, assignee["jira_user"], token)
            else:
                logging.warning(
                    f"Not adding watcher {assignee['jira_user']} to case {case}"
                )

        priority = portal2jira_sevs[cases[case]["severity"]]
        full_description = (
            "This card was automatically created from the Case Dashboard Sync Job.\r\n"
            + "\r\n"
            + "This card was created because it had a severity of "
            + cases[case]["severity"]
            + "\r\nThe account for the case is "
            + cases[case]["account"]
            + "\r\nThe case had an internal status of: "
            + cases[case]["status"]
            + "\r\n\r\n*Description:* \r\n\r\n"
            + cases[case]["description"]
            + "\r\n"
        )
        card_info = {
            "project": {"key": cfg["project"]},
            "issuetype": {"name": cfg["type"]},
            "components": [{"name": cfg["component"]}],
            "priority": {"name": priority},
            "labels": cfg["labels"],
            "summary": case + ": " + cases[case]["problem"],
            "description": full_description[:253] + ".."
            if len(full_description) > 253
            else full_description,
        }

        if assignee:
            card_info["assignee"] = {"name": assignee["jira_user"]}

        logging.warning("A card needs created for case {}".format(case))
        logging.warning(card_info)

        if action == "create":
            logging.warning("creating card for case {}".format(case))
            new_card = jira_conn.create_issue(fields=card_info)
            logging.warning("created {}".format(new_card.key))

            email_content.append(
                (
                    f"A JIRA issue ({cfg['server']}/browse/{new_card}) has been created"
                    f" for a new case:\n"
                    f"Case #: {case} (https://access.redhat.com/support/cases/{case})\n"
                    f"Account: {cases[case]['account']}\n"
                    f"Summary: {cases[case]['problem']}\n"
                    f"Severity: {cases[case]['severity']}\n"
                    f"Description: {cases[case]['description']}\n"
                )
            )
            if assignee:
                email_content.append(
                    f"It is initially being tracked by {assignee['name']}.\n"
                )
            email_content.append("\n===========================================\n\n")

            # Add newly create card to the sprint
            if cfg["sprintname"] and cfg["sprintname"] != "":
                logging.warning("moving card to sprint {}".format(sprint.id))
                jira_conn.add_issues_to_sprint(sprint.id, [new_card.key])

            # Move the card from backlog to the To Do column
            if (
                new_card.fields.status.name != "New"
                and new_card.fields.status.name != "To Do"
            ):
                logging.warning(new_card.fields.status)
                logging.warning('moving card from backlog to "To Do" column')
                jira_conn.transition_issue(new_card.key, "To Do")

            # Add links to case, etc
            logging.warning("adding link to support case {}".format(case))
            jira_conn.add_simple_link(
                new_card.key,
                {
                    "url": "https://access.redhat.com/support/cases/" + case,
                    "title": "Support Case",
                },
            )

            bz = []
            if "bug" in cases[case]:
                bz = cases[case]["bug"]
                logging.warning("adding link to BZ {}".format(cases[case]["bug"]))
                jira_conn.add_simple_link(
                    new_card.key,
                    {
                        "url": "https://bugzilla.redhat.com/show_bug.cgi?id="
                        + cases[case]["bug"],
                        "title": "BZ " + cases[case]["bug"],
                    },
                )

            tags = []
            if "tags" in cases[case]:
                cases[case]["tags"]

            new_cards[new_card.key] = {
                "card_status": status_map[new_card.fields.status.name],
                "card_created": new_card.fields.created,
                "account": cases[case]["account"],
                "summary": case + ": " + cases[case]["problem"],
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
                "watched": False,
                "crit_sit": False,
            }

    return email_content, new_cards


def redis_set(key, value):
    logging.warning("syncing {}..".format(key))
    r_cache = redis.Redis(host="redis")
    r_cache.mset({key: value})
    logging.warning("{}....synced".format(key))


def redis_get(key):
    logging.warning("fetching {}..".format(key))
    r_cache = redis.Redis(host="redis")
    data = r_cache.get(key)
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


def generate_stats(account=None):
    """generate some stats"""

    logging.warning("generating stats")
    start = time.time()

    cards = redis_get("cards")
    cases = redis_get("cases")
    bugs = redis_get("bugs")

    if account is not None:
        logging.warning("filtering cases for {}".format(account))
        cards = {c: d for (c, d) in cards.items() if d["account"] == account}
        cases = {c: d for (c, d) in cases.items() if d["account"] == account}

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
        "watched": 0,
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
            if cards[card]["watched"]:
                stats["watched"] += 1
            if cards[card]["crit_sit"]:
                stats["crit_sit"] += 1
            if (
                cards[card]["escalated"]
                or cards[card]["watched"]
                or cards[card]["crit_sit"]
            ):
                stats["total_escalations"] += 1
            if cards[card]["bugzilla"] is None:
                stats["no_bzs"] += 1

    for case, data in cases.items():
        if data["status"] == "Closed":
            if (
                today
                - datetime.datetime.strptime(
                    data["closeddate"], "%Y-%m-%dT%H:%M:%SZ"
                ).date()
            ).days < 7:
                stats["weekly_closed_cases"] += 1
            if (
                today
                - datetime.datetime.strptime(
                    data["closeddate"], "%Y-%m-%dT%H:%M:%SZ"
                ).date()
            ).days <= 1:
                stats["daily_closed_cases"] += 1
        else:
            stats["open_cases"] += 1
            if (
                today
                - datetime.datetime.strptime(
                    data["createdate"], "%Y-%m-%dT%H:%M:%SZ"
                ).date()
            ).days < 7:
                stats["weekly_opened_cases"] += 1
            if (
                today
                - datetime.datetime.strptime(
                    data["createdate"], "%Y-%m-%dT%H:%M:%SZ"
                ).date()
            ).days <= 1:
                stats["daily_opened_cases"] += 1
            if (
                today
                - datetime.datetime.strptime(
                    data["last_update"], "%Y-%m-%dT%H:%M:%SZ"
                ).date()
            ).days < 7:
                stats["no_updates"] += 1

    all_bugs = {}
    if bugs:
        for case, bzs in bugs.items():
            if case in cases and cases[case]["status"] != "Closed":
                for bug in bzs:
                    all_bugs[bug["bugzillaNumber"]] = bug
    no_target = {b: d for (b, d) in all_bugs.items() if d["target_release"][0] == "---"}
    stats["bugs"]["unique"] = len(all_bugs)
    stats["bugs"]["no_target"] = len(no_target)

    end = time.time()
    logging.warning("generated stats in {} seconds".format((end - start)))

    return stats


def plot_stats():
    historical_stats = redis_get("stats")
    x_values = [day for day in historical_stats]
    y_values = {
        "escalated": [],
        "watched": [],
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
        y_values["watched"].append(exists_or_zero(stat, "watched"))
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


def generate_histogram_stats(account=None):
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
            days_until_resolved = (
                datetime.datetime.strptime(resolved_at, "%Y-%m-%dT%H:%M:%SZ")
                - datetime.datetime.strptime(case_created, "%Y-%m-%dT%H:%M:%SZ")
            ).total_seconds() / seconds_per_day
            histogram_data["Resolved"][severity]["data"].append(days_until_resolved)

        # Add time to relief to the "Relief" dictionary, indexed by severity
        if relief_at is not None:
            days_until_relief = (
                datetime.datetime.strptime(relief_at, "%Y-%m-%dT%H:%M:%SZ")
                - datetime.datetime.strptime(case_created, "%Y-%m-%dT%H:%M:%SZ")
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


def main():
    print("libtelco5g")


if __name__ == "__main__":
    main()

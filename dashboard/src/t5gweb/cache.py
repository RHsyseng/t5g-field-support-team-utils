"""cache.py: caching functions for the t5gweb"""
import datetime
import json
import logging
import re
import time
import xmlrpc

import bugzilla
import requests
import t5gweb.libtelco5g as libtelco5g
from jira.exceptions import JIRAError


def get_cases(cfg):
    # https://source.redhat.com/groups/public/hydra/hydra_integration_platform_cee_integration_wiki/hydras_api_layer

    token = libtelco5g.get_token(cfg["offline_token"])
    query = cfg["query"]
    fields = ",".join(cfg["fields"])
    query = "({})".format(query)
    num_cases = cfg["max_portal_results"]
    payload = {"q": query, "partnerSearch": "false", "rows": num_cases, "fl": fields}
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    url = f"{cfg['redhat_api']}/search/cases"

    logging.warning("searching the portal for cases")
    start = time.time()
    r = requests.get(url, headers=headers, params=payload)
    cases_json = r.json()["response"]["docs"]
    end = time.time()
    logging.warning(
        "found {} cases in {} seconds".format(len(cases_json), (end - start))
    )
    cases = {}
    for case in cases_json:
        cases[case["case_number"]] = {
            "owner": case["case_owner"],
            "severity": case["case_severity"],
            "account": case["case_account_name"],
            "problem": case["case_summary"],
            "status": case["case_status"],
            "createdate": case["case_createdDate"],
            "last_update": case["case_lastModifiedDate"],
            "description": case["case_description"],
            "product": case["case_product"][0] + " " + case["case_version"],
        }
        # Sometimes there is no BZ attached to the case
        if "case_bugzillaNumber" in case:
            cases[case["case_number"]]["bug"] = case["case_bugzillaNumber"]
        # Sometimes there is no tag attached to the case
        if "case_tags" in case:
            case_tags = case["case_tags"]
            if len(case_tags) == 1:
                tags = case_tags[0].split(";")  # csv instead of a proper list
            else:
                tags = case_tags
            cases[case["case_number"]]["tags"] = tags
        if "case_closedDate" in case:
            cases[case["case_number"]]["closeddate"] = case["case_closedDate"]

    libtelco5g.redis_set("cases", json.dumps(cases))


def get_escalations(cfg):
    """Get cases that have been escalated by querying the escalations JIRA board"""
    cases = libtelco5g.redis_get("cases")
    if (
        cases is None
        or cfg["jira_escalations_project"] is None
        or cfg["jira_escalations_label"] is None
    ):
        libtelco5g.redis_set("escalations", json.dumps(None))
        return

    logging.warning("getting escalated cases from JIRA")
    jira_conn = libtelco5g.jira_connection(cfg)
    max_cards = cfg["max_jira_results"]
    project = libtelco5g.get_project_id(jira_conn, cfg["jira_escalations_project"])
    jira_query = 'project = {} AND labels = "{}" AND status != "Closed"'.format(
        project.id, cfg["jira_escalations_label"]
    )

    escalated_cards = jira_conn.search_issues(jira_query, 0, max_cards).iterable
    escalations = []
    for card in escalated_cards:
        issue = jira_conn.issue(card)
        case = issue.fields.customfield_12313441
        if case is not None:
            escalations.append(case)
    libtelco5g.redis_set("escalations", json.dumps(escalations))


def get_cards(cfg, self=None, background=False):
    cases = libtelco5g.redis_get("cases")
    bugs = libtelco5g.redis_get("bugs")
    issues = libtelco5g.redis_get("issues")
    escalations = libtelco5g.redis_get("escalations")
    watchlist = libtelco5g.redis_get("watchlist")
    details = libtelco5g.redis_get("details")
    logging.warning("attempting to connect to jira...")
    jira_conn = libtelco5g.jira_connection(cfg)
    max_cards = cfg["max_jira_results"]
    start = time.time()
    project = libtelco5g.get_project_id(jira_conn, cfg["project"])
    logging.warning("project: {}".format(project))
    board = libtelco5g.get_board_id(jira_conn, cfg["board"])
    logging.warning("board: {}".format(board))
    if cfg["sprintname"] and cfg["sprintname"] != "":
        sprint = libtelco5g.get_latest_sprint(jira_conn, board.id, cfg["sprintname"])
        jira_query = (
            "sprint=" + str(sprint.id) + ' AND labels = "' + cfg["jira_query"] + '"'
        )
        logging.warning("sprint: {}".format(sprint))
    else:
        jira_query = (
            "project=" + str(project.id) + ' AND labels = "' + cfg["jira_query"] + '"'
        )

    logging.warning("pulling cards from jira")
    card_list = jira_conn.search_issues(jira_query, 0, max_cards).iterable
    time_now = datetime.datetime.now(datetime.timezone.utc)

    jira_cards = {}
    for index, card in enumerate(card_list):
        if background:
            # Update task information for progress bar
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": index,
                    "total": len(card_list),
                    "status": "Refreshing Cards in Background...",
                },
            )
        issue = jira_conn.issue(card)
        comments = jira_conn.comments(issue)
        card_comments = []
        for comment in comments:
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
            tstamp = comment.updated
            card_comments.append((body, tstamp))
        case_number = libtelco5g.get_case_from_link(jira_conn, card)
        if not case_number or case_number not in cases.keys():
            logging.warning(
                "card isn't associated with a case. discarding ({})".format(card)
            )
            continue
        assignee = {"displayName": None, "key": None, "name": None}
        if issue.fields.assignee:
            assignee = {
                "displayName": issue.fields.assignee.displayName,
                "key": issue.fields.assignee.key,
                "name": issue.fields.assignee.name,
            }

        # Get contributors

        contributor = []
        if issue.fields.customfield_12315950:
            for engineer in issue.fields.customfield_12315950:
                contributor.append(
                    {
                        "displayName": engineer.displayName,
                        "key": engineer.key,
                        "name": engineer.name,
                    }
                )
        tags = []
        if "tags" in cases[case_number].keys():
            tags = cases[case_number]["tags"]

        if "bug" in cases[case_number].keys() and case_number in bugs.keys():
            bugzilla = bugs[case_number]
        else:
            bugzilla = None

        if case_number in issues:
            case_issues = issues[case_number]
        else:
            case_issues = None

        if escalations and case_number in escalations:
            escalated = True
        else:
            escalated = False
        if case_issues:
            for case_issue in case_issues:
                if cfg["jira_escalations_project"] in case_issue["id"]:
                    escalated_link = case_issue["url"]
                    break
                else:
                    escalated_link = None
        else:
            escalated_link = None
        if "PotentialEscalation" in issue.fields.labels and escalated is False:
            potential_escalation = True
        else:
            potential_escalation = False

        if watchlist and case_number in watchlist:
            watched = True
        else:
            watched = False
        if case_number in details.keys():
            crit_sit = details[case_number]["crit_sit"]
            group_name = details[case_number]["group_name"]
            notified_users = details[case_number]["notified_users"]
            relief_at = details[case_number]["relief_at"]
            resolved_at = details[case_number]["resolved_at"]

        else:
            crit_sit = False
            group_name = None
            notified_users = []
            relief_at = None
            resolved_at = None

        jira_cards[card.key] = {
            "card_status": libtelco5g.status_map[issue.fields.status.name],
            "card_created": issue.fields.created,
            "account": cases[case_number]["account"],
            "summary": cases[case_number]["problem"],
            "description": cases[case_number]["description"],
            "comments": card_comments,
            "assignee": assignee,
            "contributor": contributor,
            "case_number": case_number,
            "tags": tags,
            "labels": issue.fields.labels,
            "bugzilla": bugzilla,
            "issues": case_issues,
            "severity": re.search(r"[a-zA-Z]+", cases[case_number]["severity"]).group(),
            "priority": issue.fields.priority.name,
            "escalated": escalated,
            "escalated_link": escalated_link,
            "potential_escalation": potential_escalation,
            "watched": watched,
            "product": cases[case_number]["product"],
            "case_status": cases[case_number]["status"],
            "crit_sit": crit_sit,
            "group_name": group_name,
            "case_updated_date": datetime.datetime.strftime(
                datetime.datetime.strptime(
                    cases[case_number]["last_update"], "%Y-%m-%dT%H:%M:%SZ"
                ),
                "%Y-%m-%d %H:%M",
            ),
            "case_days_open": (
                time_now.replace(tzinfo=None)
                - datetime.datetime.strptime(
                    cases[case_number]["createdate"], "%Y-%m-%dT%H:%M:%SZ"
                )
            ).days,
            "case_created": cases[case_number]["createdate"],
            "notified_users": notified_users,
            "relief_at": relief_at,
            "resolved_at": resolved_at,
        }

    end = time.time()
    logging.warning("got {} cards in {} seconds".format(len(jira_cards), (end - start)))
    libtelco5g.redis_set("cards", json.dumps(jira_cards))
    libtelco5g.redis_set("timestamp", json.dumps(str(datetime.datetime.utcnow())))


def get_watchlist(cfg):
    cases = libtelco5g.redis_get("cases")
    if cases is None or cfg["watchlist_url"] is None or cfg["watchlist_url"] == "":
        libtelco5g.redis_set("watchlist", json.dumps(None))
        return

    token = libtelco5g.get_token(cfg["offline_token"])
    num_cases = cfg["max_portal_results"]
    payload = {"rows": num_cases}
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    url = f"{cfg['redhat_api']}/eh/escalations?highlight=true"

    r = requests.get(url, headers=headers, params=payload)

    watchlist = []
    for watched in r.json():
        watched_cases = watched["cases"]
        for case in watched_cases:
            caseNumber = case["caseNumber"]
            if caseNumber in cases:
                watchlist.append(caseNumber)

    libtelco5g.redis_set("watchlist", json.dumps(watchlist))


def get_case_details(cfg):
    """Caches CritSit and CaseGroup from open cases"""
    cases = libtelco5g.redis_get("cases")
    if cases is None:
        libtelco5g.redis_set("details", json.dumps(None))
        libtelco5g.redis_set("case_bz", json.dumps(None))
        return

    bz_dict = {}
    token = libtelco5g.get_token(cfg["offline_token"])
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    case_details = {}
    logging.warning("getting all bugzillas and case details")
    for case in cases:
        if cases[case]["status"] != "Closed":
            case_endpoint = f"{cfg['redhat_api']}/v1/cases/{case}"
            r_case = requests.get(case_endpoint, headers=headers)
            if r_case.status_code == 401:
                token = libtelco5g.get_token(cfg["offline_token"])
                headers = {
                    "Accept": "application/json",
                    "Authorization": "Bearer " + token,
                }
                r_case = requests.get(case_endpoint, headers=headers)

            crit_sit = r_case.json().get("critSit", False)
            group_name = r_case.json().get("groupName", None)
            notified_users = r_case.json().get("notifiedUsers", [])
            relief_at = r_case.json().get("reliefAt", None)
            resolved_at = r_case.json().get("resolvedAt", None)

            case_details[case] = {
                "crit_sit": crit_sit,
                "group_name": group_name,
                "notified_users": notified_users,
                "relief_at": relief_at,
                "resolved_at": resolved_at,
            }
            if "bug" in cases[case]:
                bz_dict[case] = r_case.json()["bugzillas"]

    libtelco5g.redis_set("details", json.dumps(case_details))
    libtelco5g.redis_set("case_bz", json.dumps(bz_dict))


def get_bz_details(cfg):
    """Get details about Bugzillas from API"""
    logging.warning("getting additional info via bugzilla API")
    bz_dict = libtelco5g.redis_get("case_bz")
    if bz_dict is None or cfg["bz_key"] is None or cfg["bz_key"] == "":
        libtelco5g.redis_set("bugs", json.dumps(None))
        return

    bz_url = "bugzilla.redhat.com"
    bz_api = bugzilla.Bugzilla(bz_url, api_key=cfg["bz_key"])
    for case in bz_dict:
        for bug in bz_dict[case]:
            try:
                bugs = bz_api.getbug(bug["bugzillaNumber"])
            except xmlrpc.client.Fault:
                logging.warning(
                    "error retrieving bug {} - restricted?".format(
                        bug["bugzillaNumber"]
                    )
                )
                bugs = None
            if bugs:
                bug["target_release"] = bugs.target_release
                bug["assignee"] = bugs.assigned_to
                bug["last_change_time"] = datetime.datetime.strftime(
                    datetime.datetime.strptime(
                        str(bugs.last_change_time), "%Y%m%dT%H:%M:%S"
                    ),
                    "%Y-%m-%d",
                )  # convert from xmlrpc.client.DateTime to str and reformat
                bug["internal_whiteboard"] = bugs.internal_whiteboard
                bug["qa_contact"] = bugs.qa_contact
                bug["severity"] = bugs.severity
            else:
                bug["target_release"] = ["unavailable"]
                bug["assignee"] = "unavailable"
                bug["last_change_time"] = "unavailable"
                bug["internal_whiteboard"] = "unavailable"
                bug["qa_contact"] = "unavailable"
                bug["severity"] = "unavailable"

    libtelco5g.redis_set("bugs", json.dumps(bz_dict))


def get_issue_details(cfg):
    logging.warning("caching issues")
    cases = libtelco5g.redis_get("cases")
    if cases is None:
        libtelco5g.redis_set("issues", json.dumps(None))
        return

    token = libtelco5g.get_token(cfg["offline_token"])
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}

    logging.warning("attempting to connect to jira...")
    jira_conn = libtelco5g.jira_connection(cfg)

    jira_issues = {}
    open_cases = [case for case in cases if cases[case]["status"] != "Closed"]
    for case in open_cases:
        issues_url = f"{cfg['redhat_api']}/cases/{case}/jiras"
        issues = requests.get(issues_url, headers=headers)
        if issues.status_code == 200 and len(issues.json()) > 0:
            case_issues = []
            for issue in issues.json():
                if "title" in issue.keys():
                    try:
                        bug = jira_conn.issue(issue["resourceKey"])
                    except JIRAError:
                        logging.warning("Can't access {}".format(issue["resourceKey"]))
                        continue

                    # Retrieve QA contact from Jira bug
                    try:
                        qa_contact = bug.fields.customfield_12315948.emailAddress
                    except AttributeError:
                        qa_contact = None
                    # Retrieve Severity from Jira bug
                    try:
                        jira_severity = bug.fields.customfield_12316142.value
                    except AttributeError:
                        jira_severity = None
                    try:
                        jira_type = bug.fields.issuetype.name
                    except AttributeError:
                        jira_type = None
                    # Retrieve assignee from Jira bug
                    if bug.fields.assignee is not None:
                        assignee = bug.fields.assignee.emailAddress
                    else:
                        assignee = None

                    # Retrieve target release from Jira bug
                    if len(bug.fields.fixVersions) > 0:
                        fix_versions = []
                        for version in bug.fields.fixVersions:
                            fix_versions.append(version.name)
                    else:
                        fix_versions = None

                    priority = None
                    if bug.fields.priority:
                        priority = bug.fields.priority.name

                    case_issues.append(
                        {
                            "id": issue["resourceKey"],
                            "url": issue["resourceURL"],
                            "title": issue["title"],
                            "status": issue["status"],
                            "updated": datetime.datetime.strftime(
                                datetime.datetime.strptime(
                                    str(issue["lastModifiedDate"]), "%Y-%m-%dT%H:%M:%SZ"
                                ),
                                "%Y-%m-%d",
                            ),
                            "qa_contact": qa_contact,
                            "assignee": assignee,
                            "fix_versions": fix_versions,
                            "priority": priority,
                            "jira_severity": jira_severity,
                            "jira_type": jira_type,
                        }
                    )
            if len(case_issues) > 0:
                jira_issues[case] = case_issues

    libtelco5g.redis_set("issues", json.dumps(jira_issues))
    logging.warning("issues cached")


def get_stats():
    logging.warning("caching {} stats")
    all_stats = libtelco5g.redis_get("stats")
    new_stats = libtelco5g.generate_stats()
    tstamp = datetime.datetime.utcnow()
    today = tstamp.strftime("%Y-%m-%d")
    stats = {today: new_stats}
    all_stats.update(stats)
    libtelco5g.redis_set("stats", json.dumps(all_stats))

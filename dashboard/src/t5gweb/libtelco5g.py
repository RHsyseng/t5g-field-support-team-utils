#! /usr/bin/python -W ignore

'''
This script takes a configuration file name as its only argument.
Not passing a configuration file as an option will cause the script
to use its default settings and any environmental settings.

Setting set in the environment override the ones in the configuration file.
'''

from __future__ import print_function
import os
import getpass
import datetime
from jira import JIRA
from jira.client import ResultList
from jira.resources import Issue
from jira.exceptions import JIRAError
import re
import pprint
import requests
from urllib.parse import urlparse
import smtplib
from email.message import EmailMessage
import random
from slack_sdk import WebClient
import redis
import json
import logging
import time
import bugzilla
import smartsheet

# for portal to jira mapping
portal2jira_sevs = {
    "1 (Urgent)"    : "Critical",
    "2 (High)"      : "Major",
    "3 (Normal)"    : "Normal",
    "4 (Low)"       : "Minor"
}

# card status mappings
status_map = {
    "To Do": "Backlog",
    "Open": "Debugging",
    "In Progress": "Eng Working",
    "Code Review": "Backport",
    "QE Review": "Ready To Close",
    "Blocked": "Blocked",
    "Won't Fix / Obsolete": "Done",
    "Done": "Done"
}

def jira_connection(cfg):

    jira = JIRA(
        server = cfg['server'],
        token_auth = cfg['password']
    )

    return jira

def get_project_id(conn, name):
    ''' Take a project name and return its id
    conn    - Jira connection object
    name    - project name

    Returns Jira object.
    Notable fields:
        .components  - list of Jira objects
            [<JIRA Component: name='CNV CI and Release', id='12333847'>,...]
        .description - string
        .id          - numerical string
        .key         - string
            KNIECO
        .name        - string
            KNI Ecosystem
    '''

    project = conn.project(name)
    return project

def get_component_id(conn, projid, name):
    ''' Take a component name and return its id
    conn    - Jira connection object
    projid  - component id
    name    - component name

    Returns Jira object.
    Notable fields:
        .description - string
        .id          - numerical string
        .name        - string
            KNI Labs & Field
        .project     - string
            KNIECO
        .projectId   - numerical string
    '''

    components=conn.project_components(projid)
    component = next(item for item in components if item.name == name)
    return component

def get_board_id(conn, name):
    ''' Take a board name as input and return its id
    conn    - Jira connection object
    name    - board name

    Returns Jira object.
    Notable fields:
        .id          - numerical string
        .name        - string
            KNI ECO Labs & Field
    '''

    boards = conn.boards(name=name)
    return boards[0]

def get_latest_sprint(conn, bid, sprintname):
    ''' Take a board id and return the current sprint
    conn    - Jira connection object
    name    - board id

    Returns Jira object.
    Notable fields:
        .id          - numerical string
        .name        - string
            ECO Labs & Field Sprint 188
    '''

    sprints = conn.sprints(bid, state="active")
    return sprints[0]

def get_last_sprint(conn, bid, sprintname):
    this_sprint = get_latest_sprint(conn, bid, sprintname)
    sprint_number = re.search('\d*$', this_sprint.name)[0]
    last_sprint_number = int(sprint_number) - 1
    board = conn.sprints(bid) # still seems to return everything?
    last_sprint_name = sprintname + ".*" + str(last_sprint_number)
    
    for b in board:
        if re.search(last_sprint_name, b.name):
            return b

def get_sprint_summary(conn, bid, sprintname, team):
    totals = {}
    last_sprint = get_last_sprint(conn, bid, sprintname)
    sid = last_sprint.id
    
    for member in team:
        user = member['jira_user']
        user = user.replace('@', '\\u0040')
        completed_cards = conn.search_issues('sprint=' + str(sid) + ' and assignee = ' + str(user) + ' and status = "DONE"', 0, 1000).iterable
        print("%s completed %d cards" % (member['name'], len(completed_cards)))
    # kobi
    user = 'kgershon@redhat.com'
    user = user.replace('@', '\\u0040')
    name = 'Kobi Gershon'
    completed_cards = conn.search_issues('sprint=' + str(sid) + ' and assignee = ' + str(user) + ' and status = "DONE"', 0, 1000).iterable
    print("%s completed %d cards" % (name, len(completed_cards)))

def get_card_summary():

    cards = redis_get('cards')
    backlog = [card for card in cards if cards[card]['card_status'] == 'Backlog']
    debugging = [card for card in cards if cards[card]['card_status'] == 'Debugging']
    eng_working = [card for card in cards if cards[card]['card_status'] == 'Eng Working']
    backport = [card for card in cards if cards[card]['card_status'] == 'Backport']
    ready_to_close = [card for card in cards if cards[card]['card_status'] == 'Ready To Close']
    done = [card for card in cards if cards[card]['card_status'] == 'Done']

    summary = {}
    summary['backlog'] = len(backlog)
    summary['debugging'] = len(debugging)
    summary['eng_working'] = len(eng_working)
    summary['backport'] = len(backport)
    summary['ready_to_close'] = len(ready_to_close)
    summary['done'] = len(done)
    return summary

def get_case_number(link, pfilter='cases'):
    ''' Accepts RH Support Case URL and returns the case number
        - https://access.redhat.com/support/cases/0123456
        - https://access.redhat.com/support/cases/#/case/0123456
    '''
    parsed_url = urlparse(link)

    if pfilter == 'cases':
        if 'cases' in parsed_url.path and parsed_url.netloc == 'access.redhat.com':
            if len(parsed_url.fragment) > 0 and 'case' in parsed_url.fragment:
                return parsed_url.fragment.split('/')[2]
            if len(parsed_url.path) > 0 and 'cases' in parsed_url.path:
                return parsed_url.path.split('/')[3]
    return ''

def get_random_member(team):
    '''Randomly pick team member and avoid picking the same person twice in a row'''

    last_choice = redis_get('last_choice')
    if len(team) > 1: 
        if last_choice is not None:
            team = [member for member in team if member != last_choice]
        current_choice = random.choice(team)
    elif len(team) == 1:
        current_choice = team[0]
    else:
        logging.warning("No team variable is available, cannot assign case.")
        current_choice = None
    redis_set('last_choice', json.dumps(current_choice))

    return current_choice


def create_cards(cfg, new_cases, action='none'):
    '''
    cfg    - configuration
    cases  - dictionary of all cases
    needed - list of cases that need a card created
    '''

    email_content = []
    new_cards = {}

    logging.warning("attempting to connect to jira...")
    jira_conn = jira_connection(cfg)
    project = get_project_id(jira_conn, cfg['project'])
    component = get_component_id(jira_conn, project.id, cfg['component'])
    board = get_board_id(jira_conn, cfg['board'])
    sprint = get_latest_sprint(jira_conn, board.id, cfg['sprintname'])
    
    cases = redis_get('cases')

    for case in new_cases:
        assignee = None
        for member in cfg['team']:
            for account in member["accounts"]:
                if account.lower() in cases[case]['account'].lower():
                    assignee = member
        if assignee == None:
            assignee = get_random_member(cfg['team'])
        assignee['displayName'] = assignee['name']
        priority = portal2jira_sevs[cases[case]['severity']]
        card_info = {
            'project': {'key': cfg['project']},
            'issuetype': {'name': cfg['type']},
            'components': [{'name': cfg['component']}],
            'priority': {'name': priority},
            'labels': cfg['labels'],
            'assignee': {'name': assignee['jira_user']},
            'customfield_12310243': float(cfg['points']),
            'summary': case + ': ' + cases[case]['problem'],
            'description': 'This card was automatically created from the Field Engineering Sync Job.\r\n\r\n'
            + 'This card was created because it had a severity of '
            + cases[case]['severity']
            + '\r\n'
            + 'The account for the case is '
            + cases[case]['account']
            + '\r\n'
            + 'The case had an internal status of: '
            + cases[case]['status']
            + '\r\n\r\n'
            + '*Description:* \r\n\r\n'
            + cases[case]['description']
            + '\r\n'
            }

        logging.warning('A card needs created for case {}'.format(case))
        logging.warning(card_info)
        
        if action == 'create':
            logging.warning('creating card for case {}'.format(case))
            new_card = jira_conn.create_issue(fields=card_info)
            logging.warning('created {}'.format(new_card.key))
            if 'field' in card_info['labels']:
                email_content.append( f"A JIRA issue (https://issues.redhat.com/browse/{new_card}) has been created for a new Telco5G case:\nCase #: {case} (https://access.redhat.com/support/cases/{case})\nAccount: {cases[case]['account']}\nSummary: {cases[case]['problem']}\nSeverity: {cases[case]['severity']}\nDescription: {cases[case]['description']}\n\nIt is initially being tracked by {assignee['name']}.\n")
            else:
                email_content.append( f"A JIRA issue (https://issues.redhat.com/browse/{new_card}) has been created for a new CNV case:\nCase #: {case} (https://access.redhat.com/support/cases/{case})\nAccount: {cases[case]['account']}\nSummary: {cases[case]['problem']}\nSeverity: {cases[case]['severity']}\nDescription: {cases[case]['description']}\n\nIt is initially being tracked by {assignee['name']}.\n")

            # Add newly create card to the sprint
            logging.warning('moving card to sprint {}'.format(sprint.id))
            jira_conn.add_issues_to_sprint(sprint.id, [new_card.key])

            # Move the card from backlog to the To Do column
            logging.warning('moving card from backlog to "To Do" column')
            jira_conn.transition_issue(new_card.key, 'To Do')

            # Add links to case, etc
            logging.warning('adding link to support case {}'.format(case))
            jira_conn.add_simple_link(new_card.key, { 
                'url': 'https://access.redhat.com/support/cases/' + case, 
                'title': 'Support Case'
                })

            bz = []
            if 'bug' in cases[case]:
                bz = cases[case]['bug']
                logging.warning('adding link to BZ {}'.format(cases[case]['bug']))
                jira_conn.add_simple_link(new_card.key, { 
                    'url': 'https://bugzilla.redhat.com/show_bug.cgi?id=' + cases[case]['bug'],
                    'title': 'BZ ' + cases[case]['bug'] })

            if 'tags' in cases[case].keys():
                tags = cases[case]['tags']
            else:
                tags = ['shift_telco5g'] # trigged by case summary, not tag

            new_cards[new_card.key] = {
                "card_status": status_map[new_card.fields.status.name],
                "card_created": new_card.fields.created,
                "account": cases[case]['account'],
                "summary": case + ': ' + cases[case]['problem'],
                "description": cases[case]['description'],
                "comments": None,
                "assignee": assignee,
                "case_number": case,
                "tags": tags,
                "labels": cfg['labels'],
                "bugzilla": bz,
                "severity": re.search(r'[a-zA-Z]+', cases[case]['severity']).group(),
                "priority": new_card.fields.priority.name,
                "case_status": cases[case]['status'],
                "escalated": False,
                "watched": False,
                "crit_sit": False
            }
    
    return email_content, new_cards

def notify(ini,blist):
    
    body = ''
    for line in blist:
        body += f"{line}\n"

    msg = EmailMessage()
    msg.set_content(body)

    msg['Subject'] = ini['subject']
    msg['From'] = ini['from']
    msg['to'] = ini['to']

    s = smtplib.SMTP(ini['smtp'])
    s.send_message(msg)
    s.quit()

def slack_notify(ini, blist):
    body = ''
    for line in blist:
        body += f"{line}\n"

    client = WebClient(token = ini['slack_token'])
    msgs = re.split(r'A JIRA issue \(https:\/\/issues\.redhat\.com\/browse\/|Description: ', body)

    #Adding the text removed by re.split() and adding ping to assignee 
    for i in range(1, len(msgs)):
        if i % 2 == 1:
            msgs[i] = "A JIRA issue (https://issues.redhat.com/browse/" + msgs[i]
        if i % 2 == 0:
            msgs[i] = "Description: " + msgs[i]
            assign = re.findall(r'(?<=\nIt is initially being tracked by )[\w ]*', msgs[i])
            for j in ini['team']:
                if j['name'] == assign[0]:
                    userid = j['slack_user']
            msgs[i] = re.sub(r'\nIt is initially being tracked by.*', '', msgs[i])
            msgs[i-1] = msgs[i-1] + f"\nIt is initially being tracked by <@{userid}>"

    #Posting Summaries + reply with Description
    for k in range(1, len(msgs)-1, 2):
        message = client.chat_postMessage(channel = ini['slack_channel'], text = msgs[k])
        reply = client.chat_postMessage(channel = ini['slack_channel'], text = msgs[k+1], thread_ts = message['ts'])

def set_defaults():
    defaults = {}
    defaults['smtp']        = 'smtp.corp.redhat.com'
    defaults['from']        = 't5g_jira@redhat.com'
    defaults['to']          = ''
    defaults['alert_to']    = 'dcritch@redhat.com'
    defaults['subject']     = 'New Card(s) Have Been Created to Track Telco5G Issues'
    defaults['sprintname']  = 'T5GFE' #Previous Sprintname: 'Labs and Field Sprint' 
    defaults['server']      = 'https://issues.redhat.com'
    defaults['project']     = 'KNIECO'
    defaults['component']   = 'KNI Labs & Field'
    defaults['board']       = 'KNI-ECO Labs & Field'
    defaults['email']       = ''
    defaults['type']        = 'Story'
    defaults['labels']      = 'field, no-qe, no-doc'
    defaults['priority']    = 'High'
    defaults['points']      = 3
    defaults['password']    = ''
    defaults['card_action'] = 'none'
    defaults['debug']       = 'False'
    defaults['fields']      =  ["case_account_name","case_summary","case_number","case_status","case_owner","case_severity","case_createdDate","case_lastModifiedDate","case_bugzillaNumber","case_description","case_tags", "case_product", "case_version", "case_closedDate"]
    defaults['query']       = "case_summary:*webscale* OR case_tags:*shift_telco5g* OR case_tags:*cnv*"
    defaults['slack_token']   = ''
    defaults['slack_channel'] = ''
    defaults['max_jira_results'] = 500
    defaults['max_portal_results'] = 5000
    return defaults

def read_config(file):
    '''
    Takes a filename as input and reads the values into a dictionary.
    file should be in the format of "key: value" pairs. no value will
    simply set the key in the dictionary.
    e.g.
        debug
        email : me@redhat.com, you@redhat.com
        email: me@redhat.com, you@redhat.com
        email:me@redhat.com, you@redhat.com
    '''

    cfg_dict = {}
    with open(file) as filep:
        for line in filep:
            if not line.startswith("#") and not line.startswith(";"):
                a = line.split(':', 1)
                key = a[0].replace('\n', '').strip()

                if len(a) > 1:
                    value = a[1].replace('\n', '').strip()
                    cfg_dict[key] = value
                elif len(key) > 0:
                    cfg_dict[key] = True
    return cfg_dict

def read_env_config(keys):
    ecfg = {}

    for key in keys:
        if 't5g_' + key in os.environ:
            ecfg[key] = os.environ.get('t5g_' + key)

    return ecfg

def get_token(offline_token):
  # https://access.redhat.com/articles/3626371
  data = { 'grant_type' : 'refresh_token', 'client_id' : 'rhsm-api', 'refresh_token': offline_token }
  url = 'https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token'
  r = requests.post(url, data=data)
  # It returns 'application/x-www-form-urlencoded'
  token = r.json()['access_token']
  return(token)

def redis_set(key, value):

    logging.warning("syncing {}..".format(key))
    r_cache = redis.Redis(host='redis')
    r_cache.mset({key: value})
    logging.warning("{}....synced".format(key))

def redis_get(key):

    logging.warning("fetching {}..".format(key))
    r_cache = redis.Redis(host='redis')
    data = r_cache.get(key)
    if data is not None:
        data = json.loads(data.decode("utf-8"))
    else:
        data = {}
    logging.warning("{} ....fetched".format(key))

    return data

def cache_cases(cfg):
  # https://source.redhat.com/groups/public/hydra/hydra_integration_platform_cee_integration_wiki/hydras_api_layer

  token = get_token(cfg['offline_token'])
  query = cfg['query']
  fields = ",".join(cfg['fields'])
  query = "({})".format(query)
  num_cases = cfg['max_portal_results']
  payload = {"q": query, "partnerSearch": "false", "rows": num_cases, "fl": fields}
  headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
  url = "https://access.redhat.com/hydra/rest/search/cases"

  logging.warning("searching the portal for cases")
  start = time.time()
  r = requests.get(url, headers=headers, params=payload)
  cases_json = r.json()['response']['docs']
  end = time.time()
  logging.warning("found {} cases in {} seconds".format(len(cases_json), (end-start)))
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
        "product": case["case_product"][0] + " " + case["case_version"]
    }
    # Sometimes there is no BZ attached to the case
    if "case_bugzillaNumber" in case:
        cases[case["case_number"]]["bug"] = case["case_bugzillaNumber"]
    # Sometimes there is no tag attached to the case
    if "case_tags" in case:
        case_tags = case["case_tags"]
        if len(case_tags) == 1:
            tags = case_tags[0].split(';') # csv instead of a proper list
        else:
            tags = case_tags
        cases[case["case_number"]]["tags"] = tags
    else: # assume. came from query, so probably telco
        cases[case["case_number"]]["tags"] = ['shift_telco5g']
    # Sometimes there is no closed date attached to the case
    if "case_closedDate" in case:
        cases[case["case_number"]]["closeddate"] = case["case_closedDate"]

  redis_set('cases', json.dumps(cases))

def cache_bz(cfg):
    
    cases = redis_get('cases')
    if cases is None:
        redis_set('bugs', json.dumps(None))
        return
    
    bz_url = "bugzilla.redhat.com"
    bz_api = bugzilla.Bugzilla(bz_url, api_key=cfg['bz_key'])
    bz_dict = {}
    token = get_token(cfg['offline_token'])
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}

    logging.warning("getting all bugzillas")
    for case in cases:
        if "bug" in cases[case] and cases[case]['status'] != "Closed":
            bz_endpoint = "https://access.redhat.com/hydra/rest/v1/cases/" + case
            r_bz = requests.get(bz_endpoint, headers=headers)
            bz_dict[case] = r_bz.json()['bugzillas']

    logging.warning("getting additional info via bugzilla API")
    for case in bz_dict:
        for bug in bz_dict[case]:
            try:
                bugs = bz_api.getbug(bug['bugzillaNumber'])
            except: # restricted access
                logging.warning("error retrieving bug {} - restricted?".format(bug['bugzillaNumber']))
                bugs = None
            if bugs:
                bug['target_release'] = bugs.target_release
                bug['assignee'] = bugs.assigned_to
                bug['last_change_time'] = datetime.datetime.strftime(datetime.datetime.strptime(str(bugs.last_change_time), '%Y%m%dT%H:%M:%S'), '%Y-%m-%d') # convert from xmlrpc.client.DateTime to str and reformat
                bug['internal_whiteboard'] = bugs.internal_whiteboard
            else:
                bug['target_release'] = ['unavailable']
                bug['assignee'] = 'unavailable'
                bug['last_change_time'] = 'unavailable'
                bug['internal_whiteboard'] = 'unavailable'

    redis_set('bugs', json.dumps(bz_dict))

def cache_issues(cfg):

    logging.warning("caching issues")
    cases = redis_get('cases')
    if cases is None:
        redis_set('issues', json.dumps(None))
        return
    
    token = get_token(cfg['offline_token'])
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}

    logging.warning("attempting to connect to jira...")
    jira_conn = jira_connection(cfg)

    jira_issues = {}
    open_cases = [case for case in cases if cases[case]['status'] != 'Closed']
    for case in open_cases:
        issues_url = "https://access.redhat.com/hydra/rest/cases/{}/jiras".format(case)
        issues = requests.get(issues_url, headers=headers)
        if issues.status_code == 200 and len(issues.json()) > 0:
            case_issues = []
            for issue in issues.json():
                if 'title' in issue.keys():
                    try:
                        bug = jira_conn.issue(issue['resourceKey'])
                    except JIRAError:
                        logging.warning("Can't access {}".format(issue['resourceKey']))
                        continue

                    # Retrieve QA contact from Jira card
                    try:
                        qa_contact = bug.fields.customfield_12315948.emailAddress
                    except AttributeError:
                        qa_contact = None

                    # Retrieve assignee from Jira card
                    if bug.fields.assignee is not None:
                        assignee = bug.fields.assignee.emailAddress
                    else:
                        assignee = None

                    # Retrieve target release from Jira card
                    if len(bug.fields.fixVersions) > 0:
                        fix_versions = []
                        for version in bug.fields.fixVersions:
                            fix_versions.append(version.name)
                    else:
                        fix_versions = None

                    case_issues.append({
                        'id': issue['resourceKey'],
                        'url': issue['resourceURL'],
                        'title': issue['title'],
                        'status': issue['status'],
                        'updated': datetime.datetime.strftime(datetime.datetime.strptime(str(issue['lastModifiedDate']), '%Y-%m-%dT%H:%M:%SZ'), '%Y-%m-%d'),
                        'qa_contact': qa_contact,
                        'assignee': assignee,
                        'fix_versions': fix_versions
                    })
            if len(case_issues) > 0:
                jira_issues[case] = case_issues
    
    redis_set('issues', json.dumps(jira_issues))
    logging.warning("issues cached")
                   

def cache_escalations(cfg):
    '''Get cases that have been escalated from Smartsheet'''
    cases = redis_get('cases')
    if cases is None:
        redis_set('escalations', json.dumps(None))
        return

    logging.warning("getting escalated cases from smartsheet")
    smart = smartsheet.Smartsheet(cfg['smartsheet_access_token'])
    sheet_dict = smart.Sheets.get_sheet(cfg['sheet_id']).to_dict()

    # Get Column ID's
    column_map = {}
    for column in sheet_dict['columns']:
        column_map[column['title']] = column['id']
    no_tracking_col = column_map['No longer tracking']
    no_escalation_col = column_map['No longer an escalation']
    case_col = column_map['Case']

    # Get Escalated Cases
    escalations = []
    for row in sheet_dict['rows']:
        for cell in row['cells']:
            if cell['columnId'] == no_tracking_col:
                if 'value' in cell and cell['value'] == True:
                    break
            if cell['columnId'] == no_escalation_col:
                if 'value' in cell:
                    break
            if cell['columnId'] == case_col and 'value' in cell and cell['value'][:8] not in cases.keys():
                break
            elif cell['columnId'] == case_col and 'value' in cell and cell['value'][:8] in cases.keys():
                escalations.append(cell['value'][:8])

    redis_set('escalations', json.dumps(escalations))

def cache_cards(cfg, self=None, background=False):

    cases = redis_get('cases')
    bugs = redis_get('bugs')
    issues = redis_get('issues')
    escalations = redis_get('escalations')
    watchlist = redis_get('watchlist')
    details = redis_get('details')
    logging.warning("attempting to connect to jira...")
    jira_conn = jira_connection(cfg)
    max_cards = cfg['max_jira_results']
    start = time.time()
    project = get_project_id(jira_conn, cfg['project'])
    logging.warning("project: {}".format(project))
    component = get_component_id(jira_conn, project.id, cfg['component'])
    logging.warning("component: {}".format(component))
    board = get_board_id(jira_conn, cfg['board'])
    logging.warning("board: {}".format(board))
    sprint = get_latest_sprint(jira_conn, board.id, cfg['sprintname'])
    logging.warning("sprint: {}".format(sprint))

    logging.warning("pulling cards from jira")

    jira_query = 'sprint=' + str(sprint.id) + ' AND (labels = "field" OR labels = "cnv")'
    card_list = jira_conn.search_issues(jira_query, 0, max_cards).iterable
    time_now = datetime.datetime.now(datetime.timezone.utc)

    jira_cards = {}
    for index, card in enumerate(card_list):
        if background:
            # Update task information for progress bar
            self.update_state(state='PROGRESS',
                              meta={'current': index, 'total': len(card_list),
                                    'status': "Refreshing Cards in Background..."}
                            )
        issue = jira_conn.issue(card)
        comments = jira_conn.comments(issue)
        card_comments = []
        for comment in comments:
            body = comment.body
            body = re.sub(r'(?<!\||\s)\s*?((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?)',"<a href=\""+r'\g<0>'+"\" target='_blank'>"+r'\g<0>'"</a>", body)
            body = re.sub(r'\[([\s\w!"#$%&\'()*+,-.\/:;<=>?@[^_`{|}~]*?\s*?)\|\s*?((http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])?[\s]*)\]',"<a href=\""+r'\2'+"\" target='_blank'>"+r'\1'+"</a>", body)
            tstamp = comment.updated
            card_comments.append((body, tstamp))
        case_number = get_case_from_link(jira_conn, card)
        if not case_number or case_number not in cases.keys():
            logging.warning("card isn't associated with a case. discarding ({})".format(card))
            continue
        assignee = {
            "displayName": issue.fields.assignee.displayName,
            "key": issue.fields.assignee.key,
            "name": issue.fields.assignee.name
        }

        # Get contributors
        if issue.fields.customfield_12315950:
            for engineer in issue.fields.customfield_12315950:
                contributor = {
                    "displayName": engineer.displayName,
                    "key": engineer.key,
                    "name": engineer.name
                }
        else:
            contributor = {
                "displayName": None,
                "key": None,
                "name": None
            }
        
        tags = []
        if 'tags' in cases[case_number].keys():
            tags = cases[case_number]['tags']
        else: # assume telco
            tags = ['shift_telco5g']
        if 'bug' in cases[case_number].keys() and case_number in bugs.keys():
            bugzilla = bugs[case_number]
        else:
            bugzilla = None
        
        if case_number in issues:
            case_issues = issues[case_number]
        else:
            case_issues = None

        if case_number in escalations:
            escalated = True
        else:
            escalated = False
        
        if 'PotentialEscalation' in issue.fields.labels and escalated is False:
            potenial_escalation = True
        else:
            potenial_escalation = False

        if case_number in watchlist:
            watched = True
        else:
            watched = False
        if case_number in details.keys():
            crit_sit = details[case_number]['crit_sit']
            group_name = details[case_number]['group_name']
        else:
            crit_sit = False
            group_name = None

        jira_cards[card.key] = {
            "card_status": status_map[issue.fields.status.name],
            "card_created": issue.fields.created,
            "account": cases[case_number]['account'],
            "summary": cases[case_number]['problem'],
            "description": cases[case_number]['description'],
            "comments": card_comments,
            "assignee": assignee,
            "contributor": contributor,
            "case_number": case_number,
            "tags": tags,
            "labels": issue.fields.labels,
            "bugzilla": bugzilla,
            "issues": case_issues,
            "severity": re.search(r'[a-zA-Z]+', cases[case_number]['severity']).group(),
            "priority": issue.fields.priority.name,
            "escalated": escalated,
            "potenial_escalation": potenial_escalation,
            "watched": watched,
            "product": cases[case_number]['product'],
            "case_status": cases[case_number]['status'],
            "crit_sit": crit_sit,
            "group_name": group_name,
            "case_updated_date": datetime.datetime.strftime(datetime.datetime.strptime(cases[case_number]['last_update'], '%Y-%m-%dT%H:%M:%SZ'), '%Y-%m-%d %H:%M'),
            "case_days_open": (time_now.replace(tzinfo=None) - datetime.datetime.strptime(cases[case_number]['createdate'], '%Y-%m-%dT%H:%M:%SZ')).days
        }

    end = time.time()
    logging.warning("got {} cards in {} seconds".format(len(jira_cards), (end - start)))
    redis_set('cards', json.dumps(jira_cards))
    redis_set('timestamp', json.dumps(str(datetime.datetime.utcnow())))

def cache_watchlist(cfg):

    cases = redis_get('cases')
    token = get_token(cfg['offline_token'])
    num_cases = cfg['max_portal_results']
    payload = {"rows": num_cases}
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    url = "https://access.redhat.com/hydra/rest/eh/escalations?highlight=true"
    r = requests.get(url, headers=headers, params=payload)
    
    watchlist = []
    for watched in r.json():
        watched_cases = watched['cases']
        for case in watched_cases:
            caseNumber = case['caseNumber']
            if caseNumber in cases:
                watchlist.append(caseNumber)
    
    redis_set('watchlist', json.dumps(watchlist))

def cache_details(cfg):
    '''Caches CritSit, CaseGroup, and Bugzillas from open cases'''
    cases = redis_get('cases')
    if cases is None:
        redis_set('bugs', json.dumps(None))
        redis_set('details', json.dumps(None))
        return

    bz_url = "bugzilla.redhat.com"
    bz_api = bugzilla.Bugzilla(bz_url, api_key=cfg['bz_key'])
    bz_dict = {}
    token = get_token(cfg['offline_token'])
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
    case_details = {}
    logging.warning("getting all bugzillas and case details")
    for case in cases:
        if cases[case]['status'] != "Closed":
            case_endpoint = "https://access.redhat.com/hydra/rest/v1/cases/" + case
            r_case = requests.get(case_endpoint, headers=headers)
            if r_case.status_code == 401:
                token = get_token(cfg['offline_token'])
                headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
                r_case = requests.get(case_endpoint, headers=headers)
            if "critSit" in r_case.json():
                crit_sit = r_case.json()['critSit']
            else:
                crit_sit = False
            if "groupName" in r_case.json():
                group_name = r_case.json()['groupName']
            else:
                group_name = None
            
            case_details[case] = {
                "crit_sit": crit_sit,
                "group_name": group_name
            }
            if "bug" in cases[case]:
                bz_dict[case] = r_case.json()['bugzillas']

    logging.warning("getting additional info via bugzilla API")
    for case in bz_dict:
        for bug in bz_dict[case]:
            try:
                bugs = bz_api.getbug(bug['bugzillaNumber'])
            except:
                logging.warning("error retrieving bug {} - restricted?".format(bug['bugzillaNumber']))
                bugs = None
            if bugs:
                bug['target_release'] = bugs.target_release
                bug['assignee'] = bugs.assigned_to
                bug['last_change_time'] = datetime.datetime.strftime(datetime.datetime.strptime(str(bugs.last_change_time), '%Y%m%dT%H:%M:%S'), '%Y-%m-%d') # convert from xmlrpc.client.DateTime to str and reformat
                bug['internal_whiteboard'] = bugs.internal_whiteboard
                bug['qa_contact'] = bugs.qa_contact
            else:
                bug['target_release'] = ['unavailable']
                bug['assignee'] = 'unavailable'
                bug['last_change_time'] = 'unavailable'
                bug['internal_whiteboard'] = 'unavailable'
                bug['qa_contact'] = 'unavailable'
    
    redis_set('bugs', json.dumps(bz_dict))
    redis_set('details', json.dumps(case_details))
    
    cache_issues(cfg)

def get_case_from_link(jira_conn, card):

    links = jira_conn.remote_links(card)
    for link in links:
        t = jira_conn.remote_link(card, link)
        if t.raw['object']['title'] == "Support Case":
            case_number = get_case_number(t.raw['object']['url'])
            if len(case_number) > 0:
                return case_number
    return None

def generate_stats(case_type):
    ''' generate some stats '''
    
    logging.warning("generating stats for {}".format(case_type))
    start = time.time()
    
    all_cards = redis_get('cards')
    if case_type == 'telco5g':
        cards = {c:d for (c,d) in all_cards.items() if 'field' in d['labels']}
    elif case_type == 'cnv':
        cards = {c:d for (c,d) in all_cards.items() if 'cnv' in d['labels']}
    else:
        logging.warning("unknown case type: {}".format(case_type))
        return {}
    
    all_cases = redis_get('cases')
    if case_type == 'telco5g':
        cases = {c:d for (c,d) in all_cases.items() if 'shift_telco5g' in d['tags']}
    elif case_type == 'cnv':
        cases = {c:d for (c,d) in all_cases.items() if 'cnv' in d['tags']}
    else:
        logging.warning("unknown case type: {}".format(case_type))
        return {}
    
    bugs = redis_get('bugs')

    today = datetime.date.today()
    
    customers = [cards[card]['account'] for card in cards]
    engineers = [cards[card]['assignee']['displayName'] for card in cards]
    severities = [cards[card]['severity'] for card in cards]
    statuses = [cards[card]['case_status'] for card in cards]
        
    stats = {
        'by_customer': {c:0 for c in customers},
        'by_engineer': {e:0 for e in engineers},
        'by_severity': {s:0 for s in severities},
        'by_status': {s:0 for s in statuses},
        'high_prio': 0,
        'escalated': 0,
        'watched': 0,
        'open_cases': 0,
        'weekly_closed_cases': 0,
        'weekly_opened_cases': 0,
        'daily_closed_cases': 0,
        'daily_opened_cases': 0,
        'no_updates': 0,
        'no_bzs': 0,
        'bugs': {
            'unique': 0,
            'no_target': 0
        },
        'crit_sit': 0,
        'total_escalations': 0
    }

    for (card, data) in cards.items():
        account = data['account']
        engineer = data['assignee']['displayName']
        severity = data['severity']
        status = data['case_status']
    
        stats['by_status'][status] += 1

        if status != 'Closed':
            stats['by_customer'][account] += 1
            stats['by_engineer'][engineer] += 1
            stats['by_severity'][severity] += 1
            if severity == "High" or severity == "Urgent":
                stats['high_prio'] += 1
            if cards[card]['escalated']:
                stats['escalated'] += 1
            if cards[card]['watched']:
                stats['watched'] += 1
            if cards[card]['crit_sit']:
                stats['crit_sit'] += 1
            if cards[card]['escalated'] or cards[card]['watched'] or cards[card]['crit_sit']:
                stats['total_escalations'] += 1
            if cards[card]['bugzilla'] is None:
                stats['no_bzs'] += 1

    for (case, data) in cases.items():
        if data['status'] == 'Closed':
            if (today - datetime.datetime.strptime(data['closeddate'], '%Y-%m-%dT%H:%M:%SZ').date()).days < 7:
                stats['weekly_closed_cases'] += 1
            if (today - datetime.datetime.strptime(data['closeddate'], '%Y-%m-%dT%H:%M:%SZ').date()).days <= 1:
                stats['daily_closed_cases'] += 1
        else:
            stats['open_cases'] += 1
            if (today - datetime.datetime.strptime(data['createdate'], '%Y-%m-%dT%H:%M:%SZ').date()).days < 7:
                stats['weekly_opened_cases'] += 1
            if (today - datetime.datetime.strptime(data['createdate'], '%Y-%m-%dT%H:%M:%SZ').date()).days <= 1:
                stats['daily_opened_cases'] += 1
            if (today - datetime.datetime.strptime(data['last_update'], '%Y-%m-%dT%H:%M:%SZ').date()).days < 7:
                stats['no_updates'] += 1
    
    all_bugs = {}
    for (case, bzs) in bugs.items():
        if case in cases and cases[case]['status'] != 'Closed':
            for bug in bzs:
                all_bugs[bug['bugzillaNumber']] = bug
    no_target = {b: d for (b, d) in all_bugs.items() if d['target_release'][0] == '---'}
    stats['bugs']['unique'] = len(all_bugs)
    stats['bugs']['no_target'] = len(no_target)
     

    end = time.time()
    logging.warning("generated stats in {} seconds".format((end-start)))

    return stats

def cache_stats(case_type):

    logging.warning("caching {} stats".format(case_type))
    all_stats = redis_get('{}_stats'.format(case_type))
    new_stats = generate_stats(case_type)
    tstamp = datetime.datetime.utcnow()
    today = tstamp.strftime('%Y-%m-%d')
    stats = {today: new_stats}
    all_stats.update(stats)
    redis_set('{}_stats'.format(case_type), json.dumps(all_stats))

def plot_stats(case_type):

    historical_stats = redis_get("{}_stats".format(case_type))
    x_values = [day for day in historical_stats]
    y_values = {
        'escalated': [],
        'watched': [],
        'open_cases': [],
        'new_cases': [],
        'closed_cases': [],
        'no_updates': [],
        'no_bzs': [],
        'bugs_unique': [],
        'bugs_no_tgt': [],
        'high_prio': [],
        'crit_sit': [],
        'total_escalations': []
        }
    for day, stat in historical_stats.items():
        y_values['escalated'].append(exists_or_zero(stat, 'escalated'))
        y_values['watched'].append(exists_or_zero(stat, 'watched'))
        y_values['open_cases'].append(exists_or_zero(stat, 'open_cases'))
        y_values['new_cases'].append(exists_or_zero(stat, 'daily_opened_cases'))
        y_values['closed_cases'].append(exists_or_zero(stat, 'daily_closed_cases'))
        y_values['no_updates'].append(exists_or_zero(stat, 'no_updates'))
        y_values['no_bzs'].append(exists_or_zero(stat, 'no_bzs'))
        y_values['bugs_unique'].append(exists_or_zero(stat['bugs'], 'unique'))
        y_values['bugs_no_tgt'].append(exists_or_zero(stat['bugs'], 'no_target'))
        y_values['high_prio'].append(exists_or_zero(stat, 'high_prio'))
        y_values['crit_sit'].append(exists_or_zero(stat, 'crit_sit'))
        y_values['total_escalations'].append(exists_or_zero(stat, 'total_escalations'))
    
    return x_values, y_values
        
def exists_or_zero(data, key):
    ''' hack for when a new data point is added, so history does not exist'''
    if key in data.keys():
        return data[key]
    else:
        return 0

def sync_priority(cfg):
    cards = redis_get("cards")
    sev_map = {re.search(r'[a-zA-Z]+', k).group(): v for k, v in portal2jira_sevs.items()}
    out_of_sync = {card:data for (card, data) in cards.items() if data['card_status'] != 'Done' and data['priority'] != sev_map[data['severity']]}
    for (card, data) in out_of_sync.items():
        new_priority = sev_map[data['severity']]
        logging.warning("{} has priority of {}, but case is {}".format(card, data['priority'], data['severity']))
        logging.warning("updating {} to a priority of {}".format(card, new_priority))
        jira_conn = jira_connection(cfg)
        oos_issue = jira_conn.issue(card)
        oos_issue.update(fields={'priority': {'name': new_priority}})
    return out_of_sync

def main():
    print("libtelco5g")

if __name__ == '__main__':
    main()


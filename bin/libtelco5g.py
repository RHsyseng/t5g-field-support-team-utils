#! /usr/bin/python -W ignore
# #! /usr/bin/python -W ignore

'''
This script takes a configuration file name as its only argument.
Not passing a configuration file as an option will cause the script
to use its default settings and any environmental settings.

Setting set in the environment override the ones in the configuration file.
'''

from __future__ import print_function
import os
import getpass
from jira import JIRA
from jira.client import ResultList
from jira.resources import Issue
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

# for portal to jira mapping
portal2jira_sevs = {
    "1 (Urgent)"    : "Urgent",
    "2 (High)"      : "High",
    "3 (Normal)"    : "Medium",
    "4 (Low)"       : "Low"
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
    board = conn.sprints(bid, state="active") # still seems to return everything?
    last_sprint_name = sprintname + ".*" + str(last_sprint_number)
    
    for b in board:
        if re.search(last_sprint_name, b.name):
            return b


def get_cards(conn, sid, user=None, include_closed=True):
    ''' Gets a list of cards in the latest sprint
    sid    - sprint id

    Returns a list of card names 
    Return: ['KNIECO-2411', 'KNIECO-2406', ...]
    '''

    returnlist = []
    if user is not None and include_closed is False:
        user = user.replace('@', '\\u0040')
        if include_closed is False:
            cards = conn.search_issues('sprint=' + str(sid) + ' and assignee = ' + str(user) + ' and status != "DONE"', 0, 1000).iterable
        else:
            cards = conn.search_issues('sprint=' + str(sid) + ' and assignee = ' + str(user), 0, 1000).iterable
    else:
        if include_closed is False:
            cards = conn.search_issues('sprint=' + str(sid) + ' and assignee = ' + str(user) + ' and status != "DONE"', 0, 1000).iterable
        else:
            cards = conn.search_issues('sprint=' + str(sid), 0, 1000).iterable
    
    for item in cards:
        returnlist.append(str(item))
    return returnlist




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
    in_progress = [card for card in cards if cards[card]['card_status'] == 'In Progress']
    code_review = [card for card in cards if cards[card]['card_status'] == 'Code Review']
    qe_review = [card for card in cards if cards[card]['card_status'] == 'QE Review']
    done = [card for card in cards if cards[card]['card_status'] == 'Done']
    summary = {}
    summary['backlog'] = len(backlog)
    summary['in_progress'] = len(in_progress)
    summary['code_review'] = len(code_review)
    summary['qe_review'] = len(qe_review)
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

def parse_cases(conn, cases, cards, debug=False):
    ''' Check which cases are mentioned in card links '''
    ''' Returns: list of cases not mentioned in cards '''

    cardcases = []
    caselist = []
    needed = []
    sevs_to_create = ['1 (Urgent)', '2 (High)', '3 (Normal)', '4 (Low)']
    if debug:
        dpp = pprint.PrettyPrinter(indent=2)

    ''' Build a list of email cases '''
    for i in cases.keys():
        caselist.append(i)

    if debug:
        print('\nDEBUG: Case List')
        dpp.pprint(caselist)

    ''' Parse the cards to build a list of mentioned case numbers '''
    for card in cards:
        links = conn.remote_links(card)

        ''' iterate through the links in the card to see if there are any cases '''
        for link in links:
            t = conn.remote_link(card, link)

            ''' Search link for case number and append it to cardcases '''
            t_case_number = get_case_number(t.raw['object']['url'])
            if len(t_case_number) > 0:
                cardcases.append(t_case_number)
                if debug:
                    print('\nDEBUG:', card)
                    dpp.pprint(t_case_number)

    ''' If the case is not in the Jira card, add it to the needed list '''
    for c in cases.keys():
        if c not in cardcases and cases[c]['severity'] in sevs_to_create:
            needed.append(c)

    return needed

def closed_cases(conn, cases, cards, debug=False):
    
    cardcases = []
    caselist = []
    needed = []
    if debug:
        dpp = pprint.PrettyPrinter(indent=2)

    ''' Build a list of email cases '''
    for i in cases.keys():
        caselist.append(i)

    if debug:
        print('\nDEBUG: Case List')
        dpp.pprint(caselist)

    ''' Parse the cards to build a list of mentioned case numbers '''
    for card in cards:
        links = conn.remote_links(card)

        ''' iterate through the links in the card to see if there are any cases '''
        for link in links:
            t = conn.remote_link(card, link)

            ''' Search link for case number and append it to cardcases '''
            t_case_number = get_case_number(t.raw['object']['url'])
            if len(t_case_number) > 0:
                if t_case_number not in caselist:
                    print("%s is still open, %s is closed" % (card, t_case_number))
                #cardcases.append(t_case_number)
                #if debug:
                #    print('\nDEBUG:', card)
                #    dpp.pprint(t_case_number)
    
    #return needed

def duplicate_cards(conn, cards, debug=False):
    ''' Check which cases are mentioned in card links '''
    ''' Returns: list of cases not mentioned in cards '''

    cardcases = []
    caselist = []
    needed = []
    case2issue = {}
    
    ''' Parse the cards to build a list of mentioned case numbers '''
    for card in sorted(cards):
        links = conn.remote_links(card)

        ''' iterate through the links in the card to see if there are any cases '''
        for link in links:
            t = conn.remote_link(card, link)

            ''' Search link for case number and append it to cardcases '''
            t_case_number = get_case_number(t.raw['object']['url'])
            if len(t_case_number) > 0:
                if t_case_number not in cardcases:
                    case2issue[t_case_number] = card
                    cardcases.append(t_case_number)
                else:
                    print("Duplicate card detected. issue %s is likely a dupe of %s" %(card, case2issue[t_case_number]))


def get_random_member(team):
    return random.choice(team)

def create_cases(conn, ini, sid, cases, needed, team, action='none'):
    '''
    conn   - connection
    ini    - ini configuration
    sid    - sprint id
    cases  - dictionary of all cases
    needed - list of cases that need a card created
    '''

    email_content = []


    for case in needed:
        print('\n\n-----------')
        assignee = None
        for member in team:
            for account in member["accounts"]:
                if account.lower() in cases[case]['account'].lower():
                    assignee = member
        if assignee == None:
            assignee = get_random_member(team)
        priority = portal2jira_sevs[cases[case]['severity']]
        card_info = {
            'project': {'key': ini['project']},
            'issuetype': {'name': ini['type']},
            'components': [{'name': ini['component']}],
            'priority': {'name': priority},
            'labels': ini['labels'],
            'assignee': {'name': assignee['jira_user']},
            'customfield_12310243': float(ini['points']),
            'summary': cases[case]['problem'],
            'description': 'This card was automatically created from the "Telco5G open cases report".\r\n\r\n'
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

        print('A card needs created for case', case)
        print('Card data:')
        pp = pprint.PrettyPrinter(indent=2)
        pp.pprint(card_info)

        if action == 'create':
            print('\nCreating card for case', case)
        
            new_card = conn.create_issue(fields=card_info)
            print('  - Created', new_card.key)

            email_content.append( f"A JIRA issue (https://issues.redhat.com/browse/{new_card}) has been created for a new Telco5G case:\nCase #: {case} (https://access.redhat.com/support/cases/{case})\nAccount: {cases[case]['account']}\nSummary: {cases[case]['problem']}\nSeverity: {cases[case]['severity']}\nDescription: {cases[case]['description']}\n\nIt is initially being tracked by {assignee['name']}.\n")

            # Add newly create card to the sprint
            print('  - Moving card to sprint (', sid, ')')
            conn.add_issues_to_sprint(sid, [new_card.key])

            # Move the card from backlog to the To Do column
            print('  - Moving card from backlog to "To Do" column')
            conn.transition_issue(new_card.key, 'To Do')

            # Add links to case, etc
            print('  - Adding link to support case', case)
            conn.add_simple_link(new_card.key, { 
                'url': 'https://access.redhat.com/support/cases/' + case, 
                'title': 'Support Case'
                })

            if 'bug' in cases[case]:
                print('  - Adding link to BZ', cases[case]['bug'])
                conn.add_simple_link(new_card.key, { 
                    'url': 'https://bugzilla.redhat.com/show_bug.cgi?id=' + cases[case]['bug'],
                    'title': 'BZ ' + cases[case]['bug'] })
    
    return email_content

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
    defaults['sheet_id']    = '1I-Sw3qBCDv3jHon7J_H3xgPU2-mJ8c-9E1h5DeVZUbk'
    defaults['range_name']  = 'webscale - knieco field eng!A2:J'
    defaults['fields']      =  ["case_account_name","case_summary","case_number","case_status","case_owner","case_severity","case_createdDate","case_lastModifiedDate","case_bugzillaNumber","case_description","case_tags"]
    defaults['query']       = "case_summary:*webscale* OR case_tags:*shift_telco5g* OR case_summary:*cnv,* OR case_tags:*cnv*"
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
    data = json.loads(data.decode("utf-8"))
    logging.warning("{} ....fetched".format(key))

    return data

def cache_cases(cfg):

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
    }
    # Sometimes there is no BZ attached to the case
    if "case_bugzillaNumber" in case:
        cases[case["case_number"]]["bug"] = case["case_bugzillaNumber"]
    # Sometimes there is no tag attached to the case
    if "case_tags" in case:
        cases[case["case_number"]]["tags"] = case["case_tags"]

  redis_set('cases', json.dumps(cases))

def cache_cards(cfg):

    logging.warning("fetching cases")
    cases = redis_get('cases')
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

    jira_cards = {}
    for card in card_list:
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
        tags = []
        if 'tags' in cases[case_number].keys():
            tags = cases[case_number]['tags']
        else: # assume telco
            tags = ['shift_telco5g']
        if 'bug' in cases[case_number].keys():
            bugzilla = cases[case_number]['bug']
        else:
            bugzilla = "None"
        jira_cards[card.key] = {
            "card_status": issue.fields.status.name,
            "account": cases[case_number]['account'],
            "summary": cases[case_number]['problem'],
            "description": cases[case_number]['description'],
            "comments": card_comments,
            "assignee": assignee,
            "case_number": case_number,
            "tags": tags,
            "labels": issue.fields.labels,
            "bugzilla": bugzilla,
            "severity": cases[case_number]['severity']
        }

    end = time.time()
    logging.warning("got {} cards in {} seconds".format(len(jira_cards), (end - start)))
    redis_set('cards', json.dumps(jira_cards))

def get_case_from_link(jira_conn, card):

    links = jira_conn.remote_links(card)
    for link in links:
        t = jira_conn.remote_link(card, link)
        if t.raw['object']['title'] == "Support Case":
            case_number = get_case_number(t.raw['object']['url'])
            if len(case_number) > 0:
                return case_number
    return None


def get_cases_json(token, query, fields, num_cases=5000, exclude_closed=True):
  # https://source.redhat.com/groups/public/hydra/hydra_integration_platform_cee_integration_wiki/hydras_api_layer
  fl = ",".join(fields)
  query = "({})".format(query)

  if exclude_closed:
      query = query + " AND -case_status:Closed"
  payload = {"q": query, "partnerSearch": "false", "rows": num_cases, "fl": fl}
  headers = {"Accept": "application/json", "Authorization": "Bearer " + token}
  url = "https://access.redhat.com/hydra/rest/search/cases"
  r = requests.get(url, headers=headers, params=payload)
  cases_json = r.json()['response']['docs']
  
  return cases_json


def get_cases(cases_json, include_tags=False):
  cases = {}
  for case in cases_json:
    #print(case)
    cases[case["case_number"]] = {
        "owner": case["case_owner"],
        "severity": case["case_severity"],
        "account": case["case_account_name"],
        "problem": case["case_summary"],
        "status": case["case_status"],
        "createdate": case["case_createdDate"],
        "last_update": case["case_lastModifiedDate"],
        "description": case["case_description"],
    }
    # Sometimes there is no BZ attached to the case
    if "case_bugzillaNumber" in case:
        cases[case["case_number"]]["bug"] = case["case_bugzillaNumber"]

    # Sometimes there is no tag attached to the case
    if "case_tags" in case and include_tags:
        cases[case["case_number"]]["tags"] = case["case_tags"]

  return cases

def main():
    print("libtelco5g")


if __name__ == '__main__':
    main()


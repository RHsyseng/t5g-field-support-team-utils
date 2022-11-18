"""utils.py: utility functions for the t5gweb"""

from datetime import date
from email.message import EmailMessage
import logging
import os
import re
import random
import smtplib
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def email_notify(ini, blist):
    ''' send an email to notify the team of a new case '''

    body = ''
    for line in blist:
        body += f"{line}\n"

    msg = EmailMessage()
    msg.set_content(body)

    msg['Subject'] = ini['subject']
    msg['From'] = ini['from']
    msg['to'] = ini['to']

    sendmail = smtplib.SMTP(ini['smtp'])
    sendmail.send_message(msg)
    sendmail.quit()

def exists_or_zero(data, key):
    ''' hack for when a new data point is added -> history does not exist'''
    if key in data.keys():
        return data[key]
    return 0

def get_previous_quarter():
    ''' Creates JIRA query to get cards from previous quarter '''
    day = date.today()
    if 1 <= day.month <= 3:
        query_range = f'((updated >= "{day.year-1}-10-01" AND updated <= "{day.year-1}-12-31")  \
                        OR (created >= "{day.year-1}-10-01" AND created <= "{day.year-1}-12-31"))'
    elif 4 <= day.month <= 6:
        query_range = f'((updated >= "{day.year}-1-01" AND updated <= "{day.year}-3-30") \
                        OR (created >= "{day.year}-1-01" AND created <= "{day.year}-3-30"))'
    elif 7 <= day.month <= 9:
        query_range = f'((updated >= "{day.year}-4-01" AND updated <= "{day.year}-6-30") \
                        OR (created >= "{day.year}-4-01" AND created <= "{day.year}-6-30"))'
    elif 10 <= day.month <= 12:
        query_range = f'((updated >= "{day.year}-7-01" AND updated <= "{day.year}-9-30") \
                        OR (created >= "{day.year}-7-01" AND created <= "{day.year}-9-30"))'
    return query_range

def get_random_member(team, last_choice=None): ##CIRCLE
    ''' Randomly pick a team member and avoid picking the same person twice in a row'''

    #last_choice = redis_get('last_choice') ##CIRCLE
    if len(team) > 1:
        if last_choice is not None:
            team = [member for member in team if member != last_choice]
        current_choice = random.choice(team)
    elif len(team) == 1:
        current_choice = team[0]
    else:
        logging.warning("No team variable is available, cannot assign case.")
        current_choice = None
    #redis_set('last_choice', json.dumps(current_choice)) ##CIRCLE

    return current_choice

def get_token(offline_token):
    ''' get a portal access token '''
    # https://access.redhat.com/articles/3626371
    data = {'grant_type': 'refresh_token', 'client_id': 'rhsm-api', 'refresh_token': offline_token}
    url = 'https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token'
    response = requests.post(url, data=data, timeout=5)
    # It returns 'application/x-www-form-urlencoded'
    token = response.json()['access_token']
    return token

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
    with open(file, encoding="utf-8") as filep:
        for line in filep:
            if not line.startswith("#") and not line.startswith(";"):
                cfg_pair = line.split(':', 1)
                key = cfg_pair[0].replace('\n', '').strip()

                if len(cfg_pair) > 1:
                    value = cfg_pair[1].replace('\n', '').strip()
                    cfg_dict[key] = value
                elif len(key) > 0:
                    cfg_dict[key] = True
    return cfg_dict

def read_env_config(keys):
    ''' read configuration values from OS environment variables '''
    ecfg = {}

    for key in keys:
        if 't5g_' + key in os.environ:
            ecfg[key] = os.environ.get('t5g_' + key)

    return ecfg

def set_cfg():
    ''' generate the working config '''
    # Set the default configuration values
    cfg = set_defaults()

    # Override the defaults and configuration file settings
    # with any environmental settings
    trcfg = read_env_config(cfg.keys())
    for key, value in trcfg.items():
        cfg[key] = value

    # Fix some of the settings so they are easier to use
    cfg['labels'] = cfg['labels'].split(',')

    cfg['offline_token'] = os.environ.get('offline_token')
    cfg['password'] = os.environ.get('jira_pass')
    cfg['bz_key'] = os.environ.get('bz_key')
    cfg['smartsheet_access_token'] = os.environ.get('smartsheet_access_token')
    cfg['sheet_id'] = os.environ.get('sheet_id')

    return cfg

def set_defaults():
    ''' set default configuration values '''
    defaults = {}
    defaults['smtp'] = 'smtp.corp.redhat.com'
    defaults['from'] = 't5g_jira@redhat.com'
    defaults['to'] = ''
    defaults['alert_to'] = 'dcritch@redhat.com'
    defaults['subject'] = 'New Card(s) Have Been Created to Track Telco5G Issues'
    defaults['sprintname'] = 'T5GFE'
    defaults['server'] = 'https://issues.redhat.com'
    defaults['project'] = 'KNIECO'
    defaults['component'] = 'KNI Labs & Field'
    defaults['board'] = 'KNI-ECO Labs & Field'
    defaults['email'] = ''
    defaults['type'] = 'Story'
    defaults['labels'] = 'field, no-qe, no-doc'
    defaults['priority'] = 'High'
    defaults['points'] = 3
    defaults['password'] = ''
    defaults['card_action'] = 'none'
    defaults['debug'] = 'False'
    defaults['fields'] = ["case_account_name", "case_summary", "case_number",
                          "case_status", "case_owner", "case_severity",
                          "case_createdDate", "case_lastModifiedDate",
                          "case_bugzillaNumber", "case_description", "case_tags",
                          "case_product", "case_version", "case_closedDate"]
    defaults['query'] = "case_summary:*webscale* OR case_tags:*shift_telco5g* OR case_tags:*cnv*"
    defaults['slack_token'] = ''
    defaults['slack_channel'] = ''
    defaults['max_jira_results'] = 1000
    defaults['max_portal_results'] = 5000
    return defaults

def slack_notify(ini, blist):
    ''' notify the team of new cases via slack '''
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
        try:
            message = client.chat_postMessage(channel = ini['slack_channel'], text = msgs[k])
            client.chat_postMessage(channel = ini['slack_channel'], text = msgs[k+1],
                                            thread_ts = message['ts'])
        except SlackApiError as slack_error:
            logging.warning("failed to post to slack: %s", slack_error)

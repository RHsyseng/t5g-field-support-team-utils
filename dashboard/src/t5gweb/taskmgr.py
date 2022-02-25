"""start celery and manage tasks"""
import logging
import time
import os
import json
import t5gweb.libtelco5g as libtelco5g
import t5gweb.t5gweb as t5gweb
from celery import Celery
from celery.schedules import crontab

mgr = Celery('t5gweb', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

#https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html#entries
@mgr.on_after_configure.connect
def setup_scheduled_tasks(sender, **kwargs):

    sender.add_periodic_task(
        crontab(hour='*', minute='15'),
        portal_jira_sync.s('telco5g'),
        name='telco5g_sync',
    )

    sender.add_periodic_task(
        crontab(hour='*', minute='30'),
        portal_jira_sync.s('cnv'),
        name='cnv_sync',
    )

@mgr.task
def portal_jira_sync(job_type):
    
    logging.warning("checking for new {} cases".format(job_type))
    cfg = t5gweb.set_cfg()
    max_to_create = os.environ.get('max_to_create')

    start = time.time()
    
    cases = libtelco5g.redis_get('cases')
    cards = libtelco5g.redis_get('cards')
    
    if job_type == 'telco5g':
        cfg['team'] = json.loads(os.environ.get('telco_team'))
        cfg['to'] = os.environ.get('telco_email')
        open_cases = [case for case in cases if cases[case]['status'] != 'Closed' and 'shift_telco5g' in cases[case]['tags']]
    elif job_type == 'cnv':
        open_cases = [case for case in cases if cases[case]['status'] != 'Closed' and 'cnv' in cases[case]['tags']]
        cfg['team'] = json.loads(os.environ.get('cnv_team'))
        cfg['to'] = os.environ.get('cnv_email')
        cfg['subject'] = 'New Card(s) Have Been Created to Track CNV Issues'
        cfg['labels'] = ['cnv', 'no-qe', 'no-doc']
    else:
        logging.warning("unknown team: {}".format(team))
        return None
    
    card_cases = [cards[card]['case_number'] for card in cards]
    new_cases = [case for case in open_cases if case not in card_cases]

    if len(new_cases) > int(max_to_create):
        email_content = "Warning: more than {} cases ({}) will be created, so refusing to proceed. Please check log output\n".format(max_to_create, len(new_cases))
        cfg['to'] = os.environ.get('alert_email')
        cfg['subject'] = 'High New Case Count Detected'
        libtelco5g.notify(cfg, email_content)
        
    logging.warning("need to create {} cases".format(len(new_cases)))

    if len(new_cases) > 0:
        message_content = libtelco5g.create_cards(cfg, new_cases, action='create')
        cfg['slack_token'] = os.environ.get('slack_token')
        cfg['slack_channel'] = os.environ.get('slack_channel')
        if message_content:
            logging.warning("notifying team about new JIRA cards")
            libtelco5g.notify(cfg, message_content)
            if cfg['slack_token'] and cfg['slack_channel']:
                libtelco5g.slack_notify(cfg, message_content)
            else:
                logging.warning("no slack token or channel specified")
            # refresh redis
            libtelco5g.cache_cards(cfg)
            
    end = time.time()
    logging.warning("synced to jira in {} seconds".format(end - start))

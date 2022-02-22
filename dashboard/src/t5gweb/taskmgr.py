"""start celery and manage tasks"""
import logging
import time
import t5gweb.libtelco5g as libtelco5g
from celery import Celery
from celery.schedules import crontab

mgr = Celery('t5gweb', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

#https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html#entries
@mgr.on_after_configure.connect
def setup_scheduled_tasks(sender, **kwargs):

    sender.add_periodic_task(
        crontab(minute='*/5'),
        portal_jira_sync.s('telco5g'),
        name='telco5g_sync',
    )
    
@mgr.task
def portal_jira_sync(team):
    
    cfg = libtelco5g.set_defaults()
    logging.warning("checking for new {} cases".format(team))
    cases = libtelco5g.redis_get('cases')
    cards = libtelco5g.redis_get('cards')
    if team == 'telco5g':
        open_cases = [case for case in cases if cases[case]['status'] != 'Closed' and 'shift_telco5g' in cases[case]['tags']]
    elif team == 'cnv':
        open_cases = [case for case in cases if cases[case]['status'] != 'Closed' and 'cnv' in cases[case]['tags']]
    else:
        logging.warning("unknown team: {}".format(team))
        return None
    
    card_cases = [cards[card]['case_number'] for card in cards]
    new_cases = [case for case in open_cases if case not in card_cases]
    logging.warning("need to create {} cases".format(len(new_cases)))

    
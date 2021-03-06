"""start celery and manage tasks"""
import logging
import time
import datetime
import os
import json
import t5gweb.libtelco5g as libtelco5g
import t5gweb.t5gweb as t5gweb
from celery import Celery
from celery.schedules import crontab
import bugzilla
import redis

mgr = Celery('t5gweb', broker='redis://redis:6379/0', backend='redis://redis:6379/0')

#https://docs.celeryproject.org/en/stable/userguide/periodic-tasks.html#entries
@mgr.on_after_configure.connect
def setup_scheduled_tasks(sender, **kwargs):

    # check for new telco cases
    sender.add_periodic_task(
        crontab(hour='*', minute='15'), # 15 mins after every hour
        portal_jira_sync.s('telco5g'),
        name='telco5g_sync',
    )

    # check for new cnv cases
    sender.add_periodic_task(
        crontab(hour='*', minute='30'), # 30 mins after every hour
        portal_jira_sync.s('cnv'),
        name='cnv_sync',
    )

    # update card cache
    sender.add_periodic_task(
        crontab(hour='*', minute='21'), # on the hour + offset
        cache_data.s('cards'),
        name='card_sync',
    )

    # update case cache
    sender.add_periodic_task(
        crontab(hour='*', minute='*/15'), # every 15 minutes
        cache_data.s('cases'),
        name='case_sync',
    )

    # update bugzilla/details cache
    sender.add_periodic_task(
        crontab(hour='*/12', minute='48'), # twice a day
        cache_data.s('details'),
        name='details_sync',
    )

    # update escalations cache
    sender.add_periodic_task(
        crontab(hour='*/12', minute='37'), # twice a day
        cache_data.s('escalations'),
        name='escalations_sync',
    )

    # tag bugzillas with 'Telco' and/or 'Telco:Case'
    sender.add_periodic_task(
        crontab(hour='*/24', minute='33'), # once a day + 33 for randomness
        tag_bz.s(),
        name='tag_bz',
    )
    
    # generate daily stats
    sender.add_periodic_task(
        crontab(hour='4', minute='11'), # every day at 4:11
        cache_stats.s(),
        name='cache_stats',
    )

    # update watchlist cache
    sender.add_periodic_task(
        crontab(hour='*/12', minute='7'), # twice a day + 7 mins
        cache_data.s('watchlist'),
        name='watchlist_sync',
    )

@mgr.task
def portal_jira_sync(job_type):
    
    logging.warning("job: checking for new {} cases".format(job_type))
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
        logging.warning("Warning: more than {} cases ({}) will be created, so refusing to proceed. Please check log output\n".format(max_to_create, len(new_cases)))
        email_content = ['Warning: more than {} cases ({}) will be created, so refusing to proceed. Please check log output\n"'.format(max_to_create, len(new_cases))]
        cfg['to'] = os.environ.get('alert_email')
        cfg['subject'] = 'High New Case Count Detected'
        libtelco5g.notify(cfg, email_content)
    elif len(new_cases) > 0:
        logging.warning("need to create {} cases".format(len(new_cases)))
        message_content, new_cards = libtelco5g.create_cards(cfg, new_cases, action='create')
        cfg['slack_token'] = os.environ.get('slack_token')
        cfg['slack_channel'] = os.environ.get('slack_channel')
        if message_content:
            logging.warning("notifying team about new JIRA cards")
            libtelco5g.notify(cfg, message_content)
            if cfg['slack_token'] and cfg['slack_channel']:
                libtelco5g.slack_notify(cfg, message_content)
            else:
                logging.warning("no slack token or channel specified")
            cards.update(new_cards)
            libtelco5g.redis_set('cards', json.dumps(cards))

    else:
        logging.warning("no new cards required")
            
    end = time.time()
    logging.warning("synced to jira in {} seconds".format(end - start))

@mgr.task(autoretry_for=(Exception,), max_retries=5, retry_backoff=30)
def cache_data(data_type):
    
    logging.warning("job: sync {}".format(data_type))

    cfg = t5gweb.set_cfg()

    if data_type == 'cases':
        libtelco5g.cache_cases(cfg)
    elif data_type == 'cards':
        # Use redis locks to prevent concurrent refreshes

        have_lock = False
        refresh_lock = redis.Redis(host='redis').lock("refresh_lock", timeout=60*5)
        try:
            have_lock = refresh_lock.acquire(blocking=False)
            if have_lock:
                libtelco5g.cache_cards(cfg)
        finally:
            if have_lock:
                refresh_lock.release()
    elif data_type == 'details':
        libtelco5g.cache_details(cfg)
    elif data_type == 'escalations':
        libtelco5g.cache_escalations(cfg)
    elif data_type == 'watchlist':
        libtelco5g.cache_watchlist(cfg)
    else:
        logging.warning("unknown data type")

@mgr.task
def tag_bz():
    
    logging.warning("getting bugzillas")
    bz_url = "bugzilla.redhat.com"
    cfg = t5gweb.set_cfg()
    bz_api = bugzilla.Bugzilla(bz_url, api_key=cfg['bz_key'])
    cases = libtelco5g.redis_get("cases")
    telco_cases = [case for case in cases if "shift_telco5g" in cases[case]['tags']]
    bugs = libtelco5g.redis_get('bugs')
    logging.warning("tagging bugzillas")
    for case in bugs:
        if case in telco_cases:
            for bug in bugs[case]:
                try:
                    bz = bz_api.getbug(bug['bugzillaNumber'])
                except:
                    logging.warning("error: {} is restricted".format(bug['bugzillaNumber']))
                    bz = None
                if bz:
                    if "telco" not in bz.internal_whiteboard.lower():
                        update = bz_api.build_update(internal_whiteboard="Telco Telco:Case " + bz.internal_whiteboard, minor_update=True)
                        logging.warning("tagging BZ:" + str(bz.id))
                        bz_api.update_bugs([bz.id], update)
                    elif "telco:case" not in bz.internal_whiteboard.lower():
                        update = bz_api.build_update(internal_whiteboard=bz.internal_whiteboard + " Telco:Case", minor_update=True)
                        logging.warning("tagging BZ:" + str(bz.id))
                        bz_api.update_bugs([bz.id], update)

@mgr.task
def cache_stats():

    for case_type in ['telco5g', 'cnv']:
        logging.warning("job: cache {} stats".format(case_type))
        libtelco5g.cache_stats(case_type)

@mgr.task(bind=True)
def refresh_background(self):
    '''Refresh Jira cards cache in background. If the refresh is already in progress, the task will be locked and won't run.
    The lock is released when the task completes or after five minutes.
    Lock code derived from http://loose-bits.com/2010/10/distributed-task-locking-in-celery.html
    '''

    have_lock = False
    refresh_lock = redis.Redis(host='redis').lock("refresh_lock", timeout=60*5)
    try:
        have_lock = refresh_lock.acquire(blocking=False)
        if have_lock:
            libtelco5g.redis_set('refresh_id', json.dumps(self.request.id))
            cfg = t5gweb.set_cfg()
            libtelco5g.cache_cards(cfg, self, background=True)
            response = {'current': 100, 'total': 100, 'status': 'Done', 'result': 'Refresh Complete'}
        else:
            response = {'locked': 'Task is Locked'}
    finally:
        if have_lock:
            refresh_lock.release()
    return response
"""core CRUD functions for t5gweb"""
import logging
import os
import jira
import click
from flask.cli import with_appcontext
from datetime import datetime, timezone, date
import pkg_resources
import re
from werkzeug.exceptions import abort
from . import libtelco5g
import json
import sys
from copy import deepcopy
from t5gweb.utils import set_cfg

def get_new_cases(case_tag):
    """get new cases created since X days ago"""

    # get cases from cache
    cases = libtelco5g.redis_get("cases")

    interval = 7
    today = date.today()
    new_cases = {c: d for (c, d) in sorted(cases.items(), key = lambda i: i[1]['severity']) if case_tag in d['tags'] and (today - datetime.strptime(d['createdate'], '%Y-%m-%dT%H:%M:%SZ').date()).days <= interval}
    for case in new_cases:
        new_cases[case]['severity'] = re.sub('\(|\)| |[0-9]', '', new_cases[case]['severity'])
    return new_cases

def get_new_comments(new_comments_only=True):

    # fetch cards from redis cache
    cards = libtelco5g.redis_get('cards')
    logging.warning("found %d JIRA cards" % (len(cards)))
    time_now = datetime.now(timezone.utc)

    # filter cards for comments created in the last week
    # and sort between telco and cnv
    detailed_cards= {}
    telco_account_list = []
    cnv_account_list = []
    for card in cards:
        comments = []
        if new_comments_only:
            if cards[card]['comments'] is not None:
                comments = [comment for comment in cards[card]['comments'] if (time_now - datetime.strptime(comment[1], '%Y-%m-%dT%H:%M:%S.%f%z')).days < 7]
        else:
            if cards[card]['comments'] is not None:
                comments = [comment for comment in cards[card]['comments']]
        if len(comments) == 0:
            #logging.warning("no recent updates for {}".format(card))
            continue # no updates
        else:
            detailed_cards[card] = cards[card]
            detailed_cards[card]['comments'] = comments
        if "shift_telco5g" in cards[card]['tags'] and cards[card]['account'] not in telco_account_list:
            telco_account_list.append(cards[card]['account'])
        if "cnv" in cards[card]['tags'] and cards[card]['account'] not in cnv_account_list:
            cnv_account_list.append(cards[card]['account'])
    telco_account_list.sort()
    cnv_account_list.sort()
    logging.warning("found %d detailed cards" % (len(detailed_cards)))

    # organize cards by status
    telco_accounts, cnv_accounts = organize_cards(detailed_cards, telco_account_list, cnv_account_list)
    return telco_accounts, cnv_accounts

def get_trending_cards():

    # fetch cards from redis cache
    cards = libtelco5g.redis_get('cards')
    time_now = datetime.now(timezone.utc)

    # get a list of trending cards
    trending_cards = [card for card in cards if 'Trends' in cards[card]['labels']]

    #TODO: timeframe?
    detailed_cards = {}
    telco_account_list = []
    for card in trending_cards:
        detailed_cards[card] = cards[card]
        account = cards[card]['account']
        if account not in telco_account_list:
            telco_account_list.append(cards[card]['account'])

    telco_accounts, cnv_accounts = organize_cards(detailed_cards, telco_account_list)
    return telco_accounts
    

def plots():

    summary = libtelco5g.get_card_summary()
    return summary

def organize_cards(detailed_cards, telco_account_list, cnv_account_list=None):
    """Group cards by account"""
    
    telco_accounts = {}
    cnv_accounts = {}

    states = {"Waiting on Red Hat":{}, "Waiting on Customer": {}, "Closed": {}}
    
    for account in telco_account_list:
        telco_accounts[account] = deepcopy(states)
    if cnv_account_list:
        for account in cnv_account_list:
            cnv_accounts[account] = deepcopy(states)
    
    for i in detailed_cards.keys():
        status = detailed_cards[i]['case_status']
        tags =  detailed_cards[i]['tags']
        account = detailed_cards[i]['account']
        #logging.warning("card: %s\tstatus: %s\ttags: %s\taccount: %s" % (i, status, tags, account))
        if "shift_telco5g" in tags:
            telco_accounts[account][status][i] = detailed_cards[i]
        if cnv_account_list and "cnv" in tags:
            cnv_accounts[account][status][i] = detailed_cards[i]
  
    return telco_accounts, cnv_accounts

@click.command('init-cache')
@with_appcontext
def init_cache():
    cfg = set_cfg()
    logging.warning("checking caches")
    cases = libtelco5g.redis_get('cases')
    cards = libtelco5g.redis_get('cards')
    bugs = libtelco5g.redis_get('bugs')
    details = libtelco5g.redis_get('details')
    escalations = libtelco5g.redis_get('escalations')
    watchlist = libtelco5g.redis_get('watchlist')
    t5g_stats = libtelco5g.redis_get('telco5g_stats')
    cnv_stats = libtelco5g.redis_get('cnv_stats')
    if cases == {}:
        logging.warning("no cases found in cache. refreshing...")
        libtelco5g.cache_cases(cfg)
    if bugs == {} or details == {}:
        logging.warning("no details found in cache. refreshing...")
        libtelco5g.cache_details(cfg)
    if escalations == {}:
        logging.warning("no escalations found in cache. refreshing...")
        libtelco5g.cache_escalations(cfg)
    if watchlist == {}:
        logging.warning("no watchlist found in cache. refreshing...")
        libtelco5g.cache_watchlist(cfg)
    if cards == {}:
        logging.warning("no cards found in cache. refreshing...")
        libtelco5g.cache_cards(cfg)
    if t5g_stats == {}:
        logging.warning("no t5g stats found in cache. refreshing...")
        libtelco5g.cache_stats('telco5g')
    if cnv_stats == {}:
        logging.warning("no cnv stats found in cache. refreshing...")
        libtelco5g.cache_stats('cnv')


def init_app(app):
    app.cli.add_command(init_cache)

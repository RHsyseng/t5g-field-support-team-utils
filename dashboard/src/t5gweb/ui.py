"""UI views for t5gweb"""
import logging
import datetime

from flask import (
    Blueprint, redirect, render_template, request, url_for, make_response, send_file
)
from . import scheduler
from t5gweb.t5gweb import (
    get_new_cases,
    get_new_comments,
    get_trending_cards,
    plots,
    set_cfg
)
from t5gweb.libtelco5g import(
    cache_cases,
    cache_cards,
    cache_bz
)

BP = Blueprint('ui', __name__, url_prefix='/')

@scheduler.task('interval', id='do_job_1', seconds=3600)
def load_data():
    """Load data for dashboard in background every 1 hr"""
    cfg = set_cfg()

    # update redis cache
    cache_cases(cfg)
    cache_cards(cfg)

    # update page views
    load_data.new_cases = get_new_cases()
    plot_data = plots()
    load_data.y = list(plot_data.values())
    telco_accounts, cnv_accounts = get_new_comments()
    load_data.telco_comments = telco_accounts
    load_data.cnv_comments = cnv_accounts
    telco_accounts_all, cnv_accounts_all = get_new_comments(new_comments_only=False)
    load_data.telco_comments_all = telco_accounts_all
    load_data.cnv_comments_all = cnv_accounts_all
    load_data.trending_cards = get_trending_cards()
    load_data.now = datetime.datetime.utcnow()

@scheduler.task('interval', id="do_job_2", seconds=86400)
def load_bz_data():
    cfg = set_cfg()
    cache_cases(cfg, get_bz=True)

@BP.route('/')
def index():
    """list new cases"""
    return render_template('ui/index.html', new_cases=load_data.new_cases, values=load_data.y, now=load_data.now)

@BP.route('/refresh')
def refresh():
    """Forces an update to the dashboard"""
    load_data()
    return redirect(url_for("ui.telco5g"))

@BP.route('/telco5g')
def telco5g():
    """Retrieves cards that have been updated within the last week and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.telco_comments, page_title='telco5g')

@BP.route('/all_telco5g')
def all_telco5g():
    """Retrieves all cards and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.telco_comments_all, page_title='all-telco5g')

@BP.route('/cnv')
def cnv():
    """Retrieves cards that have been updated within the last week and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.cnv_comments, page_title='cnv')

@BP.route('/all_cnv')
def all_cnv():
    """Retrieves all cards and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.cnv_comments_all, page_title='all-cnv')

@BP.route('/trends')
def trends():
    """Retrieves cards that have been labeled with 'Trends' within the previous quarter and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.trending_cards, page_title='trends')

@BP.route('/cache')
def refresh_cache():
    cfg = set_cfg()
    cache_cases(cfg)
    cache_cards(cfg)
    return render_template('ui/index.html', new_cases=load_data.new_cases, values=load_data.y, now=load_data.now)


# Start scheduler and load data for first run
scheduler.start()
load_bz_data()
load_data()

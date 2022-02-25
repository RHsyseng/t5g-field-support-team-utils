"""UI views for t5gweb"""
import logging
import datetime
from flask import (
    Blueprint, redirect, render_template, request, url_for, make_response, send_file
)
from t5gweb.t5gweb import (
    get_new_cases,
    get_new_comments,
    get_trending_cards,
    plots,
    cache_page_data,
    set_cfg
)
from t5gweb.libtelco5g import(
    cache_cases,
    cache_cards,
    cache_bz,
    redis_get
)

#import t5gweb.taskmgr

BP = Blueprint('ui', __name__, url_prefix='/')

@BP.route('/')
def index():
    """list new cases"""
    load_data = redis_get('page_data')
    return render_template('ui/index.html', new_cases=load_data.new_cases, values=load_data.y, now=load_data.now)

@BP.route('/refresh')
def refresh():
    """Forces an update to the dashboard"""
    cache_cards()
    cache_page_data()
    return redirect(url_for("ui.telco5g"))

@BP.route('/telco5g')
def telco5g():
    """Retrieves cards that have been updated within the last week and creates report"""
    load_data = redis_get('page_data')
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.telco_comments, page_title='telco5g')

@BP.route('/all_telco5g')
def all_telco5g():
    """Retrieves all cards and creates report"""
    load_data = redis_get('page_data')
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.telco_comments_all, page_title='all-telco5g')

@BP.route('/cnv')
def cnv():
    """Retrieves cards that have been updated within the last week and creates report"""
    load_data = redis_get('page_data')
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.cnv_comments, page_title='cnv')

@BP.route('/all_cnv')
def all_cnv():
    """Retrieves all cards and creates report"""
    load_data = redis_get('page_data')
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.cnv_comments_all, page_title='all-cnv')

@BP.route('/trends')
def trends():
    """Retrieves cards that have been labeled with 'Trends' within the previous quarter and creates report"""
    load_data = redis_get('page_data')
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.trending_cards, page_title='trends')
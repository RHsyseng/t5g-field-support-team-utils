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
    plots
)

BP = Blueprint('ui', __name__, url_prefix='/')

@scheduler.task('interval', id='do_job_1', seconds=3600)
def load_data():
    """Load data for dashboard in background every 1 hr"""
    load_data.new_cases = get_new_cases()
    plot_data = plots()
    load_data.y = list(plot_data.values())
    telco_accounts, cnv_accounts = get_new_comments()
    load_data.telco_comments = telco_accounts
    load_data.cnv_comments = cnv_accounts
    load_data.trending_cards = get_trending_cards()
    load_data.now = datetime.datetime.utcnow()

@BP.route('/')
def index():
    """list new cases"""
    return render_template('ui/index.html', new_cases=load_data.new_cases, values=load_data.y, now=load_data.now)

@BP.route('/refresh')
def refresh():
    """Forces an update to the dashboard"""
    load_data()
    return redirect(url_for("ui.updates"))

@BP.route('/telco5g')
def telco5g():
    """Retrieves cards that have been updated within the last week and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.telco_comments, page_title='telco5g')

@BP.route('/cnv')
def cnv():
    """Retrieves cards that have been updated within the last week and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.cnv_comments, page_title='cnv')

@BP.route('/trends')
def trends():
    """Retrieves cards that have been labeled with 'Trends' within the previous quarter and creates report"""
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.trending_cards, page_title='trends')

# Start scheduler and load data for first run
scheduler.start()
load_data()

"""UI views for t5gweb"""
import logging
import datetime
from flask import (
    Blueprint, redirect, render_template, request, url_for, make_response, send_file
)
from . import scheduler#, cache
from t5gweb.t5gweb import (
    get_new_cases,
    get_new_comments,
    # get_cnv,
    plots
)

BP = Blueprint('ui', __name__, url_prefix='/')

@scheduler.task('interval', id='do_job_1', seconds=600)
def load_data():
    """Load data for dashboard in background every 10 minutes"""
    load_data.new_cases = get_new_cases()
    plot_data = plots()
    load_data.y = list(plot_data.values())
    load_data.new_comments = get_new_comments()
    load_data.now = datetime.datetime.utcnow()


@BP.route('/')
# @cache.cached(timeout=14400)
def index():
    """list new cases"""
    # new_cases = get_new_cases()
    # plot_data = plots()
    # y = list(plot_data.values())
    # now = datetime.datetime.utcnow()
    return render_template('ui/index.html', new_cases=load_data.new_cases, values=load_data.y, now=load_data.now)


@BP.route('/refresh')
def refresh():
    """Forces an update to the dashboard"""
    # cache.clear()
    return redirect(url_for("ui.updates"))


@BP.route('/updates')
# @cache.cached(timeout=14400)
def updates():
    """Retrieves summary data and creates Chart.JS plot"""
    # new_comments = get_new_comments()
    # new_cnv = get_cnv()
    # now = datetime.datetime.utcnow()
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.new_comments)#, new_cnv=new_cnv)

# Start scheduler and load data for first run
scheduler.start()
load_data()

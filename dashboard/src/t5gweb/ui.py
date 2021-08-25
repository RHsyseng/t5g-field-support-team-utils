"""UI views for t5gweb"""
import logging
import datetime
from flask import (
    Blueprint, redirect, render_template, request, url_for, make_response, send_file
)
from . import cache
from t5gweb.t5gweb import (
    get_new_cases,
    get_new_comments,
    get_cnv,
    plots
)

BP = Blueprint('ui', __name__, url_prefix='/')

@BP.route('/')
@cache.cached(timeout=14400)
def index():
    """list new cases"""
    new_cases = get_new_cases()
    now = datetime.datetime.utcnow()
    new_comments = get_new_comments()
    new_cnv = get_cnv()
    return render_template('ui/index.html', new_cases=new_cases, now=now, new_comments=new_comments, new_cnv = new_cnv)

@BP.route('/refresh')
def refresh():
    """Forces an update to the dashboard"""
    cache.clear()
    return redirect(url_for("ui.index"))

@BP.route('/plots')
def plot():
    """Retrieves summary data and creates Chart.JS plot"""
    plot_data = plots()
    y = list(plot_data.values())
    return render_template('ui/plot.html', values = y)
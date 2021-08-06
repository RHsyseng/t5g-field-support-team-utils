"""UI views for t5gweb"""
import logging
import datetime
from flask import (
    Blueprint, redirect, render_template, request, url_for, make_response, send_file
)
from . import cache
from t5gweb.t5gweb import (
    get_new_cases,
    get_new_comments
)

BP = Blueprint('ui', __name__, url_prefix='/')

@BP.route('/')
@cache.cached(timeout=14400)
def index():
    """list new cases"""
    new_cases = get_new_cases()
    now = datetime.datetime.utcnow()
    new_comments = get_new_comments()
    return render_template('ui/index.html', new_cases=new_cases, now=now, new_comments=new_comments)

@BP.route('/live')
def live():
    """Forces an update to the dashboard"""
    cache.clear()
    return redirect(url_for("ui.index"))
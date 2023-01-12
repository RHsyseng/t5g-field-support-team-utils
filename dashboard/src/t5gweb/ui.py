"""UI views for t5gweb"""
import logging
import datetime
from flask import (
    Blueprint, jsonify, redirect, render_template, request, url_for, make_response, send_file, request
)
from t5gweb.taskmgr import refresh_background
from t5gweb.t5gweb import (
    get_new_cases,
    get_new_comments,
    get_trending_cards,
    plots
)
from t5gweb.libtelco5g import(
    redis_get,
    generate_stats,
    plot_stats
)
from t5gweb.utils import (
    set_cfg
)

BP = Blueprint('ui', __name__, url_prefix='/')

def load_data():
    """Load data for dashboard"""
    
    cfg = set_cfg()
    load_data.new_cases = get_new_cases()
    plot_data = plots()
    load_data.y = list(plot_data.values())
    load_data.accounts = get_new_comments()
    load_data.accounts_all = get_new_comments(new_comments_only=False)
    load_data.trending_cards = get_trending_cards()
    load_data.now = redis_get('timestamp')
    load_data.jira_server = cfg['server']


## deprecated endpoints to remove
@BP.route('/updates/telco5g')
@BP.route('/updates/telco5g/all')
@BP.route('/updates/cnv')
@BP.route('/updates/cnv/all')
@BP.route('/updates/telco5g/severity')
@BP.route('/updates/telco5g/all/severity')
@BP.route('/updates/cnv/severity')
@BP.route('/updates/cnv/all/severity')
@BP.route('/stats/cnv')
@BP.route('/stats/telco5g')
## end of deprecated routes
@BP.route('/')
def index():
    """list new cases"""
    load_data()
    return render_template('ui/index.html', new_cases=load_data.new_cases, values=load_data.y, now=load_data.now)

@BP.route('/progress/status', methods=['POST'])
def progress_status():
    """On page load: if refresh is in progress, get task information for progress bar display"""
    refresh_id = redis_get('refresh_id')
    if refresh_id != {}:
        return jsonify({}), 202, {'Location': url_for('ui.refresh_status', task_id=refresh_id)}
    else:
        return jsonify({})

@BP.route('/status/<task_id>')
def refresh_status(task_id):
    """Provide updates for refresh_background task"""
    task = refresh_background.AsyncResult(task_id)
    if task.state == 'PENDING':
        # job did not start yet
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
        if 'locked' in task.info:
            response['locked'] = task.info['locked']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info) # this is the exception raised
        }
    return jsonify(response)

@BP.route('/refresh', methods=['POST'])
def refresh():
    """Forces an update to the dashboard"""
    task = refresh_background.delay()
    load_data()
    return jsonify({}), 202, {'Location': url_for('ui.refresh_status', task_id=task.id)}


@BP.route('/updates/')
def report_view():
    """Retrieves cards that have been updated within the last week and creates report"""
    load_data()
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.accounts, jira_server=load_data.jira_server, page_title='recent updates')

@BP.route('/updates/all')
def report_view_all():
    """Retrieves all cards and creates report"""
    load_data()
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.accounts_all, jira_server=load_data.jira_server, page_title='all cards')

@BP.route('/trends/')
def trends():
    """Retrieves cards that have been labeled with 'Trends' within the previous quarter and creates report"""
    load_data()
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.trending_cards, jira_server=load_data.jira_server, page_title='trends')

@BP.route('/table/')
def table_view():
    """Sorts new cards by severity and creates table"""
    load_data()
    return render_template('ui/table.html', now=load_data.now, new_comments=load_data.accounts, jira_server=load_data.jira_server, page_title='severity')

@BP.route('/table/all')
def table_view_all():
    """Sorts all cards by severity and creates table"""
    load_data()
    return render_template('ui/table.html', now=load_data.now, new_comments=load_data.accounts_all, jira_server=load_data.jira_server, page_title='all-severity')

@BP.route('/weekly/')
def weekly_updates():
    """Retrieves cards and displays them plainly for easy copy/pasting and distribution"""
    load_data()
    return render_template('ui/weekly_report.html', now=load_data.now, new_comments=load_data.accounts, jira_server=load_data.jira_server, page_title='weekly-update')

@BP.route('/stats')
def get_stats():
    """ generate some stats"""
    load_data()
    stats = generate_stats()
    x_values, y_values = plot_stats()
    return render_template('ui/stats.html', now=load_data.now, stats=stats, x_values=x_values, y_values=y_values, page_title='stats')
    
@BP.route('/account/<string:account>')
def get_account(account):
    '''show bugs, cases and stats by for a given account'''
    load_data()
    stats = generate_stats(account)
    comments = get_new_comments(new_comments_only=False, account=account)

    pie_stats = {
        "by_severity": (
            list(stats["by_severity"].keys()),
            list(stats["by_severity"].values()),
        ),
        "by_status": (
            list(stats["by_status"].keys()),
            list(stats["by_status"].values()),
        ),
    }
    return render_template('ui/account.html', page_title=account, account=account, now=load_data.now, stats=stats, new_comments=comments, jira_server=load_data.jira_server, pie_stats=pie_stats)


"""UI views for t5gweb"""
# The login code was derived from https://github.com/SAML-Toolkits/python3-saml/tree/master/demo-flask
# License - https://github.com/SAML-Toolkits/python3-saml/blob/master/LICENSE
import os
import json
from flask import (
    Blueprint, jsonify, redirect, render_template, request, url_for, make_response, session, request, abort
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
    redis_set,
    generate_stats,
    plot_stats,
    generate_histogram_stats
)
from t5gweb.utils import (
    set_cfg
)

from urllib.parse import urlparse, urljoin
from flask_login import LoginManager, UserMixin, login_user, login_required
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.utils import OneLogin_Saml2_Utils

BP = Blueprint('ui', __name__, url_prefix='/')
login_manager=LoginManager()
login_manager.login_view = 'ui.login'
users = redis_get('users')

class User(UserMixin):
    def __init__(self, user_id):
        user = users[user_id]
        self.id = user_id
        self.given_name = user['givenName'][0]
        self.mail = user['mail'][0]

def is_safe_url(target):
    '''From https://flask-login.readthedocs.io/en/latest/#login-example, prevents Open Redirects'''
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc

@login_manager.user_loader
def load_user(user_id):
    '''https://flask-login.readthedocs.io/en/latest/#how-it-works'''
    if user_id in users:
        return User(user_id)
    return None

def init_saml_auth(req):
    '''Load user-configured settings into SAML package'''
    settings = json.loads(os.environ.get('saml_settings'))
    auth = OneLogin_Saml2_Auth(req, settings)
    return auth


def prepare_flask_request(request):
    # If server is behind proxys or balancers use the HTTP_X_FORWARDED fields
    return {
        'https': 'on',
        'http_host': request.host,
        'script_name': request.path,
        'get_data': request.args.copy(),
        # Uncomment if using ADFS as IdP, https://github.com/onelogin/python-saml/pull/144
        # 'lowercase_urlencoding': True,
        'post_data': request.form.copy()
    }

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

@BP.route('/', methods=['GET', 'POST'])
def login():
    '''Handles redirects back and forth from SAML Provider and user creation in Redis'''
    req = prepare_flask_request(request)
    auth = init_saml_auth(req)
    errors = []
    error_reason = None
    not_auth_warn = False
    attributes = False
    wrong_permissions=False
    alert_email=None

    if 'sso' in request.args:
        return redirect(auth.login())
    elif 'acs' in request.args:
        request_id = None
        if 'AuthNRequestID' in session:
            request_id = session['AuthNRequestID']

        auth.process_response(request_id=request_id)
        errors = auth.get_errors()
        not_auth_warn = not auth.is_authenticated()
        if len(errors) == 0:
            if 'AuthNRequestID' in session:
                del session['AuthNRequestID']
            session['samlUserdata'] = auth.get_attributes()
            session['samlNameId'] = auth.get_nameid()
            session['samlNameIdFormat'] = auth.get_nameid_format()
            session['samlNameIdNameQualifier'] = auth.get_nameid_nq()
            session['samlNameIdSPNameQualifier'] = auth.get_nameid_spnq()
            session['samlSessionIndex'] = auth.get_session_index()
            self_url = OneLogin_Saml2_Utils.get_self_url(req)
            if 'RelayState' in request.form and self_url != request.form['RelayState']:
                # To avoid 'Open Redirect' attacks, before execute the redirection confirm
                # the value of the request.form['RelayState'] is a trusted URL.
                if not is_safe_url(request.form['RelayState']):
                    abort(400)
                return redirect(auth.redirect_to(request.form['RelayState']))
        elif auth.get_settings().is_debug_active():
            error_reason = auth.get_last_error_reason()
    if 'samlUserdata' in session:
        if len(session['samlUserdata']) > 0:
            cfg = set_cfg()
            attributes = session['samlUserdata']
            groups = ",".join(attributes['memberOf'])
            #RBAC
            if cfg['rbac'] not in groups:
                    wrong_permissions = True
                    return render_template(
                        'ui/login.html',
                        errors=errors,
                        error_reason=error_reason,
                        not_auth_warn=not_auth_warn,
                        wrong_permissions=wrong_permissions,
                        alert_email=cfg['alert_to']
                    )
        #JIT Provisioning
        if attributes['rhatUUID'][0] not in users:
            new_user = {attributes['rhatUUID'][0]: {attribute_name:attribute_value for (attribute_name,attribute_value) in attributes.items()}}
            users.update(new_user)
            redis_set('users',json.dumps(users))

        user = User(attributes['rhatUUID'][0])
        login_user(user)
        next = request.args.get('next')

        # Avoid 'Open Redirect'
        if not is_safe_url(next):
            return abort(400)
        return redirect(next or url_for('ui.index'))


    return render_template(
        'ui/login.html',
        errors=errors,
        error_reason=error_reason,
        not_auth_warn=not_auth_warn,
        wrong_permissions=wrong_permissions
    )

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
@BP.route('/home')
# @login_required
def index():
    """list new cases"""
    load_data()
    return render_template('ui/index.html', new_cases=load_data.new_cases, values=load_data.y, now=load_data.now)

@BP.route('/progress/status', methods=['POST'])
# @login_required
def progress_status():
    """On page load: if refresh is in progress, get task information for progress bar display"""
    refresh_id = redis_get('refresh_id')
    if refresh_id != {}:
        return jsonify({}), 202, {'Location': url_for('ui.refresh_status', task_id=refresh_id)}
    else:
        return jsonify({})

@BP.route('/status/<task_id>')
# @login_required
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
# @login_required
def refresh():
    """Forces an update to the dashboard"""
    task = refresh_background.delay()
    load_data()
    return jsonify({}), 202, {'Location': url_for('ui.refresh_status', task_id=task.id)}


@BP.route('/updates/')
# @login_required
def report_view():
    """Retrieves cards that have been updated within the last week and creates report"""
    load_data()
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.accounts, jira_server=load_data.jira_server, page_title='recent updates')

@BP.route('/updates/all')
# @login_required
def report_view_all():
    """Retrieves all cards and creates report"""
    load_data()
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.accounts_all, jira_server=load_data.jira_server, page_title='all cards')

@BP.route('/trends/')
# @login_required
def trends():
    """Retrieves cards that have been labeled with 'Trends' within the previous quarter and creates report"""
    load_data()
    return render_template('ui/updates.html', now=load_data.now, new_comments=load_data.trending_cards, jira_server=load_data.jira_server, page_title='trends')

@BP.route('/table/')
# @login_required
def table_view():
    """Sorts new cards by severity and creates table"""
    load_data()
    return render_template('ui/table.html', now=load_data.now, new_comments=load_data.accounts, jira_server=load_data.jira_server, page_title='severity')

@BP.route('/table/all')
# @login_required
def table_view_all():
    """Sorts all cards by severity and creates table"""
    load_data()
    return render_template('ui/table.html', now=load_data.now, new_comments=load_data.accounts_all, jira_server=load_data.jira_server, page_title='all-severity')

@BP.route('/weekly/')
# @login_required
def weekly_updates():
    """Retrieves cards and displays them plainly for easy copy/pasting and distribution"""
    load_data()
    return render_template('ui/weekly_report.html', now=load_data.now, new_comments=load_data.accounts, jira_server=load_data.jira_server, page_title='weekly-update')

@BP.route('/stats')
@login_required
def get_stats():
    """ generate some stats"""
    load_data()
    stats = generate_stats()
    x_values, y_values = plot_stats()
    histogram_stats = generate_histogram_stats()
    return render_template('ui/stats.html', now=load_data.now, stats=stats, x_values=x_values, y_values=y_values, histogram_stats=histogram_stats,page_title='stats')
    
@BP.route('/account/<string:account>')
# @login_required
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

    histogram_stats = generate_histogram_stats(account)
    return render_template('ui/account.html', page_title=account, account=account, now=load_data.now, stats=stats, new_comments=comments, jira_server=load_data.jira_server, pie_stats=pie_stats, histogram_stats=histogram_stats)


"""UI views for t5gweb"""

# The login code was derived from:
# https://github.com/SAML-Toolkits/python3-saml/tree/master/demo-flask
# License - https://github.com/SAML-Toolkits/python3-saml/blob/master/LICENSE
import json
import logging
import os
from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import LoginManager, UserMixin, login_required, login_user
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from t5gweb.libtelco5g import (
    generate_histogram_stats,
    generate_stats,
    plot_stats,
    redis_get,
    redis_set,
)
from t5gweb.t5gweb import get_new_cases, get_new_comments, get_trending_cards, plots
from t5gweb.taskmgr import refresh_background
from t5gweb.utils import make_pie_dict, set_cfg

BP = Blueprint("ui", __name__, url_prefix="/")
login_manager = LoginManager()
login_manager.login_view = "ui.login"
users = redis_get("users")


class User(UserMixin):
    """Flask-Login user class for authentication
    
    Extends UserMixin to provide user authentication functionality. User data
    is retrieved from Redis cache based on the user's rhatUUID.
    
    Args:
        user_id: The rhatUUID of the user to load from cache
    """
    def __init__(self, user_id):
        user = users[user_id]
        self.id = user_id
        self.given_name = user["givenName"][0]
        self.mail = user["mail"][0]


def is_safe_url(target):
    """Validate that a redirect URL is safe to prevent Open Redirect attacks
    
    Checks that the target URL uses http/https scheme and matches the current
    host to prevent malicious redirects. Implementation from Flask-Login
    documentation: https://flask-login.readthedocs.io/en/latest/#login-example
    
    Args:
        target: Target URL to validate for redirection
        
    Returns:
        bool: True if URL is safe to redirect to, False otherwise
    """
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login callback to reload user from user ID in session
    
    Required callback for Flask-Login to load a user from the user ID stored
    in the session. See: https://flask-login.readthedocs.io/en/latest/#how-it-works
    
    Args:
        user_id: User identifier (rhatUUID) stored in the session
        
    Returns:
        User: User object if user exists in cache, None otherwise
    """
    if user_id in users:
        return User(user_id)
    return None


def init_saml_auth(req):
    """Initialize SAML authentication with configured settings
    
    Loads SAML settings from environment variable and creates a SAML
    authentication object for handling SSO authentication flow.
    
    Args:
        req: Prepared request dictionary containing HTTP request data
        
    Returns:
        OneLogin_Saml2_Auth: Initialized SAML authentication object
    """
    settings = json.loads(os.environ.get("saml_settings"))
    auth = OneLogin_Saml2_Auth(req, settings)
    return auth


def prepare_flask_request(request):
    """Prepare Flask request data for SAML authentication
    
    Converts Flask request object into a dictionary format required by the
    OneLogin SAML library. Handles proxy/load balancer scenarios using
    HTTP_X_FORWARDED fields.
    
    Args:
        request: Flask request object
        
    Returns:
        dict: Request data dictionary with https, http_host, script_name,
            get_data, and post_data keys
    """
    # If server is behind proxys or balancers use the HTTP_X_FORWARDED fields
    return {
        "https": "on",
        "http_host": request.host,
        "script_name": request.path,
        "get_data": request.args.copy(),
        "post_data": request.form.copy(),
    }


@BP.route("/", methods=["GET", "POST"])
def login():
    """Handle SAML SSO authentication flow and user provisioning
    
    Manages the complete SAML authentication process including:
    - Initiating SSO login flow
    - Processing SAML responses from identity provider
    - Validating user group membership (RBAC)
    - Just-In-Time (JIT) user provisioning in Redis
    - Session management and safe redirects
    
    Can be disabled by setting FLASK_LOGIN_DISABLED=true environment variable.
    
    Query Parameters:
        sso: Initiates SSO redirect to identity provider
        acs: Assertion Consumer Service - processes SAML response
        next: Optional URL to redirect to after successful login
        
    Returns:
        Response: Redirect to index on successful auth, login page template
            on failure or for initial request
    """
    # Anything except for 'true' will be set to False
    login_disabled = os.getenv("FLASK_LOGIN_DISABLED", "false") == "true"
    if login_disabled:
        return redirect(url_for("ui.index"))
    req = prepare_flask_request(request)
    auth = init_saml_auth(req)
    errors = []
    error_reason = None
    not_auth_warn = False
    attributes = False
    wrong_permissions = False

    if "sso" in request.args:
        return redirect(auth.login())
    elif "acs" in request.args:
        request_id = None
        if "AuthNRequestID" in session:
            request_id = session["AuthNRequestID"]
        logging.warning("request_id")
        logging.warning(request_id)
        logging.warning(session)
        auth.process_response(request_id=request_id)
        errors = auth.get_errors()
        logging.warning("errors")
        logging.warning(errors)
        logging.warning(auth.get_settings().is_debug_active())
        not_auth_warn = not auth.is_authenticated()
        if len(errors) == 0:
            if "AuthNRequestID" in session:
                del session["AuthNRequestID"]
            session["samlUserdata"] = auth.get_attributes()
            session["samlNameId"] = auth.get_nameid()
            session["samlNameIdFormat"] = auth.get_nameid_format()
            session["samlNameIdNameQualifier"] = auth.get_nameid_nq()
            session["samlNameIdSPNameQualifier"] = auth.get_nameid_spnq()
            session["samlSessionIndex"] = auth.get_session_index()
            self_url = OneLogin_Saml2_Utils.get_self_url(req)
            if "RelayState" in request.form and self_url != request.form["RelayState"]:
                # To avoid 'Open Redirect' attacks, before execute the redirection
                # confirm the value of the request.form['RelayState'] is a trusted URL.
                if not is_safe_url(request.form["RelayState"]):
                    abort(400)
                return redirect(auth.redirect_to(request.form["RelayState"]))
        elif auth.get_settings().is_debug_active():
            error_reason = auth.get_last_error_reason()
    if "samlUserdata" in session:
        if len(session["samlUserdata"]) > 0:
            cfg = set_cfg()
            attributes = session["samlUserdata"]

            # RBAC - Check if the user is a member of the allowed groups
            if not any(
                string in group
                for group in attributes["memberOf"]
                for string in cfg["rbac"]
            ):
                wrong_permissions = True
                return render_template(
                    "ui/login.html",
                    errors=errors,
                    error_reason=error_reason,
                    not_auth_warn=not_auth_warn,
                    wrong_permissions=wrong_permissions,
                    alert_email=cfg["alert_email"],
                )
        # JIT Provisioning
        if attributes["rhatUUID"][0] not in users:
            new_user = {
                attributes["rhatUUID"][0]: {
                    attribute_name: attribute_value
                    for (attribute_name, attribute_value) in attributes.items()
                }
            }
            users.update(new_user)
            redis_set("users", json.dumps(users))

        user = User(attributes["rhatUUID"][0])
        login_user(user)
        next_page = request.args.get("next")

        # Avoid 'Open Redirect'
        if not is_safe_url(next_page):
            return abort(400)
        return redirect(next_page or url_for("ui.index"))

    return render_template(
        "ui/login.html",
        errors=errors,
        error_reason=error_reason,
        not_auth_warn=not_auth_warn,
        wrong_permissions=wrong_permissions,
    )


# deprecated endpoints to remove
@BP.route("/updates/telco5g")
@BP.route("/updates/telco5g/all")
@BP.route("/updates/cnv")
@BP.route("/updates/cnv/all")
@BP.route("/updates/telco5g/severity")
@BP.route("/updates/telco5g/all/severity")
@BP.route("/updates/cnv/severity")
@BP.route("/updates/cnv/all/severity")
@BP.route("/stats/cnv")
@BP.route("/stats/telco5g")
# end of deprecated routes
@BP.route("/home")
@login_required
def index():
    """Display dashboard home page with new cases and statistics
    
    Main dashboard view showing new cases created in the last 7 days and
    summary statistics of card counts by status.
    
    Returns:
        str: Rendered HTML template with new cases and plot data
    """
    plot_data = plots()
    return render_template(
        "ui/index.html",
        new_cases=get_new_cases(),
        values=list(plot_data.values()),
        now=redis_get("timestamp"),
    )


@BP.route("/progress/status", methods=["POST"])
@login_required
def progress_status():
    """Check if a card refresh is in progress and return task information
    
    Called on page load to determine if a background card refresh is running.
    If a refresh is in progress, returns a 202 status with Location header
    pointing to the task status endpoint.
    
    Returns:
        tuple: JSON response, status code, and optional Location header.
            Returns (empty JSON, 202, Location) if refresh in progress,
            (empty JSON, 200) otherwise
    """
    refresh_id = redis_get("refresh_id")
    if refresh_id != {}:
        return (
            jsonify({}),
            202,
            {"Location": url_for("ui.refresh_status", task_id=refresh_id)},
        )
    else:
        return jsonify({})


@BP.route("/status/<task_id>")
@login_required
def refresh_status(task_id):
    """Provide real-time status updates for background refresh task
    
    Returns the current state of a background card refresh task including
    progress information (current/total cards processed) and status messages.
    Used for displaying progress bars in the UI.
    
    Args:
        task_id: Celery task ID for the refresh operation
        
    Returns:
        Response: JSON response with task state, current progress, total
            items, and status message
    """
    task = refresh_background.AsyncResult(task_id)
    if task.state == "PENDING":
        # job did not start yet
        response = {
            "state": task.state,
            "current": 0,
            "total": 1,
            "status": "Pending...",
        }
    elif task.state != "FAILURE":
        response = {
            "state": task.state,
            "current": task.info.get("current", 0),
            "total": task.info.get("total", 1),
            "status": task.info.get("status", ""),
        }
        if "result" in task.info:
            response["result"] = task.info["result"]
        if "locked" in task.info:
            response["locked"] = task.info["locked"]
    else:
        # something went wrong in the background job
        response = {
            "state": task.state,
            "current": 1,
            "total": 1,
            "status": str(task.info),  # this is the exception raised
        }
    return jsonify(response)


@BP.route("/refresh", methods=["POST"])
@login_required
def refresh():
    """Trigger a background refresh of JIRA cards cache
    
    Initiates an asynchronous background task to refresh the JIRA cards
    cache. Returns immediately with task ID for status polling.
    
    Returns:
        tuple: JSON response, 202 status code, and Location header pointing
            to the task status endpoint
    """
    task = refresh_background.delay()
    return jsonify({}), 202, {"Location": url_for("ui.refresh_status", task_id=task.id)}


@BP.route("/updates/")
@login_required
def report_view():
    """Display cards with comments from the last week
    
    Retrieves and displays JIRA cards that have comments created within the
    last 7 days, organized by account and status.
    
    Returns:
        str: Rendered HTML template showing cards with recent updates
    """
    cfg = set_cfg()
    cards = redis_get("cards")
    return render_template(
        "ui/updates.html",
        now=redis_get("timestamp"),
        new_comments=get_new_comments(cards),
        jira_server=cfg["server"],
        page_title="recent updates",
    )


@BP.route("/updates/all")
@login_required
def report_view_all():
    """Display all cards with all comments
    
    Retrieves and displays all JIRA cards with all their comments (not just
    recent ones), organized by account and status.
    
    Returns:
        str: Rendered HTML template showing all cards and comments
    """
    cfg = set_cfg()
    cards = redis_get("cards")
    return render_template(
        "ui/updates.html",
        now=redis_get("timestamp"),
        new_comments=get_new_comments(cards=cards, new_comments_only=False),
        jira_server=cfg["server"],
        page_title="all cards",
    )


@BP.route("/trends/")
@login_required
def trends():
    """Display cards marked with the 'Trends' label
    
    Retrieves and displays JIRA cards that have been labeled with 'Trends',
    typically used for tracking trending issues or patterns. Cards are
    organized by account and status.
    
    Returns:
        str: Rendered HTML template showing trending cards with SLA settings
    """
    cfg = set_cfg()
    cards = redis_get("cards")
    return render_template(
        "ui/updates.html",
        now=redis_get("timestamp"),
        new_comments=get_trending_cards(cards),
        jira_server=cfg["server"],
        page_title="trends",
        sla_settings=cfg["sla_settings"],
    )


@BP.route("/table/")
@login_required
def table_view():
    """Display cards with recent comments in table format sorted by severity
    
    Shows JIRA cards with comments from the last 7 days in a table view,
    organized by severity level for prioritization.
    
    Returns:
        str: Rendered HTML table template with cards sorted by severity
    """
    cfg = set_cfg()
    cards = redis_get("cards")
    return render_template(
        "ui/table.html",
        now=redis_get("timestamp"),
        new_comments=get_new_comments(cards),
        jira_server=cfg["server"],
        page_title="severity",
        sla_settings=cfg["sla_settings"],
    )


@BP.route("/table/all")
@login_required
def table_view_all():
    """Display all cards in table format sorted by severity
    
    Shows all JIRA cards (not just those with recent comments) in a table
    view, organized by severity level for comprehensive overview.
    
    Returns:
        str: Rendered HTML table template with all cards sorted by severity
    """
    cfg = set_cfg()
    cards = redis_get("cards")
    return render_template(
        "ui/table.html",
        now=redis_get("timestamp"),
        new_comments=get_new_comments(cards=cards, new_comments_only=False),
        jira_server=cfg["server"],
        page_title="all-severity",
        sla_settings=cfg["sla_settings"],
    )


@BP.route("/weekly/")
@login_required
def weekly_updates():
    """Display weekly updates in plain format for easy copying
    
    Shows cards with recent comments in a simplified, plain-text format
    optimized for copy/pasting into emails, reports, or other distribution
    channels.
    
    Returns:
        str: Rendered HTML template with plain-formatted weekly updates
    """
    cfg = set_cfg()
    cards = redis_get("cards")
    return render_template(
        "ui/weekly_report.html",
        now=redis_get("timestamp"),
        new_comments=get_new_comments(cards),
        jira_server=cfg["server"],
        page_title="weekly-update",
        sla_settings=cfg["sla_settings"],
    )


@BP.route("/stats")
@login_required
def get_stats():
    """Display comprehensive statistics and metrics dashboard
    
    Generates and displays overall statistics including counts by customer,
    engineer, severity, status, historical trends, and time-to-resolution
    histograms for all cases and cards.
    
    Returns:
        str: Rendered HTML template with statistics, time-series plots, and
            histogram data
    """
    stats = generate_stats()
    x_values, y_values = plot_stats()
    histogram_stats = generate_histogram_stats()
    return render_template(
        "ui/stats.html",
        now=redis_get("timestamp"),
        stats=stats,
        x_values=x_values,
        y_values=y_values,
        histogram_stats=histogram_stats,
        page_title="stats",
    )


@BP.route("/account/<string:account>")
@login_required
def get_account(account):
    """Display detailed view for a specific account
    
    Shows filtered statistics, cards, comments, and metrics for a single
    customer account including pie charts and time-to-resolution histograms.
    
    Args:
        account: Customer account name to filter by
        
    Returns:
        str: Rendered HTML template with account-specific data and statistics
    """
    cfg = set_cfg()
    stats = generate_stats(account)
    cards = redis_get("cards")
    comments = get_new_comments(cards=cards, new_comments_only=False, account=account)
    pie_stats = make_pie_dict(stats)
    histogram_stats = generate_histogram_stats(account)
    return render_template(
        "ui/account.html",
        page_title=account,
        account=account,
        now=redis_get("timestamp"),
        stats=stats,
        new_comments=comments,
        jira_server=cfg["server"],
        pie_stats=pie_stats,
        histogram_stats=histogram_stats,
        sla_settings=cfg["sla_settings"],
    )


@BP.route("/engineer/<string:engineer>")
@login_required
def get_engineer(engineer):
    """Display detailed view for a specific engineer
    
    Shows filtered statistics, cards, comments, and metrics for a single
    engineer including pie charts and time-to-resolution histograms. Uses
    the same template as account view with engineer_view flag enabled.
    
    Args:
        engineer: Engineer name (display name) to filter by
        
    Returns:
        str: Rendered HTML template with engineer-specific data and statistics
    """
    cfg = set_cfg()
    cards = redis_get("cards")
    stats = generate_stats(engineer=engineer)
    comments = get_new_comments(cards=cards, new_comments_only=False, engineer=engineer)
    pie_stats = make_pie_dict(stats)
    histogram_stats = generate_histogram_stats(engineer=engineer)
    return render_template(
        "ui/account.html",
        page_title=engineer,
        account=engineer,
        now=redis_get("timestamp"),
        stats=stats,
        new_comments=comments,
        jira_server=cfg["server"],
        pie_stats=pie_stats,
        histogram_stats=histogram_stats,
        engineer_view=True,
        sla_settings=cfg["sla_settings"],
    )

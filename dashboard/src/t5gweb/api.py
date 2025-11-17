"""API endpoints for t5gweb"""

import json

from flask import Blueprint, jsonify, request
from flask_login import login_required
from t5gweb.cache import (
    get_bz_details,
    get_cards,
    get_case_details,
    get_cases,
    get_escalations,
    get_issue_details,
    get_stats,
)
from t5gweb.libtelco5g import generate_stats, redis_get, redis_set, sync_portal_to_jira
from t5gweb.utils import set_cfg

BP = Blueprint("api", __name__, url_prefix="/api")


@BP.route("/")
@login_required
def index():
    """List all available API endpoints
    
    Returns a JSON object containing URLs for all available API endpoints
    including refresh endpoints and data retrieval endpoints.
    
    Returns:
        dict: Dictionary with 'endpoints' key containing list of endpoint URLs
    """
    endpoints = {
        "endpoints": [
            "{}refresh/cards".format(request.base_url),
            "{}refresh/cases".format(request.base_url),
            "{}refresh/bugs".format(request.base_url),
            "{}refresh/details".format(request.base_url),
            "{}refresh/escalations".format(request.base_url),
            "{}refresh/issues".format(request.base_url),
            "{}refresh/stats".format(request.base_url),
            "{}cards".format(request.base_url),
            "{}cases".format(request.base_url),
            "{}bugs".format(request.base_url),
            "{}details".format(request.base_url),
            "{}escalations".format(request.base_url),
            "{}issues".format(request.base_url),
            "{}stats".format(request.base_url),
        ]
    }
    return endpoints


@BP.route("/refresh/<string:data_type>")
@login_required
def refresh(data_type):
    """Force an immediate refresh of cached data
    
    Triggers synchronous data refresh for the specified data type. Supported
    types include cards, cases, details, bugs, escalations, issues,
    create_jira_cards, and stats.
    
    Args:
        data_type: Type of data to refresh. Valid values:
            - 'cards': JIRA cards cache
            - 'cases': Red Hat Portal cases cache
            - 'details': Case details including CritSit status
            - 'bugs': Bugzilla bug details
            - 'escalations': Escalated cases from JIRA board
            - 'issues': JIRA issues linked to cases
            - 'create_jira_cards': Sync Portal cases to JIRA
            - 'stats': Statistics cache
            
    Returns:
        Response: JSON response indicating success or error for the operation
    """
    cfg = set_cfg()
    if data_type == "cards":
        get_cards(cfg)
        return jsonify({"caching cards": "ok"})
    elif data_type == "cases":
        get_cases(cfg)
        return jsonify({"caching cases": "ok"})
    elif data_type == "details":
        get_case_details(cfg)
        return jsonify({"caching details": "ok"})
    elif data_type == "bugs":
        get_bz_details(cfg)
    elif data_type == "escalations":
        cases = redis_get("cases")
        escalations = get_escalations(cfg, cases)
        redis_set("escalations", json.dumps(escalations))
        return jsonify({"caching escalations": "ok"})
    elif data_type == "issues":
        get_issue_details(cfg)
        return jsonify({"caching issues": "ok"})
    elif data_type == "create_jira_cards":
        sync_portal_to_jira()
        return jsonify({"create_jira_cards": "ok"})
    elif data_type == "stats":
        get_stats()
        return jsonify({"caching stats": "ok"})
    else:
        return jsonify({"error": "unknown data type: {}".format(data_type)})


@BP.route("/cards")
@login_required
def show_cards():
    """Retrieve all JIRA cards from cache
    
    Returns cached JIRA cards data in JSON format.
    
    Returns:
        Response: JSON object containing all cached JIRA cards
    """
    cards = redis_get("cards")
    return jsonify(cards)


@BP.route("/cases")
@login_required
def show_cases():
    """Retrieve all Red Hat Portal cases from cache
    
    Returns cached case data in JSON format.
    
    Returns:
        Response: JSON object containing all cached cases
    """
    cases = redis_get("cases")
    return jsonify(cases)


@BP.route("/bugs")
@login_required
def show_bugs():
    """Retrieve all Bugzilla bugs from cache
    
    Returns cached Bugzilla bug data in JSON format.
    
    Returns:
        Response: JSON object containing all cached bugs
    """
    bugs = redis_get("bugs")
    return jsonify(bugs)


@BP.route("/escalations")
@login_required
def show_escalations():
    """Retrieve all escalated cases from cache
    
    Returns list of escalated case numbers in JSON format.
    
    Returns:
        Response: JSON object containing all escalated case numbers
    """
    escalations = redis_get("escalations")
    return jsonify(escalations)


@BP.route("/details")
@login_required
def show_details():
    """Retrieve case details including CritSit status and group names
    
    Returns detailed case information including CritSit flags, group names,
    notified users, and relief/resolution timestamps in JSON format.
    
    Returns:
        Response: JSON object containing case details for all cases
    """
    details = redis_get("details")
    return jsonify(details)


@BP.route("/issues")
@login_required
def show_issues():
    """Retrieve all JIRA issues associated with open cases
    
    Returns cached JIRA issue data linked to cases in JSON format.
    
    Returns:
        Response: JSON object containing all cached JIRA issues
    """
    issues = redis_get("issues")
    return jsonify(issues)


@BP.route("/stats")
@login_required
def show_stats():
    """Generate and return current statistics
    
    Generates fresh statistics including counts by customer, engineer,
    severity, status, and bug metrics in JSON format.
    
    Returns:
        Response: JSON object containing current statistics
    """
    stats = generate_stats()
    return jsonify(stats)

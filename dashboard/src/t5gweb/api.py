"""API endpoints for t5gweb"""
from flask import Blueprint, jsonify, request
from flask_login import login_required
from t5gweb.cache import (
    get_bz_details,
    get_cards,
    get_case_details,
    get_cases,
    get_escalations,
    get_issue_details,
    get_watchlist,
)
from t5gweb.libtelco5g import generate_stats, redis_get
from t5gweb.utils import set_cfg

BP = Blueprint("api", __name__, url_prefix="/api")


@BP.route("/")
@login_required
def index():
    """list api endpoints"""
    endpoints = {
        "endpoints": [
            "{}refresh/cards".format(request.base_url),
            "{}refresh/cases".format(request.base_url),
            "{}refresh/bugs".format(request.base_url),
            "{}refresh/details".format(request.base_url),
            "{}refresh/escalations".format(request.base_url),
            "{}refresh/watchlist".format(request.base_url),
            "{}refresh/issues".format(request.base_url),
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
    """Forces an update to the dashboard"""
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
        get_escalations(cfg)
        return jsonify({"caching escalations": "ok"})
    elif data_type == "watchlist":
        get_watchlist(cfg)
        return jsonify({"caching watchlist": "ok"})
    elif data_type == "issues":
        get_issue_details(cfg)
        return jsonify({"caching issues": "ok"})
    else:
        return jsonify({"error": "unknown data type: {}".format(data_type)})


@BP.route("/cards")
@login_required
def show_cards():
    """Retrieves all cards"""
    cards = redis_get("cards")
    return jsonify(cards)


@BP.route("/cases")
@login_required
def show_cases():
    """Retrieves all cases"""
    cases = redis_get("cases")
    return jsonify(cases)


@BP.route("/bugs")
@login_required
def show_bugs():
    """Retrieves all bugs"""
    bugs = redis_get("bugs")
    return jsonify(bugs)


@BP.route("/escalations")
@login_required
def show_escalations():
    """Retrieves all escalations"""
    escalations = redis_get("escalations")
    return jsonify(escalations)


@BP.route("/watchlist")
@login_required
def show_watched():
    """Retrieves all cases on the watchlist"""
    watchlist = redis_get("watchlist")
    return jsonify(watchlist)


@BP.route("/details")
@login_required
def show_details():
    """Retrieves CritSit and Group Name for each case"""
    details = redis_get("details")
    return jsonify(details)


@BP.route("/issues")
@login_required
def show_issues():
    """Retrieves all JIRA issues associated with open cases"""
    issues = redis_get("issues")
    return jsonify(issues)


@BP.route("/stats")
@login_required
def show_stats():
    stats = generate_stats()
    return jsonify(stats)

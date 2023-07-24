"""API endpoints for t5gweb"""
import json

from flask import Blueprint, request
from flask_login import login_required

from t5gweb.cache import (get_bz_details, get_cards, get_case_details,
                          get_cases, get_escalations, get_issue_details,
                          get_watchlist)
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
        return {"caching cards": "ok"}
    elif data_type == "cases":
        get_cases(cfg)
        return {"caching cases": "ok"}
    elif data_type == "details":
        get_case_details(cfg)
        return {"caching details": "ok"}
    elif data_type == "bugs":
        get_bz_details(cfg)
    elif data_type == "escalations":
        get_escalations(cfg)
        return {"caching escalations": "ok"}
    elif data_type == "watchlist":
        get_watchlist(cfg)
        return {"caching watchlist": "ok"}
    elif data_type == "issues":
        get_issue_details(cfg)
        return {"caching issues": "ok"}
    else:
        return {"error": "unknown data type: {}".format(data_type)}


@BP.route("/cards")
@login_required
def show_cards():
    """Retrieves all cards"""
    cards = redis_get("cards")
    return cards


@BP.route("/cases")
@login_required
def show_cases():
    """Retrieves all cases"""
    cases = redis_get("cases")
    return cases


@BP.route("/bugs")
@login_required
def show_bugs():
    """Retrieves all bugs"""
    bugs = redis_get("bugs")
    return bugs


@BP.route("/escalations")
@login_required
def show_escalations():
    """Retrieves all escalations"""
    escalations = redis_get("escalations")
    return json.dumps(escalations)


@BP.route("/watchlist")
@login_required
def show_watched():
    """Retrieves all cases on the watchlist"""
    watchlist = redis_get("watchlist")
    return json.dumps(watchlist)


@BP.route("/details")
@login_required
def show_details():
    """Retrieves CritSit and Group Name for each case"""
    details = redis_get("details")
    return json.dumps(details)


@BP.route("/issues")
@login_required
def show_issues():
    """Retrieves all JIRA issues associated with open cases"""
    issues = redis_get("issues")
    return json.dumps(issues)


@BP.route("/stats")
@login_required
def show_stats():
    stats = generate_stats()
    return stats

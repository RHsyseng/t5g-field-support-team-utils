"""API endpoints for t5gweb"""
from flask import (
    Blueprint, request
)
from t5gweb.t5gweb import (
    set_cfg
)
from t5gweb.libtelco5g import(
    cache_cases,
    cache_cards,
    cache_bz,
    redis_get
)

BP = Blueprint('api', __name__, url_prefix='/api')

@BP.route('/')
def index():
    """list api endpoints"""
    endpoints = {"endpoints": [
        "{}refresh/cards".format(request.base_url),
        "{}refresh/cases".format(request.base_url),
        "{}refresh/bugs".format(request.base_url),
        "{}cards/telco5g".format(request.base_url),
        "{}cards/cnv".format(request.base_url),
        "{}cases/telco5g".format(request.base_url),
        "{}cases/cnv".format(request.base_url),
        "{}bugs".format(request.base_url),
    ]}
    return endpoints

@BP.route('/refresh/<string:data_type>')
def refresh(data_type):
    """Forces an update to the dashboard"""
    cfg = set_cfg()
    if data_type == 'cards':
        cache_cards(cfg)
        return {"caching cards":"ok"}
    elif data_type == 'cases':
        cache_cases(cfg)
        return {"caching cases":"ok"}
    elif data_type == 'bugs':
        cache_bz(cfg)
        return {"caching bugs":"ok"}

@BP.route('/cards/<string:card_type>')
def get_cards(card_type):
    """Retrieves all cards of a specific type"""
    if card_type == 'telco5g':
        cards = redis_get('cards')
        telco_cards = {c:d for (c,d) in cards.items() if 'field' in d['labels']}
        return telco_cards
    elif card_type == 'cnv':
        cards = redis_get('cards')
        cnv_cards = {c:d for (c,d) in cards.items() if 'field' in d['labels']}
        return cnv_cards
    else:
        return {'error': 'unknown card type: {}'.format(card_type)}

@BP.route('/cases/<string:case_type>')
def get_cases(case_type):
    """Retrieves all cases of a specific type"""
    if case_type == 'telco5g':
        cases = redis_get('cases')
        telco_cases = {c:d for (c,d) in cases.items() if 'shift_telco5g' in d['tags']}
        return telco_cases
    elif case_type == 'cnv':
        cases = redis_get('cases')
        cnv_cases = {c:d for (c,d) in cases.items() if 'cnv' in d['tags']}
        return cnv_cases
    else:
        return {'error': 'unknown card type: {}'.format(case_type)}
    
@BP.route('/bugs')
def get_bugs():
    """Retrieves all bugs"""
    bugs = redis_get('bugs')
    return bugs
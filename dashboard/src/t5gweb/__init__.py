"""initialize t5gweb application"""
import os
from flask import Flask, redirect, url_for
from prometheus_flask_exporter import PrometheusMetrics
from . import t5gweb
from . import api
from . import ui

def create_app(test_config=None):
    """factory functions to launch app"""
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = os.environ.get('secret_key')
    ui.login_manager.init_app(app)
    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    metrics = PrometheusMetrics(app)
    metrics.info('app_info', 'App Info', version='1.230428')

    t5gweb.init_app(app)
    app.register_blueprint(api.BP)
    app.register_blueprint(ui.BP)
    return app

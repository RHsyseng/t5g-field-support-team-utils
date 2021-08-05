"""initialize t5gweb application"""
import os
from flask import Flask, redirect, url_for
from .cache import cache

def create_app(test_config=None):
    """factory functions to launch app"""
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    cache.init_app(app)
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

    #@app.route('/')
    #def _():
    #    return redirect(url_for('ui.index'))

    from . import ui
    app.register_blueprint(ui.BP)
    return app

from . import bp


def register_blueprints(app):
    app.register_blueprint(bp)

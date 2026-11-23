def register(app):
    from api.routes import access, auth, dashboard, defects, equipment, scheduled
    for module in (auth, dashboard, scheduled, defects, access, equipment):
        app.register_blueprint(module.bp, url_prefix='/api')

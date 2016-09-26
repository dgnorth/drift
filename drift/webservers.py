# -*- coding: utf-8 -*-

import logging

log = logging.getLogger(__name__)

DEFAULT_PORT = 5000


def run_app(app, web_server=None):
    """
    Run Flask app in the specified web server.
    :param app: an instance of :class:`flask.Flask`.
    :param web_server: is one of:
        "flask":    Use Flask default web server (Werkzeug).
        "tornado":  Use Tornado web server.
        "gevent":   Use Gevent web server.
        "twisted":  Use Twisted Web web server.
        "gunicorn": Use Gunicorn web server.
        "mod_wsgi": Use Apache web server.
        "uwsgi":    Use uWSGI web server.

    If :param web_server: is None, the "web_server" config value from `app`
    is used.

    Note: Only "flask", "tornado", "gevent", and "twisted" work a the moment.
    """
    web_server = web_server or "flask"
    log.info("Running '%s' web server on port %s", web_server, app.config.get('PORT', DEFAULT_PORT))

    # Magically map 'web_server' to a local function name.
    import webservers
    fn = getattr(webservers, "run_{}_server".format(web_server), None)
    if fn is None:
        raise RuntimeError("Web server '%s' not supported." % web_server)
    fn(app, app.config.get('PORT', DEFAULT_PORT))


def run_flask_server(app, port):
    app.run(threaded=True, host='0.0.0.0', port=port)


def run_tornado_server(app, port):

    from tornado.wsgi import WSGIContainer
    from tornado.httpserver import HTTPServer
    from tornado.ioloop import IOLoop
    log.info("Activating Tornado server on port %s", port)
    http_server = HTTPServer(WSGIContainer(app), xheaders=True)
    http_server.listen(port)
    IOLoop.instance().start()


def run_gevent_server(app, port):
    from gevent.pywsgi import WSGIServer
    import gevent.monkey
    gevent.monkey.patch_all()

    log.info("Activating gevent server on port %s", port)
    http_server = WSGIServer(('', port), app)
    http_server.serve_forever()


def run_twisted_server(app, port):
    import sys

    try:
        import _preamble
        _preamble
    except ImportError:
        sys.exc_clear()

    sys.argv = ['runserver.py', 'web', '--port',
                str(port), '--wsgi', 'app.app']
    from twisted.scripts.twistd import run
    run()


def run_gunicorn_server(app, port):
    # this is not tested and does not work. only runs on linux.
    raise RuntimeError("Not Implemented yet!")
    import sys
    from pkg_resources import load_entry_point

    sys.exit(
        load_entry_point(
            'gunicorn==19.0.0', 'console_scripts', 'gunicorn')()
    )


def run_mod_wsgi_server(app, port):
    raise RuntimeError("Not Implemented yet!")


def run_uwsgi_server(app, port):
    raise RuntimeError("Not Implemented yet!")
    # this is not tested and does not work. only runs on linux.
    import sys

    sys.argv = ['runserver.py', '-s', '/tmp/uwsgi.sock', '-w', 'app.app']

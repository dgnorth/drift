"""
Run all apps in this project as a console server.
"""
from drift import webservers

def get_options(parser):
    parser.add_argument("--server", help="Server type to run (e.g. tornado)", default=None)

def run_command(args):
    from drift.appmodule import app
    webservers.run_app(app, args.server)

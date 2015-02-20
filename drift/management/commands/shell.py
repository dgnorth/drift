"""
Interactive shell
"""
from drift.flaskfactory import create_app

def run_command(args):
    from drift.appmodule import app
    import code
    code.interact(local=locals())
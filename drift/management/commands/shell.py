# -*- coding: utf-8 -*-
"""
Interactive shell
"""


def run_command(args):
    from drift.appmodule import app
    import code
    code.interact(local=locals())

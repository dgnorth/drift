#!/usr/bin/env python
import sys, os, argparse
import imp
import importlib

def get_commands():
    commands = [f[:-3] for f in os.listdir(os.path.join(__path__[0], "commands")) if not f.startswith("_") and f.endswith(".py")]
    return commands

def execute_cmd():
    valid_commands = get_commands()
    parser = argparse.ArgumentParser(description="")
    #parser.add_argument("command", help="Command to execute", choices=valid_commands)
    parser.add_argument("-v", "--verbose", help="I am verbose!", action="store_true")

    subparsers = parser.add_subparsers(help="sub-command help")
    for cmd in valid_commands:
        module = importlib.import_module("drift.management.commands." + cmd)
        subparser = subparsers.add_parser(cmd, help="Subcommands for {}".format(cmd))
        if hasattr(module, "get_options"):
            module.get_options(subparser)
        subparser.set_defaults(func=module.run_command)

    args = parser.parse_args()
    args.func(args)

# -*- coding: utf-8 -*-
import sys
import unittest
import os.path
import importlib


"""
Test the import of various top level modules to make sure they compile
"""


class ImportTestCase(unittest.TestCase):
    def test_devapp(self):
        importlib.import_module("drift.contrib.flask.devapp")

    def test_fixers(self):
        importlib.import_module("drift.fixers")

    def test_flaskfactory(self):
        importlib.import_module("drift.flaskfactory")

    def test_orm(self):
        importlib.import_module("drift.orm")

    def test_systesthelper(self):
        importlib.import_module("drift.systesthelper")

    def test_urlregistry(self):
        importlib.import_module("drift.core.extensions.urlregistry")

    def test_utils(self):
        importlib.import_module("drift.utils")

    def test_uwsgiboot(self):
        importlib.import_module("drift.contrib.flask.plainapp")

    def test_version(self):
        importlib.import_module("drift.version")

    def test_webservers(self):
        importlib.import_module("drift.webservers")

    def test_drift_commands(self):
        import drift.management
        valid_commands = drift.management.get_commands()
        for cmd in valid_commands:
            importlib.import_module("drift.management.commands." + cmd)


class ScriptImportTestCase(unittest.TestCase):
    script_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

    def setUp(self):
        sys.path.append(self.script_dir)

    def tearDown(self):
        sys.path.pop()

    def test_parse_uwsgi_profiler(self):
        importlib.import_module("parse_uwsgi_profiler")

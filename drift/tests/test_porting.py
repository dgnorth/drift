# -*- coding: utf-8 -*-
import sys
import unittest
import os.path
import importlib


"""
Test the import of various top level modules to make sure they compile
"""
class ImportTestCase(unittest.TestCase):
    def test_celeryboot(self):
        import drift.celeryboot

    def test_devapp(self):
        import drift.devapp

    def test_fixers(self):
        import drift.fixers

    def test_flaskfactory(self):
        import drift.flaskfactory

    def test_orm(self):
        import drift.orm

    def test_systesthelper(self):
        import drift.systesthelper

    def test_urlregistry(self):
        import drift.urlregistry

    def test_utils(self):
        import drift.utils

    def test_uwsgiboot(self):
        import drift.uwsgiboot

    def test_version(self):
        import drift.version

    def test_webservers(self):
        import drift.webservers

    def test_drift_commands(self):
        import drift.management
        valid_commands = drift.management.get_commands()
        for cmd in valid_commands:
            module = importlib.import_module("drift.management.commands." + cmd)



class ScriptImportTestCase(unittest.TestCase):
    script_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

    def setUp(self):
        sys.path.append(self.script_dir)
    def tearDown(self):
        sys.path.pop()

    def test_drift_admin(self):
        # must use this because drift-admin.py contains a dash!
        __import__('drift-admin', globals(), locals(), [], 0)

    def test_parse_uwsgi_profiler(self):
        import parse_uwsgi_profiler

    def test_travis_build_dependent_projects(self):
        import travis_build_dependent_projects

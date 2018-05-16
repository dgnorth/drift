# -*- coding: utf-8 -*-
import unittest


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

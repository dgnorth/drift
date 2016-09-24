import unittest
import logging

from flask import Flask

import jsonschema


from drift.core.extensions.schemachecker import get_schema_for_media_type, validate

@unittest.skip("needs refactoring")
class driftTestCase(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        logging.basicConfig(level="ERROR")
        self.app.testing = True
        self.test_client = self.app.test_client()

    def tearDown(self):
        pass

    def test_flasksetup(self):
        # Run minimal setup
        flasksetup(self.app, options=[])

    def test_all(self):
        # Run with all options
        flasksetup(self.app)



if __name__ == "__main__":

    unittest.main()

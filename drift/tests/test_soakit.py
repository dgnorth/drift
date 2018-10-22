import unittest
import logging

from flask import Flask


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
        # flasksetup(self.app, options=[])
        pass

    def test_all(self):
        # Run with all options
        # flasksetup(self.app)
        pass


if __name__ == "__main__":

    unittest.main()

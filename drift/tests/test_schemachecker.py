import unittest
import logging

import jsonschema

from app.realapp import make_app
from drift.flasksetup import flasksetup
from drift.core.extensions.schemachecker import get_schema_for_media_type, validate


class StatusMonitorTestCase(unittest.TestCase):

    def setUp(self):
        logging.basicConfig(level="ERROR")
        self.app = make_app()
        self.app.config["TESTING"] = True
        flasksetup(self.app, ["schemachecker"])
        self.test_client = self.app.test_client()

    def tearDown(self):
        pass

    def test_schema(self):
        pass


if __name__ == "__main__":

    unittest.main()

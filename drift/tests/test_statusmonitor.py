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
        flasksetup(self.app, ["statusmonitor", "schemachecker"])
        self.test_client = self.app.test_client()

    def tearDown(self):
        pass

    def test_monitor(self):
        TEMPLATE = "_service_info_template"
        mon = self.app.extensions.get("statusmonitor")
        service_status = mon.get_service_status(TEMPLATE)

        with self.assertRaises(RuntimeError):
            # Get a service that has no .json file defined. It should fail.
            mon.get_service_status("not_a_real_service")

        # Do tests using the .json service template.
        si = service_status.get_service_info()
        self.assertEqual(si["status"], "ok")

        # Flag an error on item 'dummy'
        service_status.update_status("error", "dummy")
        si = service_status.get_service_info()
        self.assertEqual(si["status"], "error")

        # Flag it back to 'ok' on item 'dummy'
        service_status.update_status("ok", "dummy")
        si = service_status.get_service_info()
        self.assertEqual(si["status"], "ok")

        # Flag it back to 'ok' on item 'dummy'
        service_status.update_status("ok", "dummy")
        si = service_status.get_service_info()
        self.assertEqual(si["status"], "ok")

        # Flag dummy2 entry to 'warning'
        service_status.update_status("warning", "dummy2")
        si = service_status.get_service_info()
        self.assertEqual(si["status"], "warning")

        # Flag dummy3 entry to 'error'
        service_status.update_status("error", "dummy3")
        si = service_status.get_service_info()
        self.assertEqual(si["status"], "error")

        # Make sure there's no leak between return values
        service_status.update_status("warning", "dummy3")
        si2 = service_status.get_service_info()
        self.assertNotEqual(si, si2)

        with self.assertRaises(RuntimeError):
            # Try set bogus status
            service_status.update_status("bogus status", "dummy")


    def test_schema(self):
        TEMPLATE = "_service_info_template"
        mon = self.app.extensions.get("statusmonitor")
        format_checker = jsonschema.FormatChecker()
        with self.app.test_request_context():
            schema = get_schema_for_media_type("vnd.ccp.eus.servicestatus-v1")

        # Do tests using the .json service template.
        service_status = mon.get_service_status(TEMPLATE)
        si = service_status.get_service_info()
        self.assertEqual(si["status"], "ok")
        jsonschema.validate(si, schema, format_checker=format_checker)

        # Insert buggy data and make sure it's caught
        si["contact_info"][0]["phone"] = 123  # Must be string, not number.
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(si, schema, format_checker=format_checker)

        # Create and update a dependency
        service_status.update_status(
            "warning",
            "dependency check",
            check_duration=5.5,
            last_error="just checking"
        )

        si = service_status.get_service_info()
        jsonschema.validate(si, schema, format_checker=format_checker)

if __name__ == "__main__":

    unittest.main()

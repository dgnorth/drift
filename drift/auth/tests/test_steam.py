import unittest
import mock
from json import loads, dumps

import requests
from werkzeug.exceptions import Unauthorized, ServiceUnavailable

from drift.auth.steam import run_ticket_validation

patcher = None


def setUpModule():

    original_get = requests.get

    def requests_get_mock(url, *args, **kw):

        class Response(object):
            def json(self):
                return loads(self.content)

        response = Response()
        response.status_code = 200

        if url == 'key url':
            response.content = 'secret key'
        elif 'AuthenticateUserTicket' in url:
            ret = {
                "response": {
                    "params": {
                        "result": "OK",
                        "steamid": "76561198026053155",
                        "ownersteamid": "76561198026053155",
                        "vacbanned": False,
                        "publisherbanned": False
                    }
                }
            }
            response.content = dumps(ret)
        elif 'CheckAppOwnership' in url:
            ret = {
                "appownership": {
                    "ownsapp": True,
                    "permanent": False,
                    "timestamp": "2016-07-04T08:01:08Z",
                    "ownersteamid": "76561198026053155",
                    "result": "OK"
                }
            }
            response.content = dumps(ret)
        else:
            return original_get(url, *args, **kw)

        return response

    global patcher
    patcher = mock.patch('requests.get', requests_get_mock)
    patcher.start()


def tearDownModule():
    global patcher
    patcher.stop()


class SteamCase(unittest.TestCase):

    steamid = '76561198026053155'
    ticket = "140000003DED863BEB5F462E23D6EB0301001001C78E8457180000000100000002000000B2470DD200000000E081FC0"\
        "111000000B2000000320000000400000023D6EB0301001001E0010000B2470DD2CA00010A00000000604C8457E0FB9F5701"\
        "00000000000000000036237172F0213710820FA4E76E26FCD11C7A2A1EC868680D7AF51DAEB7859BACEB85D4972E0E2DDB0"\
        "4D9D8EC2E24392C4981F1588930285424F4B4B15F545AD2B1E06482163A9E91BF2EE5BF0A270C3B287FFE7F532AF0A0448D"\
        "11381EEE1CA2652FA914C2C833A362761B394D7D8489F9CC5886839AA8F0053547ACE7582C3A"

    def test_missing_fields(self):
        # Verify missing field check. The exception will list out all missing fields, so by removing
        # a single field, we should only be notified of that one missing.
        with self.assertRaises(Unauthorized) as context:
            run_ticket_validation({})
        self.assertIn("The token is missing required fields: ticket, appid.", context.exception.description)

    def test_broken_url(self):
        # Verify that broken key url is caught
        with self.assertRaises(ServiceUnavailable) as context:
            run_ticket_validation({'ticket': self.ticket, 'appid': 123}, key_url='http://localhost:1/')
        self.assertIn("The server is temporarily unable", context.exception.description)

    def test_steam(self):
        # Can't really test this. Just mock success cases from api.steampowered.com.
        steamid = run_ticket_validation({'steamid': self.steamid, 'ticket': self.ticket, 'appid': 123}, key_url='key url')
        self.assertTrue(steamid == self.steamid)
        # TODO: mock error cases as well. it isn't that hard.


if __name__ == "__main__":
    import logging
    logging.basicConfig(level='INFO')
    unittest.main()

import unittest
import collections
import mock

import requests
from werkzeug.exceptions import Unauthorized, ServiceUnavailable

from drift.auth.gamecenter import validate_gamecenter_token, TRUSTED_ORGANIZATIONS


template = {
    "public_key_url": "https://static.gc.apple.com/public-key/gc-prod-2.cer",
    "app_bundle_id": "com.directivegames.themachines.ios",
    "player_id": "G:1637867917",
    "timestamp": 1452128703383,
    "salt": "vPWarQ==",
    "signature": "ZuhbO8TqGKadYAZHsDd5NgTs/tmM8sIqhtxuUmxOlhmp8PUAofIYzdwaNlKcJwYoExT2dL78qZWlLgHFRQ4Z458tCL1scXKcEzMvTdROAJfCvOBrzzPrYXqLGMh/x9yc6Rb5hgdnleOnxKtcXEuq+U2l2y7WTssUYKByOHfGiZLvGeICYOIt1XdV18JbR6kBwB7oXZuwbERwvccnaeVoIiqjF52XvjSKuJg2X0GPvN8TDMFT9FUaDUrKmMFHiBmd6FWbe59V3/dTg7IeKY8BuZYRmVbnuSsrp4kmuKaLSMknIOyhpwbIbn47B43nzYafiqmXv0O//y0owV7fkKYc+Q=="
}

app_bundles = ["com.directivegames.themachines.ios"]

# Apple cert file
gc_prod_2_cer = '0\x82\x04\xe70\x82\x03\xcf\xa0\x03\x02\x01\x02\x02\x10qN\x1ai;\xe7.A<'\
    '\x1633\x02\xd4Je0\r\x06\t*\x86H\x86\xf7\r\x01\x01\x0b\x05\x000\x7f1\x0b0\t\x06\x03U'\
    '\x04\x06\x13\x02US1\x1d0\x1b\x06\x03U\x04\n\x13\x14Symantec Corporation1\x1f0\x1d'\
    '\x06\x03U\x04\x0b\x13\x16Symantec Trust Network100.\x06\x03U\x04\x03\x13\'Symantec'\
    ' Class 3 SHA256 Code Signing CA0\x1e\x17\r150228000000Z\x17\r170227235959Z0n1\x0b0'\
    '\t\x06\x03U\x04\x06\x13\x02US1\x0b0\t\x06\x03U\x04\x08\x0c\x02CA1\x120\x10\x06\x03U'\
    '\x04\x07\x0c\tCupertino1\x130\x11\x06\x03U\x04\n\x0c\nApple Inc.1\x140\x12\x06\x03U'\
    '\x04\x0b\x0c\x0bISO RaD SRE1\x130\x11\x06\x03U\x04\x03\x0c\nApple Inc.0\x82\x01"0\r'\
    '\x06\t*\x86H\x86\xf7\r\x01\x01\x01\x05\x00\x03\x82\x01\x0f\x000\x82\x01\n\x02\x82\x01'\
    '\x01\x00\xba\xab\xfe\xe5\xff\xba\x8e\xcf\x951]`\xd4\x96)\xaeeT\xcf}~%\x06x\xc3\xc3W\xdd'\
    '\xa8\xb2X\xc9{\xc5\x7fD9b\xd6Z\x12,\xaa\x8d\x12B\x94\x1d}\xe5\xb5\x13\x05@\xf0KV\'\xb5'\
    '\x8dZ\x10\xd8\xd8B\xf4Q\x18\xd1A\xc9\xba\x1a}\xfc\xb5O\xa9\x83i\xb7$\xbf\xc9*\x90h\x02'\
    '\xd5\xa1s\xd4N\x13\x9fw\x88\xd8\xc4\x80>9yUHj\xf0\'\xc5\x87\xc8\xb5\xceek_\xb8Z\xa0U\xf3'\
    '\xcf\xcc\x18\xae\xf8m\x93VN\x03\xf8\x84yt\xceM\x8b{\x0b~\x14\xdcne8\xd1\xfa\xd5`\x95\x7f('\
    '\xb3|\x02\x12\xc0\xecTF\xae6\x05C_F\xea\xf5\x17\xbe\x11\x01@\x8f\xd6K\x93\xf9\xd7Z\x11\x9f'\
    '\xfc7n\nWc%|,\xc7\xa5\xb6\xf4\x82\xd7\x1e\x0b+\x08a\xb5EWE\x17\xeb\xe2\xf1\x87\xb0`\xe5z*'\
    '\x97\xb38\t\xc9\x9c\x1bJ\xf0\xf4\xa2h^\xb3\x85M\x8a\xae\xbc\xb1\x95&m"\xe3\xe4\x1d\xa9jAK'\
    '\nV\x92\xd5e\xaf\x95\x89\x02\x03\x01\x00\x01\xa3\x82\x01n0\x82\x01j0\t\x06\x03U\x1d\x13\x04'\
    '\x020\x000\x0e\x06\x03U\x1d\x0f\x01\x01\xff\x04\x04\x03\x02\x07\x800\x13\x06\x03U\x1d%\x04'\
    '\x0c0\n\x06\x08+\x06\x01\x05\x05\x07\x03\x030f\x06\x03U\x1d \x04_0]0[\x06\x0b`\x86H\x01\x86'\
    '\xf8E\x01\x07\x17\x030L0#\x06\x08+\x06\x01\x05\x05\x07\x02\x01\x16\x17https://d.symcb.com/cp'\
    's0%\x06\x08+\x06\x01\x05\x05\x07\x02\x020\x19\x1a\x17https://d.symcb.com/rpa0\x1f\x06\x03U'\
    '\x1d#\x04\x180\x16\x80\x14\x96;S\xf0y3\x97\xaf}\x83\xef.+\xcc\xca\xb7\x86\x1erf0+\x06'\
    '\x03U\x1d\x1f\x04$0"0 \xa0\x1e\xa0\x1c\x86\x1ahttp://sv.symcb.com/sv.crl0W\x06\x08+'\
    '\x06\x01\x05\x05\x07\x01\x01\x04K0I0\x1f\x06\x08+\x06\x01\x05\x05\x070\x01\x86\x13http'\
    '://sv.symcd.com0&\x06\x08+\x06\x01\x05\x05\x070\x02\x86\x1ahttp://sv.symcb.com/sv.crt0'\
    '\x11\x06\t`\x86H\x01\x86\xf8B\x01\x01\x04\x04\x03\x02\x04\x100\x16\x06\n+\x06\x01\x04'\
    '\x01\x827\x02\x01\x1b\x04\x080\x06\x01\x01\x00\x01\x01\xff0\r\x06\t*\x86H\x86\xf7\r'\
    '\x01\x01\x0b\x05\x00\x03\x82\x01\x01\x00y2\xa3S\xc1\x9e\xf1\xfa\xc8\x124\x86\xd2\xf6='\
    '\x99\xa1e\\`\x01x\xa2\xc1|\x8eO\x84\xb9\x1e53Zrg\x8b\xe1\x91\x11\x91n[\xf6\xb4\xee\xe0'\
    '\xa2\xcf\xed\x91~\x08\xea\x02\xb7]u\x1aK\x1eN\xb1\xfdJa\x11\xb6\xd8KE#\xbc\xb7u\xa8H'\
    '\xc2\xb6!\xa3\xf6\x114\x92j\xa8\x0b\xa0\xc0\xe3\xc2\xd1a\x8f\x8f&\xaf=\x9aD\xad#\x8b'\
    '\x8b\xef\x16\x1b\xa3\x85+O\x14\x08i\x0e\x88f\xf5\xa1c\xccz\xfb\xb0~c\xbe4\xee\x1cl%e'\
    '\x97Xq\xecF\xa32\x1d\xf8\x1e\xc0\xce=\x93r\xd8\xa9.(\x12*<9\x00\x89\x99:\xe5\x08\xf5'\
    '\xec\x9de\xdb\x1f\xcf+\xe1\xc6\xab(^\xa9=26\xdb\x01\xcaO\xf4\x0f\x9e\x9d\xc06\x80Kut'\
    '\xe8V\xbb:\xf7\x89+\xf5\r\xc8$S]=\xc3\xa3\xf01\x00\xa4{`\xf7\xb2\xf6+Ja\xce\xe5\xf1O?'\
    '\xc7\x82\xbc\x12NzR\xc4\xdaR$\x08\xc3\xf98\x07\xdcTY`\x1a\x94\xcf|Ec\x0f\xc8\xc6\xaa'


patcher = None

def setUpModule():

    original_get = requests.get

    def requests_get_mock(url, *args, **kw):
        if url == 'broken url':
            raise requests.exceptions.RequestException('Url broken - unittest.')
        elif url == 'broken cert':
            broken_cert = collections.namedtuple('Response', 'content status_code')
            broken_cert.content = 'not a valid cert'
            broken_cert.status_code = 200
            return broken_cert
        elif url == template['public_key_url']:
            cert = collections.namedtuple('Response', 'content status_code')
            cert.content = gc_prod_2_cer
            cert.status_code = 200
            return cert
        else:
            return original_get(url, *args, **kw)

    global patcher
    patcher = mock.patch('requests.get', requests_get_mock)
    patcher.start()


def tearDownModule():
    global patcher
    patcher.stop()


class GameCenterCase(unittest.TestCase):

    def test_gamecenter(self):
        # This should fly straight through
        validate_gamecenter_token(template, app_bundles=app_bundles)

    def test_missing_fields(self):
        # Verify missing field check. The exception will list out all missing fields, so by removing
        # a single field, we should only be notified of that one missing.
        with self.assertRaises(Unauthorized) as context:
            t = template.copy()
            del t['salt']
            validate_gamecenter_token(t)
        self.assertIn("The token is missing required fields: salt.", context.exception.description)

    def test_app_bundles(self):
        # Verify that the token is issued to the appropriate app.
        with self.assertRaises(Unauthorized) as context:
            validate_gamecenter_token(template, app_bundles=['dummy'])
        self.assertIn("'app_bundle_id' not one of ['dummy']", context.exception.description)
        
    def test_broken_url(self):
        # Verify that broken public key url is caught
        with self.assertRaises(ServiceUnavailable) as context:
            t = template.copy()
            t['public_key_url'] = 'broken url'
            validate_gamecenter_token(t)
        self.assertIn("The server is temporarily unable", context.exception.description)

    def test_broken_cert(self):
        # Verify that broken certs fail.
        with self.assertRaises(Unauthorized) as context:
            t = template.copy()
            t['public_key_url'] = 'broken cert'
            validate_gamecenter_token(t)
        self.assertIn("Can't load certificate", context.exception.description)        

    def test_cert_validation(self):
        # Make sure cert is issued to a trusted organization.
        _tmp = TRUSTED_ORGANIZATIONS[:]
        TRUSTED_ORGANIZATIONS[:] = ['Mordor Inc.']
        try:
            with self.assertRaises(Unauthorized) as context:
                validate_gamecenter_token(template)
            self.assertIn("Certificate is issued to 'Apple Inc.' which is not one of ['Mordor Inc.'].", context.exception.description)
        finally:
            TRUSTED_ORGANIZATIONS[:] = _tmp

    def test_cert_expiration(self):
        # TODO: See if there is any way to test for cert expiration. It's tricky me thinks.
        pass

    def test_signature(self):
        # Check signature of token by corrupting the signature
        with self.assertRaises(Unauthorized) as context:
            t = template.copy()
            t['signature'] = t['signature'][:84] + '5' + t['signature'][85:]  # Just modify one random letter.
            validate_gamecenter_token(t)
        self.assertIn("Can't verify signature:", context.exception.description)
        self.assertIn("'padding check failed'", context.exception.description)

        # Check signature of token by modifying the payload
        with self.assertRaises(Unauthorized) as context:
            t = template.copy()
            t['player_id'] = 'G:5637867917'
            validate_gamecenter_token(t)
        self.assertIn("Can't verify signature:", context.exception.description)
        self.assertIn("'bad signature'", context.exception.description)

    # For requests library mock
    def requests_get(self, url, *args, **kw):
        if url == 'broken':
            raise requests.exceptions.RequestException('Url broken - unittest.')
        elif url == template['public_key_url']:
            return self
        else:
            return GameCenterCase.orig_get(url, *args, **kw)
        

if __name__ == "__main__":

    unittest.main()

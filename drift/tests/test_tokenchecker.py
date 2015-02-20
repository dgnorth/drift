import unittest
import httplib
import logging
from datetime import datetime

from app.realapp import app
from .. import tokenchecker


class TestTokenChecker(tokenchecker.TokenChecker):

    # This is a typical token from TQ SSO.
    token = {
        "userName": None,
        "tokenType": "Service",
        "clientIdentifier": "BuddyService",
        "userID": None,
        "customerID": None,
        "applicationID": 39,
        "characterID": None
    }

    def get_token_from_issuer(self, auth):
        ## "expires_on": datetime.datetime(2014, 4, 8, 13, 11, 49, 715021, tzinfo=<iso8601.iso8601.Utc object at 0x0259DD30>)}
        return self.token.copy()


auth = TestTokenChecker(app)

@app.route("/scoped1")
@auth.scoped("somescope.read.v1")
def scoped1():
    return "ok"

@app.route("/scoped2")
@auth.scoped("somescope.read.v1 somescope.write.v1")
def scoped2():
    return "ok"

@app.route("/scoped_none")
@auth.scoped()
def scoped_none():
    return "ok"

class TokenCheckerTestCase(unittest.TestCase):

    def setUp(self):
        logging.basicConfig(level="ERROR")
        app.config["TESTING"] = True
        self.app = app.test_client()
        auth.testcase = self

    def tearDown(self):
        pass


    def test_authorization(self):

        app.config["OAUTH2_DEBUG_SKIPCHECK"] = False

        # Token from issuer will start with no 'scopes' and no 'expiresOn' fields.

        # Make sure unauthorized access fails
        r = self.app.get("/scoped1")
        self.assertEqual(r.status_code, httplib.UNAUTHORIZED)

        # Make sure unauthorized access succeedes with checking=off.
        app.config["OAUTH2_DEBUG_SKIPCHECK"] = True
        r = self.app.get("/scoped1")
        self.assertEqual(r.status_code, httplib.OK)
        self.assertEqual(r.data, "ok")
        app.config["OAUTH2_DEBUG_SKIPCHECK"] = False

        # Make sure access succeedes when issuer token has no scope defined and
        # scoped function doesn't define any
        headers = {"Authorization": "Bearer abc1"}
        r = self.app.get("/scoped_none", headers=headers)
        self.assertEqual(r.status_code, httplib.OK)
        self.assertEqual(r.data, "ok")

        # Make sure access fails when issuer token has no scope defined but
        # scoped function does.
        headers = {"Authorization": "Bearer abc2"}
        r = self.app.get("/scoped1", headers=headers)
        self.assertEqual(r.status_code, httplib.UNAUTHORIZED)


        # Now the token from the issuer will include a single scope.
        auth.token["scopes"] = "somescope.read.v1"


        # See if access succeedes when issuer token has the scope required
        # by the function.
        headers = {"Authorization": "Bearer abc3"}
        r = self.app.get("/scoped1", headers=headers)
        self.assertEqual(r.status_code, httplib.OK)
        self.assertEqual(r.data, "ok")

        # See if access fails when issuer token has not all the scopes required
        # by the function.
        headers = {"Authorization": "Bearer abc4"}
        r = self.app.get("/scoped2", headers=headers)
        self.assertEqual(r.status_code, httplib.UNAUTHORIZED)

        # Now the token from the issuer will include three scopes.
        auth.token["scopes"] = "otherscope somescope.read.v1 somescope.write.v1"

        # See if access succeedes when issuer token has all the scopes required
        # by the function.
        headers = {"Authorization": "Bearer abc5"}
        r = self.app.get("/scoped2", headers=headers)
        self.assertEqual(r.status_code, httplib.OK)
        self.assertEqual(r.data, "ok")

        # See if access fails when token issuer fails
        token = auth.token
        auth.token = {"error": "Issuer has issues."}
        headers = {"Authorization": "Bearer abcx"}
        r = self.app.get("/scoped_none", headers=headers)
        self.assertEqual(r.status_code, httplib.UNAUTHORIZED)
        auth.token = token

        # Put a bogus expiry date in token.
        auth.token["expiresOn"] = "this is not a date"

        # See if unparseable expiry date slides through.
        headers = {"Authorization": "Bearer abc6"}
        r = self.app.get("/scoped1", headers=headers)
        self.assertEqual(r.status_code, httplib.OK)
        self.assertEqual(r.data, "ok")

        # See if good expiration date slides through.
        auth.token["expiresOn"] = "2083-04-08T13:11:49.7150213Z"
        headers = {"Authorization": "Bearer abc7"}
        r = self.app.get("/scoped1", headers=headers)
        self.assertEqual(r.status_code, httplib.OK)
        self.assertEqual(r.data, "ok")

        # See if access fails when issuer returns expired token.
        auth.token["expiresOn"] = "1983-04-08T13:11:49.7150213Z"
        headers = {"Authorization": "Bearer abc8"}
        r = self.app.get("/scoped1", headers=headers)
        self.assertEqual(r.status_code, httplib.UNAUTHORIZED)

        # Set expiry date back to future.
        auth.token["expiresOn"] = "2083-04-08T13:11:49.7150213Z"


    def test_token_cache(self):

        # Test token caching:
        auth.prune_token_cache(0)
        self.assertEqual(len(auth.tokens), 0)

        # Check that tokens get cached through normal 'get' method.
        headers = {"Authorization": "Do normal check"}
        r = self.app.get("/scoped1", headers=headers)
        auth.pop_token_from_cache("Do normal check")
        self.assertEqual(len(auth.tokens), 0)

        # Generate double the entries the cache can hold. Mark the 'last_accessed'
        # dates with unique days so we can verify the pruning.
        checksize = 10
        year = 2050
        for i in xrange(checksize * 2):
            token = auth.token.copy()
            headers = {"Authorization": "Bearer #%s" % i}
            token["expiresOn"] = "{}-04-08T13:11:49.7150213Z".format(year+i)
            token["_expires_on"] = datetime(2020, 1, 1)
            last_accessed = datetime(2014, 1, i + 1)
            token["check"] = i  # Used to verify, see below
            auth.push_token_to_cache(token, "Auth key %s" % i, last_accessed)

        self.assertEqual(len(auth.tokens), checksize * 2)
        auth.prune_token_cache(checksize)
        self.assertEqual(len(auth.tokens), checksize)

        # Make sure the most recently accessed tokens are remaining
        self.assertEqual(len(auth.tokens), checksize)
        for i in xrange(checksize):
            token = auth.pop_token_from_cache("Auth key %s" % i)
            last_accessed = datetime(2014, 1, i + 1)
            self.assertTrue(token["check"] < checksize)


if __name__ == "__main__":

    unittest.main()

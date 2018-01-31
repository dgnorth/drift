# -*- coding: utf-8 -*-
import unittest

from driftconfig.util import get_drift_config
from drift.core.extensions.apikeyrules import get_api_key_rule
from drift.tests import DriftTestCase
from drift.systesthelper import setup_tenant


class ApiKeyRulesTest(DriftTestCase):

    @classmethod
    def setUpClass(cls):

        config_size = {
            'num_org': 5,
            'num_tiers': 2,
            'num_deployables': 4,
            'num_products': 2,
            'num_tenants': 2,
        }

        ts = setup_tenant(config_size=config_size, use_app_config=False)
        cls.ts = ts
        cls.tier_name = ts.get_table('tiers').find()[0]['tier_name']
        cls.product_name = ts.get_table('products').find()[0]['product_name']
        cls.tenant_name_1 = ts.get_table('tenant-names').find({'product_name': cls.product_name})[0]['tenant_name']
        cls.tenant_name_2 = ts.get_table('tenant-names').find({'product_name': cls.product_name})[1]['tenant_name']
        cls.deployable_1 = ts.get_table('deployables').find({'tier_name': cls.tier_name})[0]['deployable_name']
        cls.conf = get_drift_config(
            ts=ts,
            tenant_name=cls.tenant_name_1,
            tier_name=cls.tier_name,
            deployable_name=cls.deployable_1,
        )
        cls._add_rules()

    @classmethod
    def _add_rules(cls):
        """The location of this function is for convenience as the test function comes right after it."""

        # Make a few rules to test various cases:
        # Rule 1: reject clients 1.6.0 and 1.6.2 and ask them to upgrade.
        # Rule 2: redirect client 1.6.5 to another tenant.
        # Rule 3: always let client 1.6.5, and 1.6.6 pass through.
        # Rule 4: reject all clients with message "server is down".
        rules = [
            ('upgrade-client-1.6', ["1.6.0", "1.6.2"], 'reject', [404, {"action": "upgrade_client"}]),
            ('redirect-to-new-tenant', ["1.6.5"], 'redirect', cls.tenant_name_2),
            ('always-pass', ["1.6.5", "1.6.6"], 'pass', cls.tenant_name_1),
            ('downtime-message', [], 'reject', [503, {"message": "The server is down for maintenance."}]),
        ]

        api_key_rules = cls.ts.get_table('api-key-rules')

        for i, (rule_name, version_pattern, rule_type, custom) in enumerate(rules):
            row = api_key_rules.add({
                'product_name': cls.product_name,
                'rule_name': rule_name,
                'assignment_order': i,
                'version_patterns': version_pattern,
                'rule_type': rule_type,
            })
            if rule_type == 'reject':
                row['reject'] = {'status_code': custom[0], 'response_body': custom[1]}
            elif rule_type == 'redirect':
                row['redirect'] = {'tenant_name': custom}

            row['response_header'] = {'Test-Rule-Name': rule_name}  # To test response headers

        cls.ts.get_table('api-keys').add({
            'api_key_name': cls.product_name,
            'product_name': cls.product_name
        })

        cls.ts.get_table('api-keys').add({
            'api_key_name': 'custom-key',
            'key_type': 'custom',
        })

    def test_custom_key(self):
        # Only keys of type 'product' need to be associated with a product. Custom keys can
        # be universal and thus implicitly excempt from any product rule.
        headers = {
            "Drift-Api-Key": "custom-key",
        }
        url = "https://%s.kaleo.io/drift" % self.tenant_name_1
        rule = get_api_key_rule(headers, url, self.conf)
        self.assertIsNone(rule)

    def test_no_api_key_means_pass(self):
        # The reason for this is that some endpoints don't need
        # a key and this is enforced by nginx before it gets here
        url = "https://%s.kaleo.io/drift" % self.tenant_name_1
        rule = get_api_key_rule({}, url, self.conf)
        self.assertIsNone(rule)

    def test_pass_rule_passes(self):
        headers = {
            "Drift-Api-Key": "%s:%s" % (self.product_name, "1.6.6")
        }
        url = "https://%s.kaleo.io/drift" % self.tenant_name_1
        rule = get_api_key_rule(headers, url, self.conf)
        self.assertIsNotNone(rule)
        self.assertIsNone(rule["status_code"])

    def test_reject_rule_rejects(self):
        headers = {
            "Drift-Api-Key": "%s:%s" % (self.product_name, "1.6.1")
        }
        url = "https://%s.kaleo.io/drift" % self.tenant_name_1
        rule = get_api_key_rule(headers, url, self.conf)
        self.assertIsNotNone(rule)
        self.assertEqual(rule['status_code'], 503)
        self.assertEqual(rule['response_body']['message'], "The server is down for maintenance.")

    def test_upgrade_rule_passes_with_info(self):
        headers = {
            "Drift-Api-Key": "%s:%s" % (self.product_name, "1.6.0")
        }
        url = "https://%s.kaleo.io/drift" % self.tenant_name_1
        rule = get_api_key_rule(headers, url, self.conf)
        self.assertIsNotNone(rule)
        self.assertEqual(rule['status_code'], 404)
        self.assertEqual(rule['response_body']['action'], "upgrade_client")

    def test_redirect_rule_redirects(self):
        headers = {
            "Drift-Api-Key": "%s:%s" % (self.product_name, "1.6.5")
        }
        url = "https://%s.kaleo.io/drift" % self.tenant_name_1
        rule = get_api_key_rule(headers, url, self.conf)
        self.assertIsNotNone(rule)
        self.assertEqual(rule['status_code'], 307)
        self.assertEqual(rule['response_header']['Location'], "https://%s.kaleo.io/drift" % self.tenant_name_2)

    def test_redirect_rule_passes_when_redirected(self):
        headers = {
            "Drift-Api-Key": "%s:%s" % (self.product_name, "1.6.5")
        }
        url = "https://%s.kaleo.io/drift" % self.tenant_name_2
        rule = get_api_key_rule(headers, url, self.conf)
        self.assertIsNotNone(rule)
        self.assertIsNone(rule['status_code'])


if __name__ == '__main__':
    unittest.main()

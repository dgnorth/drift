# -*- coding: utf-8 -*-
"""
    drift - API key rules
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Implement api key rules for passing, redirecting or rececting requests based
    on product and version of the client.
"""
from __future__ import absolute_import
import logging
import httplib
from urlparse import urlparse, urlunparse

from flask import request, g, jsonify, make_response
from flask_restful import abort

from drift.utils import get_config


log = logging.getLogger(__name__)


def register_extension(app):
    @app.before_request
    def check_api_key_rules():
        # A note about availability of 'g.conf': The 'driftconfig' module makes this object
        # available, and as it is a 'resource' module, it is guaranteed to be executed before
        # any 'extension' module code.

        # We don't require the key to exist in the request header as it is usually
        # enforced by the api router. Some endpoints are actually "keyless". But if the
        # key does exist in the request header, we apply the rules accordingly.
        key = request.headers.get('Drift-Api-Key')
        if not key:
            return

        rule = get_api_key_rule(key, request.url, g.conf)
        if not rule:
            return

        # Update response header in the "after request" callback function further below.
        if 'response_header' in rule:
            g.update_response_header_api_rule = rule['response_header']

        if 'status_code' in rule:
            import json
            log.info("Applying api key rule %s", json.dumps(rule, indent=4))
            response = make_response(jsonify(rule['response_body']), rule['status_code'])
            return response

    @app.after_request
    def after_request_apply_api_rules(response):
        if hasattr(g, 'update_response_header_api_rule'):
            for k, v in g.update_response_header_api_rule.items():
                response.headers[k] = v

        return response


def get_api_key_rule(key, request_url, conf):
    # Looks up and matches an api key rule to a given key and client version.
    # Returns None if no rule or action is in effect, else a dict with the following
    # optional entries that should be used in response to the http request:
    # 'status_code', 'response_body' and 'response_header'.
    # If no 'status_code' is returned, the request should be processed further.

    if ':' in key:
        key, version = key.rsplit(':', 1)
    else:
        version = None

    def retval(status_code=None, message=None, description=None, rule=None):
        status_code = status_code or httplib.FORBIDDEN
        message = message or 'Forbidden'
        description = description or message
        response_body = {
            "error": {
                "code": "user_error",
                "description": description
            },
            "message": message,
            "status_code": status_code
        }

        return {
            'status_code': status_code,
            'response_body': response_body,
            'rule': rule,
            'api_key': key,
            'api_key_version': version,
        }

    # Fist look up the API key in our config.
    api_key = g.conf.table_store.get_table('api-keys').get({'api_key_name': key})
    if not api_key:
        return retval(description="API Key '{}' not found.".format(key))

    # See if the API key is active or not.
    if not api_key['in_use']:
        return retval(description="API Key '{}' is disabled.".format(key))

    # Match the API key to the product/tenant.
    product, tenant = g.conf.product, g.conf.tenant
    if api_key['product_name'] != product['product_name']:
        return retval(description="API Key '{}' is for product '{}'"
            " but current tenant '{}' is on product '{}'.".format(
                key, api_key['product_name'], tenant['tenant_name'], product['product_name']))

    # Now we apply the actual rules for this product.
    rules = g.conf.table_store.get_table('api-key-rules').find(
        {'product_name': product['product_name'], 'is_active': True})
    rules = sorted(rules, key=lambda rule: rule['assignment_order'])

    for rule in rules:
        patterns = rule['version_patterns']
        is_match = False

        # If no pattern is specified, it effectively means "match always".
        if not patterns:
            is_match = True

        # If the caller provided its version, we use it to match certain rules.
        if version:
            for pattern in patterns:
                if version.startswith(pattern):
                    is_match = True
                    break

        # If the rule did not match the client version, continue to next one.
        if not is_match:
            continue

        ret = retval(rule=rule)
        ret['response_header'] = rule.get('response_header', {})

        if rule['rule_type'] == 'pass':
            return ret

        # Mark response as json
        ret['response_header']['Content-Type'] = 'application/json'

        if rule['rule_type'] == 'reject':
            if 'reject' in rule:
                ret['response_body'] = rule['reject']['response_body']
                ret['status_code'] = rule['reject']['status_code']
            else:
                ret['response_body'] = {'message': 'Forbidden'}
                ret['status_code'] = httplib.FORBIDDEN
            return ret

        elif rule['rule_type'] == 'redirect':
            urlparts = urlparse(request_url)
            if '.' not in urlparts.hostname:
                return retval(
                    status_code=400,
                    message='Bad Request',
                    description="Can't redirect to new tenant when hostname is dotless.",
                    rule=rule,
                )

            redirect = rule['redirect']
            new_hostname = redirect['tenant_name'] + '.' + urlparts.hostname.split('.', 1)[1]
            url = request_url.replace(urlparts.hostname, new_hostname)
            ret['status_code'] = 307  # Temporary redirect
            ret['response_body'] = {'message': "Redirecting to tier '{}'.".format(redirect['tenant_name'])}
            ret['response_header']['Location'] = url

            return ret
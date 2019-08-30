# -*- coding: utf-8 -*-
"""
    drift - Tenancy logic
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Figure out which tenant is in play
"""
from __future__ import absolute_import

import os
import logging
import socket
import warnings

from flask import request, has_request_context
from werkzeug.local import LocalProxy


log = logging.getLogger(__name__)


def drift_init_extension(app, **kwargs):
    pass


def get_tenant_name(request_headers=None):
    """Figure out tenant name in the following order:
    1. Tenant name explicitly specified in request header under the key 'Drift-Header'.
    2. Tenant name is the left most part of the host name specified in the request header.
    3. Default tenant name is specified in environment variable 'DRIFT_DEFAULT_TENANT'.
    """
    if request_headers:
        if 'Drift-Tenant' in request_headers:
            return request_headers['Drift-tenant']
        if 'Host' in request_headers:
            host_parts = split_host(request_headers['Host'])
            if host_parts['tenant']:
                return host_parts['tenant']

    return os.environ.get('DRIFT_DEFAULT_TENANT')


# Flask specific block begins
def _flask_get_tenant_name():
    """Calls get_tenant_name with request header and host if applicable.
    """
    request_headers = request.headers if has_request_context() else None
    return get_tenant_name(request_headers)


current_tenant_name = LocalProxy(_flask_get_tenant_name)


# Deprecated name as it's a bit misleading.
def _get_tenant_from_hostname(*args, **kw):
    # warnings.warn(
    #     "'tenant_from_hostname' has been renamed 'current_tenant_name'.",
    #     DeprecationWarning,
    #     stacklevel=2
    # )
    return _flask_get_tenant_name()

tenant_from_hostname = LocalProxy(_get_tenant_from_hostname)
# Flask specific block ends


def split_host(host):
    """Split 'host' into tenant, domain and port if possible."""
    ret = {
        'host': host,
        'tenant': None,
        'domain': None,
        'port': None,
    }

    # IPv6 barf because of https://tools.ietf.org/html/rfc3986#section-3.2.2
    if '[' in host and ']' in host:
        return ret  # Quickly and dirtily assume IPv6

    if ':' in host:
        ret['host'], ret['port'] = host.split(':', 1)
    if '.' in ret['host'] and not _is_valid_ipv4_address(ret['host']):
        ret['tenant'], ret['domain'] = host.split('.', 1)

    return ret


def _is_valid_ipv4_address(address):
    try:
        socket.inet_pton(socket.AF_INET, address)
    except AttributeError:  # no inet_pton here, sorry
        try:
            socket.inet_aton(address)
        except socket.error:
            return False
        return address.count('.') == 3
    except socket.error:  # not a valid address
        return False

    return True


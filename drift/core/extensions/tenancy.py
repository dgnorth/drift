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

from flask import request, _app_ctx_stack as stack
from werkzeug.local import LocalProxy


log = logging.getLogger(__name__)


def get_tenant_from_hostname(*args, **kw):
    ctx = stack.top
    if ctx is not None:
        if not hasattr(ctx, 'current_tenant'):
            ctx.current_tenant = _figure_out_tenant()
        return ctx.current_tenant
    else:
        # Not in a Flask request context, so the only way to specify any
        # tenant is using the environment variable.
        return os.environ.get('DRIFT_DEFAULT_TENANT')


tenant_from_hostname = LocalProxy(get_tenant_from_hostname)


def _figure_out_tenant():
    """
    Figure out the current tenant name. It's either set through an environment variable
    'DRIFT_DEFAULT_TENANT', or it's the left-most part of the host name.
    """
    tenant_name = os.environ.get('DRIFT_DEFAULT_TENANT')

    # Figure out tenant. Normally the tenant name is embedded in the hostname.
    host = str(request.headers.get("Host"))
    if '.' in host and not _is_valid_ipv4_address(host) and not _is_valid_ipv6_address(host):
        tenant_name, domain = host.split('.', 1)

    return tenant_name


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


def _is_valid_ipv6_address(address):
    try:
        socket.inet_pton(socket.AF_INET6, address)
    except socket.error:  # not a valid address
        return False
    return True

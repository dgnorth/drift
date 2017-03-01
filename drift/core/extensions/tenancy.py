# -*- coding: utf-8 -*-
"""
    drift - Tenancy logic
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Figure out which tenant is in play
"""
from __future__ import absolute_import

import os
import logging

from flask import request, _app_ctx_stack as stack
from werkzeug.local import LocalProxy


log = logging.getLogger(__name__)


def get_current_tenant(*args, **kw):
    ctx = stack.top
    if ctx is not None:
        if not hasattr(ctx, 'current_tenant'):
            ctx.current_tenant = _figure_out_tenant()
        return ctx.current_tenant
    else:
        # Not in a Flask request context, so the only way to specify any
        # tenant is using the environment variable.
        return os.environ.get('default_drift_tenant')


current_tenant = LocalProxy(get_current_tenant)


def _figure_out_tenant():
    """
    Figure out the current tenant name. It's either set through an environment variable
    'default_drift_tenant', or it's the left-most part of the host name.
    """
    tenant_name = os.environ.get('default_drift_tenant')

    # Figure out tenant. Normally the tenant name is embedded in the hostname.
    host = request.headers.get("Host")
    # Two dots minimum required if tenant is to be specified in the hostname.
    host_has_tenant = False
    if host and host.count('.') >= 2:
        host_has_tenant = True
        for l in host.split(":")[0].split("."):
            try:
                int(l)
            except:
                break
        else:
            host_has_tenant = False

    if host_has_tenant:
        tenant_name, domain = host.split('.', 1)

    return tenant_name


# -*- coding: utf-8 -*-


# HACK: Temporary placeholder file until billion imports have been fixed up

def register_endpoints(f):
    from drift.core.extensions.urlregistry import register_endpoints as reg
    return reg(f)


# -*- coding: utf-8 -*-
import warnings

warnings.warn(
    "please import drift.core.extensions.urlregistry instead of drift.urlregistry.",
    DeprecationWarning,
    stacklevel=2)


# HACK: Temporary placeholder file until billion imports have been fixed up
def register_endpoints(f):
    from drift.core.extensions.urlregistry import register_endpoints as reg
    return reg(f)

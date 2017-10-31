import warnings

class ExtDeprecationWarning(DeprecationWarning):
    pass

warnings.simplefilter('always', ExtDeprecationWarning)

warnings.warn(
    "Importing drift.auth.jwtchecker is deprecated, use drift.core.extensions.jwt instead.",
    ExtDeprecationWarning
    )

from drift.core.extensions.jwt import *

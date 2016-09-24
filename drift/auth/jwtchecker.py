import warnings

class ExtDeprecationWarning(DeprecationWarning):
    pass

warnings.simplefilter('always', ExtDeprecationWarning)

warnings.warn(
    "Importing drif.auth.jwtchecker is deprecated, use drift.core.extension.jwt instead.",
    ExtDeprecationWarning
    )

from drift.core.extensions.jwt import *

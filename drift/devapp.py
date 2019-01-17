# Deprecated
import warnings
from drift.contrib.flask.devapp import app
warnings.warn(
    "Use drift.contrib.flask.devapp instead of drift.devapp.",
    DeprecationWarning,
    stacklevel=2,
)

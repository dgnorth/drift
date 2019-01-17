# Deprecated
import warnings
from drift.contrib.flask.plainapp import app
warnings.warn(
    "Use drift.contrib.flask.plainapp instead of drift.uwsgiboot.",
    DeprecationWarning,
    stacklevel=2,
)

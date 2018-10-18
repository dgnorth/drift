# -*- coding: utf-8 -*-
import logging


# The logger is already configured at this point by the lambda thunker so we need to reset it.
root = logging.getLogger()
if root.handlers:
    for handler in root.handlers:
        root.removeHandler(handler)

logging.basicConfig(format='[%(levelname)s] %(name)s: %(message)s', level=logging.INFO)


try:
    from drift.flaskfactory import drift_app
    app = drift_app()
except Exception:
    logging.exception("Can't create Drift app object.")

[![Build Status](https://travis-ci.org/dgnorth/drift.svg?branch=master)](https://travis-ci.org/dgnorth/drift)
[![codecov](https://codecov.io/gh/dgnorth/drift/branch/develop/graph/badge.svg)](https://codecov.io/gh/dgnorth/drift)


# drift
Micro framework for SOA based applications.


Drift is a high level web framework to implement REST based web services and contains tools for deployment, operation and total lifecycle management of those services.

## Installation:
For developer setup [pipenv](https://docs.pipenv.org/) is used to set up virtual environment and install dependencies.

```bash
pip install --user pipenv
pipenv --two
pipenv install -d -e ".[aws,dev]"
```
This installs *drift* in editable mode with full CLI support.

Note: Development on this library makes most sense within a context of a project that uses it (like *drift-base*).

## Acknowledgement

The project is generously supported by a grant from the Icelandic Technology Development Fund.
![https://www.rannis.is/sjodir/rannsoknir/taeknithrounarsjodur](img/tsj_en_logo.jpg)
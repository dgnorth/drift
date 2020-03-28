[![Build Status](https://travis-ci.org/dgnorth/drift.svg?branch=develop)](https://travis-ci.org/dgnorth/drift)
[![codecov](https://codecov.io/github/dgnorth/drift/branches/develop/graph/badge.svg)](https://codecov.io/github/dgnorth/drift/branches/develop)
[![Latest version on
PyPi](https://badge.fury.io/py/python-drift.svg)](https://badge.fury.io/py/python-drift)

# drift
Micro framework for SOA based applications.


Drift is a high level web framework to implement REST based web services and contains tools for deployment, operation and total lifecycle management of those services.

## Installation:

This library is not installed directly. (WORK IN PROGRESS). 

## Developer setup:

The following instructions are for setting up your workstation for local development.

### Prepare your workstation:

You need to have [pipenv](https://github.com/pypa/pipenv), [PostgreSQL](https://www.postgresql.org/) and [Redis](https://redis.io/) installed.

#### OSX:
```bash
pip install --user pipenv
brew install postgresql
brew install redis
```

#### Linux:
```bash
pip install --user pipenv
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
sudo apt-get install redis-server
```

#### Windows:
```bash
pip install pipenv

# Install and run Redis server
choco install redis-64
redis-server

# Install and run PostgreSQL server
choco install postgresql  # When prompted for pwd, specify 'postgres'.
```

#### Setup postgresql
Drift assumes a default password of `postgres` for the database superuser.  The default install on Linux typically uses an empty one.  To set a password:
```bash
sudo -u postgres psql postgres
postgres=# \\password postgres
(set password to 'postgres')
postres=# \\q
```

### Prepare for local unittesting of the drift module
This module can be tested on its own, but it requires the [drift-config](https://github.com/dgnorth/drift-config) project as a dependency.

Assuming that *drift-config* has been cloned to the same level as this one, do the following to create
a virtualenv:
```bash
pipenv --two # or --three
pipenv install -e "../drift-config[s3-backend,redis-backend]"
pipenv install -e ".[aws,test]"
```
This creates a Pipfile and a Pipfile.lock for local development.

You can now run unittests, e.g. by running `pipenv run python -m unittest discover`

If you want to switch to a different version of Python remove the `Pipfile` entirely and re-do the above steps with the appropriate switch for python version.
You may also need to remove `.pyc` files, e.g. with a command such as:
```bash
find . -name "*.pyc" -exec rm "{}" ";"
```

### Prepare a project for local development

Drift comes with some base services in a project called [drift-base](https://github.com/dgnorth/drift-base). Here is an example of how to set up that project for local development. The same method applies for all other Drift based projects.

```bash
# Get the drift-base project from Github
git clone https://github.com/dgnorth/drift-base.git
cd drift-base

# Set up virtual environment and install dependencies
pipenv install --dev

# Activate the virtualenv and set up local development environment
pipenv shell
dconf developer
```
##### HINT:
It's very convenient to refresh the local environment and run a server in one go. (Just make sure the virtualenv is active):

```bash
dconf developer --run
```



## Acknowledgement

The project is generously supported by a grant from the Icelandic Technology Development Fund.
![https://www.rannis.is/sjodir/rannsoknir/taeknithrounarsjodur](img/tsj_en_logo.jpg)

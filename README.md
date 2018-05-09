[![Build Status](https://travis-ci.org/dgnorth/drift.svg?branch=master)](https://travis-ci.org/dgnorth/drift)
[![codecov](https://codecov.io/gh/dgnorth/drift/branch/develop/graph/badge.svg)](https://codecov.io/gh/dgnorth/drift)


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
pip install --user pipenv

# Install and run Redis server
choco install redis-64
redis-server

# Install and run PostgreSQL server
choco install postgresql  # When prompted for pwd, specify 'postgres'.
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
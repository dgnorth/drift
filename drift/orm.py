# -*- coding: utf-8 -*-
"""
This module contains generic and application-level sql logic.
"""

from contextlib import contextmanager
from flask import g
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base, declared_attr

import datetime
from sqlalchemy import Column, DateTime

import logging
log = logging.getLogger(__name__)

utc_now = text("(now() at time zone 'utc')")

Base = declarative_base()


def _get_db_connection_info():
    """
    Return tenant specific DB connection info, if available, else use one that's
    specified for the tier.
    """
    ci = g.conf.tier.get('db_connection_info')
    if not ci and g.conf.tenant:
        ci = g.conf.tenant.get('db_connection_info')

    return ci

def get_sqlalchemy_session(conn_string=None):
    """
    Return an SQLAlchemy session for the specified DB connection string
    """
    if not conn_string:
        #from drift.tenant import get_connection_string
        #conn_string = get_connection_string(g.driftenv_objects)
        ci = _get_db_connection_info()
        if not ci:
            return

        conn_string = '{driver}://{user}:{password}@{server}/{db}'.format(
            driver=ci.get("driver", "postgresql"),
            user=ci.get("user", "zzp_user"),
            password=ci.get("password", "zzp_user"),
            server=ci["db_server"],
            db=ci["db_name"]
        )

    engine = create_engine(conn_string, echo=False, poolclass=NullPool)
    session_factory = sessionmaker(bind=engine, expire_on_commit=True)
    session = session_factory()
    session.expire_on_commit = False
    return session


@contextmanager
def sqlalchemy_session(conn_string=None):
    session = get_sqlalchemy_session(conn_string)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


class ModelBase(Base):
    __abstract__ = True

    # we use this declared_attr method to ensure that these automatic columns are placed at the end
    @declared_attr
    def create_date(cls):
        return Column(DateTime, nullable=False, server_default=utc_now, index=False)

    @declared_attr
    def modify_date(cls):
        return Column(DateTime, nullable=False, server_default=utc_now,
                      onupdate=datetime.datetime.utcnow)

    def as_dict(self):
        """
        Returns the data for the row as a dictionary
        """
        columns = self.__table__.columns._data.keys()
        data = {}
        for c in columns:
            data[c] = getattr(self, c)
        return data

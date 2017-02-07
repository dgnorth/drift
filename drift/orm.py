# -*- coding: utf-8 -*-
"""
This module contains generic and application-level sql logic.
"""

from contextlib import contextmanager
from flask import g, current_app
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base, declared_attr

import datetime
from sqlalchemy import Column, DateTime

from drift.core.resources.postgres import format_connection_string
import logging
log = logging.getLogger(__name__)

utc_now = text("(now() at time zone 'utc')")

Base = declarative_base()

#! TODO: Move contents to resources.postgres

def get_sqlalchemy_session(conn_string=None):
    """
    Return an SQLAlchemy session for the specified DB connection string
    """
    if not conn_string:
        ci = None
        if g.conf.tenant:
            ci = g.conf.tenant.get('postgres')
        if not ci:
            return

        # HACK: Ability to override Postgers hostname
        if current_app.config.get('drift_use_local_servers', False):
            ci['server'] = 'localhost'
        else:
            bork
        conn_string = format_connection_string(ci)

    log.debug("Creating sqlalchemy session with connection string '%s'", conn_string)
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

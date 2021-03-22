# -*- coding: utf-8 -*-
"""
This module contains generic and application-level sql logic.
"""
import datetime
import logging

from sqlalchemy import text, inspect
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy import Column, DateTime

log = logging.getLogger(__name__)

utc_now = text("(now() at time zone 'utc')")

Base = declarative_base()

# ! TODO: Move contents to resources.postgres
# These are here due to importing from other modules
from drift.core.resources.postgres import get_sqlalchemy_session, sqlalchemy_session  # noqa: F401


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
        return {c.key: getattr(self, c.key)
                for c in inspect(self).mapper.column_attrs}

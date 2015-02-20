# -*- coding: utf-8 -*-
"""
    EventLog
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Helper for writing eventLogs

    :copyright: (c) 2014 CCP
"""
import logging

eventLog_handler = logging.getLogger('eventLog')

def log_event(event_name, pilot_id, *args, **kwargs):
    """
    (Ab)Uses the python logging framework to write out json-formatted 
    log files in eventLog specification.
    Call example:
     drift.eventlog.log_event("myFacility::MyEvent", pilot_id, something=1, something_else=2)
    """
    extra = {"eventlog_%s" % k:v for k, v in kwargs.items()}
    extra.update({"pilot_id": pilot_id})
    eventLog_handler.info(event_name, extra=extra)

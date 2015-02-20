# -*- coding: utf-8 -*-
"""
    Status Monitor utility for Flask Service applications.
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Keeps track of static service info and live stats.
    REST API is implemented in :module:`restapi.servicestatus`.

    :copyright: (c) 2014 CCP
"""
from os.path import join, exists
import json
import logging
from datetime import datetime
import copy
from collections import defaultdict

log = logging.getLogger(__name__)


class StatusMonitor(object):
    """
    Keeps track of service status flags and errors.
    """
    def __init__(self, app=None):
        self.app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        app.extensions['statusmonitor'] = self
        self._services = {}  # Service name: ServiceStatus instance
        self._start_time = datetime.utcnow().isoformat("T") + "Z"

    def get_service_status(self, service_name, template=None):
        """
        Returns an instance of ServiceStatus for 'service_name'.
        If .json file for 'service_name' is not found, then '_template' must
        contain a dict representing the static part. (Used for unit tests).
        """
        if service_name in self._services:
            return self._services[service_name]

        # Initialize service status info
        service_file = join(
            self.app.instance_path, "..", "config", service_name + ".json")

        if not exists(service_file):
            if template is None:
                raise RuntimeError(
                    "Service {!r} has no config file {!r}.".format(
                        service_name, service_file))
            si = template
        else:
            with open(service_file) as f:
                si = json.load(f)

        if service_name != si["name"]:
            raise RuntimeError(
                "'service_name' and static info differ, {!r} != {!r}".format(
                    service_name, si["name"]))

        si["start_time"] = self._start_time
        self._services[service_name] = ServiceStatus(si)
        return self._services[service_name]


class ServiceStatus(object):
    """Manage static and dynamic service info."""

    def __init__(self, si):
        self._static = si
        self._dependencies = defaultdict(dict)  # tenant:dep_name: Status
        self._tenants = set()

    def add_tenant(self, tenant):
        """
        Add a tenant name to the list of tenants or environments being served
        by this service.
        """
        self._tenants.add(tenant)

    def get_service_info(self, tenant=None):
        """Returns static and status info."""

        # First get a copy of the static part
        si = copy.deepcopy(self._static)

        # Add dynamic info
        si["tenants"] = list(self._tenants)
        si["current_tenant"] = tenant

        # Combine static dependency info with dynamic one.
        deps = {dep["name"]: dep for dep in si["dependencies"]}
        deps.update(self._dependencies[tenant])
        deps = deps.values()
        si["dependencies"] = deps

        # If any of critical dependencies have status 'warning' or 'error', it
        # will be reflected as this services global status.
        statusflags = [dep.get("status", "ok") for dep in deps]
        if "error" in statusflags:
            si["status"] = "error"
        elif "warning" in statusflags:
            si["status"] = "warning"
        else:
            si["status"] = "ok"

        return si

    def update_status(
            self, status,
            dependency_name, tenant=None,
            last_checked=None, check_duration=None, last_error=None, **kw):
        """
        Set 'status' on dependency item 'dependency_name'.
        If this is a tenant specific dependency, then the 'tenant'
        argument must be set.

        If 'last_checked' is set, it's a ISO8601 string. If not, current time
        is used.

        Optional 'check_duration' describes how long the check took in seconds.
        Optional 'last_error' describes last warning or error.
        'kw' can contain additional key-values to set on the dependency.
        """
        if status not in ["ok", "warning", "error"]:
            raise RuntimeError(
                "'status' is {!r} which is no good.".format(status))

        dep = self._dependencies[tenant].get(dependency_name)
        if not dep:
            # Make a new dependency entry, based on a static one if available.
            for dep in self._static["dependencies"]:
                if dep["name"] == dependency_name:
                    dep = copy.deepcopy(dep)
                    break
            else:
                # Make a fresh one from scratch. Only the name is needed.
                dep = {"name": dependency_name}

            self._dependencies[tenant][dependency_name] = dep

        dep["status"] = status

        if last_checked is None:
            dep["last_checked"] = datetime.utcnow().isoformat("T") + "Z"
        else:
            dep["last_checked"] = last_checked

        if check_duration is None:
            dep.pop("check_duration", None)
        else:
            dep["check_duration"] = check_duration

        if last_error is None:
            dep.pop("last_error", None)
        else:
            dep["last_error"] = last_error

        # Finally, add additional key-values.
        dep.update(kw)

def register_extension(app):
    app.statusmonitor = StatusMonitor(app)

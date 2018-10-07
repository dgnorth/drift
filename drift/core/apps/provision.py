# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging
import importlib

from six.moves import http_client

from flask import Blueprint, current_app, url_for, abort, request, g
from flask_restful import Api, Resource, reqparse

from driftconfig.config import TSTransaction

from driftconfig.util import get_drift_config, define_tenant, provision_tenant_resources
from driftconfig.relib import create_backend, get_store_from_url

from drift.core.extensions.schemachecker import simple_schema_request

log = logging.getLogger(__name__)
bp = Blueprint("admin", __name__)
api = Api(bp)


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)


class AdminProvisionAPI(Resource):

    no_jwt_check = ["POST"]

    #@requires_roles("service")
    @simple_schema_request({
        "provisioners": {"type": "array", },
    }, required=[])
    def post(self):
        tenant_name = g.conf.tenant_name['tenant_name']
        tier_name = g.conf.tier['tier_name']

        # quick check for tenant state before downloading config
        if g.conf.tenant["state"] != "initializing":
            abort(http_client.BAD_REQUEST, message="You can only provision tenants which are in state 'initializing'. Tenant '%s' is in state '%s'" % (tenant_name, g.conf.tenant["state"]))

        args_per_provisioner = {}
        if request.json:
            for arg in request.json.get("provisioners", {}):
                if "provisioner" not in arg or "arguments" not in arg:
                    log.warning("Provisioner argument missing 'provisioner' or 'arguments'")
                    continue
                args_per_provisioner[arg["provisioner"]] = arg["arguments"]

        origin = g.conf.domain['origin']
        ts = get_store_from_url(origin)
        conf = get_drift_config(
            ts=ts,
            tenant_name=tenant_name,
            tier_name=tier_name,
            deployable_name=current_app.config['name']
        )


        if conf.tenant["state"] != "initializing":
            raise RuntimeError("Tenant unexpectedly found in state '%s': %s" % (conf.tenant["state"], conf.tenant))

        resources = current_app.config.get("resources")
        for module_name in resources:
            m = importlib.import_module(module_name)
            if hasattr(m, "provision"):
                provisioner_name = m.__name__.split('.')[-1]
                log.info("Provisioning '%s' for tenant '%s' on tier '%s'", provisioner_name, tenant_name, tier_name)

                args = args_per_provisioner.get(provisioner_name, {})
                m.provision(conf, args)

        # Mark the tenant as ready
        conf.tenant["state"] = "active"

        # Save out config
        log.info("Saving config to %s", origin)
        origin_backend = create_backend(origin)
        origin_backend.save_table_store(ts)

        local_origin = 'file://~/.drift/config/' + g.conf.domain['domain_name']
        log.info("Saving config to %s", local_origin)
        local_store = create_backend(local_origin)
        local_store.save_table_store(ts)

        # invalidate flask config
        current_app.extensions['driftconfig'].refresh()

        return "OK"


api.add_resource(AdminProvisionAPI, "/provision")


class AdminProvisionAPI2(Resource):

    no_jwt_check = ["GET", "POST"]

    get_args = reqparse.RequestParser()
    get_args.add_argument("tenant_name", type=str)

    @simple_schema_request({
        "tenant_name": {"type": "string"}
    }, required=[])
    def get(self):
        args = self.get_args.parse_args()
        tenant_name = args.tenant_name
        if tenant_name:
            crit = {'tenant_name': tenant_name}
        else:
            crit = {'tier_name': g.conf.tier['tier_name']}

        tenants = g.conf.table_store.get_table('tenants').find(crit)
        return tenants

    @simple_schema_request({
        "tenant_name": {"type": "string"},
        "preview": {"type": "boolean"},
    }, required=[])
    def post(self):
        tenant_name = request.json.get('tenant_name') if request.json else None
        preview = request.json.get('preview', False) if request.json else False
        result = []

        with TSTransaction(commit_to_origin=not preview) as ts:

            if tenant_name:
                crit = {'tenant_name': tenant_name}
            else:
                crit = {'tier_name': g.conf.tier['tier_name']}

            for tenant_info in ts.get_table('tenant-names').find(crit):
                tenant_name = tenant_info['tenant_name']
                # Refresh for good measure
                define_tenant(
                    ts=ts,
                    tenant_name=tenant_name,
                    product_name=tenant_info['product_name'],
                    tier_name=tenant_info['tier_name'],
                )

                report = provision_tenant_resources(ts=ts, tenant_name=tenant_name, preview=preview)
                result.append(report)

        return result


api.add_resource(AdminProvisionAPI2, "/admin/provision")

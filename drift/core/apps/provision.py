# -*- coding: utf-8 -*-
"""
Schames listing APIs
"""
import logging
import importlib

from six.moves import http_client

from flask import current_app, request, g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
import marshmallow as ma

from driftconfig.config import TSTransaction

from driftconfig.util import get_drift_config, define_tenant, provision_tenant_resources
from driftconfig.relib import create_backend, get_store_from_url

from drift.core.extensions.schemachecker import simple_schema_request

log = logging.getLogger(__name__)
bp_provision = Blueprint("provision", "Provision", url_prefix='/provision', description="The provision API")
bp_admin = Blueprint("admin", "Admin Provision", url_prefix='/admin', description="The admin Provision API")


class AdminProvisionRequestSchema(ma.Schema):
    provisioners = ma.fields.Dict(description="The provisioners")


class AdminProvision2GetSchema(ma.Schema):
    tenant_name = ma.fields.Str(description="Name of the tenant to provision")

class AdminProvision2PostSchema(ma.Schema):
    tenant_name = ma.fields.Str(description="Name of the tenant to provision")
    preview = ma.fields.Boolean(description="Just check")


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp_provision)
    api.register_blueprint(bp_admin)


@bp_provision.route('', endpoint='provision_admin')
class AdminProvisionAPI(MethodView):

    no_jwt_check = ["POST"]

    @bp_provision.arguments(AdminProvisionRequestSchema)
    def post(self, args):
        """
        Provision tenant

        <ADD DESCRIPTION>
        """
        tenant_name = g.conf.tenant_name['tenant_name']
        tier_name = g.conf.tier['tier_name']

        # quick check for tenant state before downloading config
        if g.conf.tenant["state"] != "initializing":
            abort(http_client.BAD_REQUEST, message="You can only provision tenants which are in state 'initializing'. Tenant '%s' is in state '%s'" % (tenant_name, g.conf.tenant["state"]))

        args_per_provisioner = {}
        if request.json:
            for arg in args.get("provisioners", {}):
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

@bp_admin.route('/provision', endpoint='provision')
class AdminProvisionAPI2(MethodView):

    no_jwt_check = ["GET", "POST"]

    @bp_admin.arguments(AdminProvision2GetSchema)
    def get(self, args):
        """
        Get provisioned tenant

        <ADD DESCRIPTION>
        """
        tenant_name = args.get('tenant_name')
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
    @bp_admin.arguments(AdminProvision2PostSchema)
    def post(self, args):
        """
        Provision tenant number 2

        <ADD DESCRIPTION>
        """
        tenant_name = args.get('tenant_name') if request.json else None
        preview = args.get('preview', False) if request.json else False
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

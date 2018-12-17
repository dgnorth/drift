from click import echo, secho
from alembic import context
from sqlalchemy import pool, create_engine

from drift.flaskfactory import drift_app
from drift.core.resources.postgres import format_connection_string, connect
from drift.utils import get_tier_name, get_config
from drift.orm import Base


MASTER_USERNAME = 'postgres'
MASTER_PASSWORD = 'postgres'


def run_migrations():

    conf = get_config()
    pick_tenant = context.get_x_argument(as_dictionary=True).get('tenant')
    dry_run = context.get_x_argument(as_dictionary=True).get('dry-run')

    for tenant in conf.tenants:
        tenant_name = tenant['tenant_name']
        secho("Tenant '{}': ".format(tenant_name), nl=False)
        pginfo = tenant.get('postgres')
        if not pginfo:
            secho("Missing postgres resource info!", fg='red')
            continue

        if pick_tenant and tenant_name != pick_tenant:
            secho("Skipping this tenant.", fg='yellow')
            continue

        if dry_run:
            secho("Dry run, not taking any further actions.")

        if context.is_offline_mode():
            sql_filename = '{}.{}.sql'.format(conf.tier['tier_name'], tenant_name)
            echo("Writing SQL code to ", nl=False)
            secho(sql_filename, fg='magenta')
            with open(sql_filename, 'w') as out:
                context.configure(
                    url=format_connection_string(pginfo),
                    output_buffer=out,
                    target_metadata=Base.metadata,
                    process_revision_directives=process_revision_directives,
                    compare_type=True,
                )

                with context.begin_transaction():
                    context.run_migrations()
        else:
            # HACK WARNING! This has to come from the config
            pginfo['username'] = MASTER_USERNAME
            pginfo['password'] = MASTER_PASSWORD

            secho("\n\tConnecting {server}:{port}/{database}...".format(**pginfo), nl=False)

            engine = connect(pginfo, connect_timeout=3.0)
            try:
                connection = engine.connect()
            except Exception as e:
                if 'timeout expired' in str(e):
                    secho("ERROR: {}".format(e), fg='red')
                    continue
                else:
                    raise

            transaction = connection.begin()
            secho("OK", fg="green")
            secho("\tRunning migration...", nl=False)
            context.configure(
                connection=connection,
                upgrade_token="%s_upgrades" % tenant_name,
                downgrade_token="%s_downgrades" % tenant_name,
                target_metadata=Base.metadata,
            )
            context.run_migrations()
            transaction.commit()
            connection.close()
            secho("OK", fg="green")


def process_revision_directives(context, revision, directives):
    if context.config.cmd_opts.autogenerate:
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []


def run():

    app = drift_app()
    run_migrations()
    del app

# drift configuration management

Configuration management and provisioning logic has been refactored quite extensively. Here is an overview of the important bits:

**Registering deployables and creating and provisioning tenants is now completely automated!** There is no longer any manual step involved. There is no need to edit the config json files by hand.

Another huge update is how deployable registration is maintained. If a deployable is added or removed, all related configuration entries are updated automatically. This applies to tier configuration as well as product configuration. If a new deployable is added to a product, all current tenants for this product will be automatically updated and provisioned. Same happens if a deployable is removed.


## Drift deployable registration
Drift deployables are now self-registering. It is done using a CLI or REST API.

Example:

```bash
drift-admin --config dgnorth register --tiers DEVNORTH
```
This command creates or updates the registration info for this deployable in Drift config database. It will also create or update resource registration and tier default value registration.

If a default value is not available for some resource attributes the command will prompt the user. This includes attributes like Postgres and Redis host names.

## New resource modules
*jwtsession* and *apitarget* are new resource modules. They take care of creating or updating the drift config with public and private keys and api routes and such.

There is also additional support for all kinds of legacy stuff like *service_user*. This is all handled in a clean and robust manner.


## Tenant creation and provisioning
Tenants are created or updated using a CLI or REST API.

The command line suite for tenant management is now in *driftconfig* which simplifies things quite a bit.

#### Create a new tenant
To create a new tenant (or refresh its configuration):

```bash
driftconfig create-tenant <tenant name> <product> <tier>
```

If the *create-tenant* is called again using the same arguments, it will simply refresh the tenant configuration (see below).

#### Refresh tenant configuration
If there are any changes to product registration or deployable resource logic, all relevant tenants need to have their configuration updated. This is fully automatic now but needs to be triggered explicitly. Here's how to refresh a tenant's config using command line:

```bash
 driftconfig refresh-tenant <tenant name>
```

#### Provision resources for a tenant
Provisioning the actual resources for a tenant using the comand line assumes couple of things:

 - The deployable(s) used by the tenants product must be installed on the same machine.
 - Any cloud based resources that are used(like Postgres and Redis DB on AWS) must be accessible from the same machine.

The command line for it looks like this:

```bash
driftconfig provision-tenant <tenant name>
```

The *provision-tenant* command will always refresh the tenant configuration before calling the provisioning function.

This command is stateless in itself as the state of the tenant and its resources is stored in the configuration. This command can be called multiple times and at any time.


## Use case - Deploy Kaleo Web

Register the Kaleo deployable if it hasn't been done already:

```bash
# In kaleo-web folder:
drift-admin --config dgnorth register --tiers DEVNORTH
driftconfig assign-tier --config dgnorth kaleo-web --tiers DEVNORTH
```		

Next step is to create the Kaleo tenant itself and provision its resources:

```bash
driftconfig create-tenant --config dgnorth kaleo dg-kaleo DEVNORTH

# Assume we have network access to DEVNORTH resources
driftconfig provision-tenant --config dgnorth dg-kaleo
```

The deployable has to be running on DEVNORTH. This takes care of it:

```bash
# In kaleo-web folder:
drift-admin --config dgnorth --tier DEVNORTH ami bake
drift-admin --config dgnorth --tier DEVNORTH ami run
```

#### IMPORTANT:
The cache is not updated automatically on DEVNORTH due to limitations with Zappa and global namespaces (Run `driftconfig cache dgnorth` just in case). 

Moving on...


To see what's going on:

```bash
export PRODUCT_NAME=dg-kaleo
export DEPLOYABLE=kaleo-web
curl -s https://devnorth.dg-api.com/api-router/ | python -c "import sys, json, pprint; d = json.load(sys.stdin); print json.dumps([p for p in d['products'] if p['product_name'] == '${PRODUCT_NAME}'], indent=4); print json.dumps([p for p in d['deployables'] if p['name'] == '${DEPLOYABLE}'], indent=4)"
```

This should yield the following result:

```json
[
    {
        "organization_name": "directivegames", 
        "state": "active", 
        "tenants": [
            "dg-kaleo"
        ], 
        "product_name": "dg-kaleo", 
        "deployables": [
            "kaleo-web"
        ]
    }
]
[
    {
        "requires_api_key": false, 
        "upstream_servers": [
            [
                {
                    "status": "online", 
                    "version": "0.2.0", 
                    "health": "ok", 
                    "address": "10.50.2.156:10080"
                }
            ]
        ], 
        "api": "kaleo", 
        "is_active": true, 
        "name": "kaleo-web"
    }
]
```

Kaleo Web is now running on DEVNORTH:
[https://dg-kaleo.dg-api.com/kaleo/](https://dg-kaleo.dg-api.com/kaleo/)

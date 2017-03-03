# Drift TutoralThis tutorial takes you through the initial steps in setting up a Drift development environment and run the basic Drift services on your local workstation.## Create a new everything from scratch.Scenario: A game company called **KneeDeep Studios** with a title called **Snowfall**.### Install Pre-requisites> Note: Drift is Python based. [Virtual envs](http://docs.python-guide.org/en/latest/dev/virtualenvs/) are nice. It's a good idea to `pip install virtualenv virtualenvwrapper` and do `mkvirtualenv drift` and work within that virtual environment.For local development, the following packages are needed:
#### OSX```bashpip install driftpip install drift-basebrew install postgresqlbrew install redis```

Run the Redis server simply by executing `redis-server`.

To set up the PostgreSQL server, see [PostgreSQL setup](postgres-setup.md).### AWS support
If you want AWS development and operation environment, make sure you have the AWS CLI suite installed, and access and secret keys set up on your local computer.

```bash
pip install awscli
aws configure

```### Create Drift Configuration DatabaseThere is a single configuration database that covers all static configuration of Drift based tiers and apps. Managing this database is done using the `driftconfig` command line suite.```bash
driftconfig create kdstudios s3://kdstudios-config/kdstudios
# Note! If you opt for non-AWS based development, define a
# different source for your configuration database.
# Example: driftconfig create kdstudios file://~/kdstudios
# Now assume this is the only config on the local machine, otherwise# point to it using DRIFT_CONFIG_URL environment variable.# Add a tier. It's a good practice to start with the live tier
# and if necessary add a dev and staging tier later, even though
# the live tier will only be used for development in the beginning.driftconfig tier add LIVE

# Make the basic drift service available on LIVE tier.
driftconfig deployable add drift-base
```
### Register our organization and product
Now we have our LIVE tier set up, but all services need to run in the context of a product. Next step is to set up our organization and product.

```bash
# Arguments: organization name, short name, display namedriftconfig organization add kd-studios kd "Knee Deep Studios"# Arguments: product name, organization namedriftconfig product add snowfall kd-studios```At this point we have all the necessarty bits registered in our configuration database. Next steps are all about provisioning and running the actual services.

### Provision a tenant
Drift is a multi-tenant platform. For our scenario we just need to create a tenant for our local development. Additional tenants can be created at any time as well.

> Note: We have already completed all the basic registration steps in the Drift configuration database. For provisioning and running services, we need to use the `drift-admin` command line suite.

```bash
# Note: Tenant names MUST be prefixed with the organization short
# name. Additionally, having the word 'default' in the name will
# make it the default tenant when running a service locally.
drift-admin tenant add kd-defaultdev
```
Now you have completed every setup steps.### Running a service locallyRun the following command to start the Drift web server on your machine:

```bash
drift-admin runserver drift-base
```

The server should be up and running on port 10080. To try it out:
```bash
curl -H accept:application/json http://localhost:10080
```

> Note: The 'drift-base' argument can be ommitted if cwd is in the repository of the project. Example: `➜  drift-base git:(develop) ✗ drift-admin runserver`

Using [Postman](https://www.getpostman.com/) for development is highly encouraged. There are other ways as well, but managing authorized sessions is best done using Postman and a set of helper scripts.

### What next
Next up is to set up the LIVE tier on AWS. Please follow the steps described in [Drift on AWS](drift-on-aws.md)

The final exercise is to create a new deployable/service. Please follow the steps described in [Drift Deployables](drift-deployables.md)



*(c) 2017 Directive Games North*
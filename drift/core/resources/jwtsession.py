# -*- coding: utf-8 -*-
"""
JWT Session Management

By including this resource module in a Drift app, it will be able to accept JWT from a list
of trusted issuers and issue and sign new JWT's.

Custom attributes for top level registration:

    key_size:            <int>  Size in bytes of private key.
    trusted_issuers:     <list of deployable names>  Default value is ['drift-base']
    expiry_days:         <int>  Expiration in days, default is 365.
"""
import logging
import datetime
import secrets

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

DEFAULT_KEY_SIZE = 1024
DEFAULT_EXPIRY_DAYS = 365

log = logging.getLogger(__name__)


def register_deployable(ts, deployablename, attributes):
    """
    Deployable registration callback.
    'deployablename' is from table 'deployable-names'.
    """
    pass


def register_deployable_on_tier(ts, deployable, attributes):
    """
    Deployable registration callback for tier.
    'deployable' is from table 'deployables'.
    """
    pk = {'tier_name': deployable['tier_name'], 'deployable_name': deployable['deployable_name']}
    row = ts.get_table('public-keys').get(pk)
    if row is None:
        row = ts.get_table('public-keys').add(pk)

    # Add session cookie secret key
    row.setdefault('secret_key', secrets.token_urlsafe(32))

    # Generate RSA key pairs
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=attributes.get('key_size', DEFAULT_KEY_SIZE),
        backend=default_backend()
    )

    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    now = datetime.datetime.utcnow()
    expiry_days = attributes.get('expiry_days', DEFAULT_EXPIRY_DAYS)

    keypair = {
        'issued': now.isoformat() + "Z",
        'expires': (now + datetime.timedelta(days=expiry_days)).isoformat() + "Z",
        'public_key': public_pem.decode(),  # PEM is actually a text format
        'private_key': private_pem.decode(),  # PEM is actually a text format
    }

    # LEGACY SUPPORT! Make sure there is only one keypair registered. If one exists already
    # in the config then leave it as is. If not, add one.
    if 'keys' in row and len(row['keys']) > 0:
        # Just leave this as is
        log.warning("Legacy support: Key pair already registered, leaving it as is.")
        current_keypair = row['keys'][0]
    else:
        log.warning("Legacy support: Adding new key pair for this deployable.")
        current_keypair = keypair
        row.setdefault('keys', []).append(keypair)

    # LEGACY SUPPORT! Register drift-base as trusted issuer. Always.
    if deployable['deployable_name'] == 'drift-base':
        issuers = deployable.setdefault('jwt_trusted_issuers', [])
        for issuer in issuers:
            if issuer.get('iss') == 'drift-base':
                log.warning("Legacy support: drift-base already configured as trusted issuer.")
                break
        else:
            log.warning("Legacy support: Adding drift-base as trusted issuer.")
            issuers.append({
                'iss': 'drift-base',
                'iat': current_keypair['issued'],
                'exp': current_keypair['expires'],
                'pub_rsa': current_keypair['public_key'],
            })


def register_resource_on_tier(ts, tier, attributes):
    """
    Tier registration callback.
    'tier' is from table 'tiers'.
    'attributes' is a dict containing optional attributes for default values.
    """
    # LEGACY SUPPORT! Register the service user
    tier.setdefault('service_user', {"password": "SERVICE", "username": "user+pass:$SERVICE$"})


def register_deployable_on_tenant(ts, deployable_name, tier_name, tenant_name, resource_attributes):
    pass

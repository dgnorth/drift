import OpenSSL
import struct
import base64

from werkzeug.exceptions import Unauthorized

from drift.auth.util import fetch_url


TRUSTED_ORGANIZATIONS = ["Apple Inc."]


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)


def validate_gamecenter_token(gc_token, app_bundles=None):
    """Validates Apple Game Center token 'gc_token'. If validation fails, an
    HTTPException:Unauthorized exception is raised.

    Returns a unique ID for this player.

    If set, 'app_bundles' is list of app bundles id's, and the 'app_bundle_id' in
    the token must be one of the listed ones.

    
    Example:

    gc_token = {
        "public_key_url": "https://static.gc.apple.com/public-key/gc-prod-2.cer",
        "app_bundle_id": "com.directivegames.themachines.ios",
        "player_id": "G:1637867917",
        "timestamp": 1452128703383,
        "salt": "vPWarQ==",
        "signature": "ZuhbO8TqGKadYAZHsDd5NgTs/tmM8sIqhtxuUmxOlhmp8PUAofIYzdwaN...
    }
    
    validate_gamecenter_token(gc_token)
    
    """

    token_desc = dict(gc_token)
    token_desc["signature"] = token_desc.get("signature", "?")[:10]
    error_title = 'Invalid Game Center token: %s' % token_desc 

    # Verify required fields
    required_fields = [
        'app_bundle_id', 'player_id', 'public_key_url',
        'salt', 'signature', 'timestamp'
    ]

    missing_fields = list(set(required_fields) - set(gc_token.keys()))
    if missing_fields:
        abort_unauthorized(error_title + ". The token is missing required fields: %s." % ', '.join(missing_fields))

    # Verify that the token is issued to the appropriate app.
    if app_bundles and gc_token["app_bundle_id"] not in app_bundles:
        abort_unauthorized(error_title + ". 'app_bundle_id' not one of %s" % app_bundles)

    # Fetch public key, use cache if available.
    content = fetch_url(gc_token['public_key_url'], error_title)

    # Load certificate
    try:
        cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_ASN1, content)
    except OpenSSL.crypto.Error as e:
        abort_unauthorized(error_title + ". Can't load certificate: %s" % str(e))      

    # Verify that the key is issued to someone we trust and is not expired.
    org_name = cert.get_subject().organizationName
    if org_name not in TRUSTED_ORGANIZATIONS:
        abort_unauthorized(error_title + ". Certificate is issued to '%s' which is not one of %s." % (org_name, TRUSTED_ORGANIZATIONS))
    
    if cert.has_expired():
        abort_unauthorized(error_title + ". Certificate is expired, 'notAfter' is '%s'" % cert.get_notAfter())            

    # Check signature
    salt_decoded = base64.b64decode(gc_token["salt"])
    payload = ""
    payload += gc_token["player_id"].encode('UTF-8') 
    payload += gc_token["app_bundle_id"].encode('UTF-8') 
    payload += struct.pack('>Q', int(gc_token["timestamp"])) 
    payload += salt_decoded
    signature_decoded = base64.b64decode(gc_token["signature"])

    try:
        OpenSSL.crypto.verify(cert, signature_decoded, payload, 'sha256')
    except Exception as e:
        abort_unauthorized(error_title + ". Can't verify signature: %s" % str(e))

    return gc_token["player_id"]

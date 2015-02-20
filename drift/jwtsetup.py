import ccpjwt
import datetime, logging, requests, json
from drift.utils import get_service_db_conn
import netaddr
from flask import g, abort, request
import jwt as pyjwt
import random

log = logging.getLogger(__name__)

def get_remote_addr():
    """
    We keep this in a function so that it can be mocked out
    Note that in unit tests this will be None
    """
    return request.remote_addr

def jwtsetup(app):
    jwt = ccpjwt.JWT(app)

    def authenticate_provider(username, password, provider):
        providers = app.config.get("authentication_providers", {})
        if provider not in providers:
            log.error("Authentication provider %s not found. I cannot authenticate %s", provider, username)
            return None

        # local development environment
        if provider == "local":
            ret = {"role": "service" if username.startswith("$") else "player"} #! TODO: Temporary hack fix for battleservers with incorrect provider
            local_password = providers[provider].get("password")
            if local_password != password:
                log.warning("Could not authenticate local user %s. Incorrect password", username)
                return None
            ip_address = get_remote_addr()
            log.info("Local user %s authenticating from IP address %s", username, ip_address)
            localdev_ip_whitelist = app.config.get("localdev_ip_whitelist", [])
            allowed_networks = netaddr.IPSet(localdev_ip_whitelist)
            if not ip_address or ip_address in allowed_networks:
                return ret
            else:
                log.warning("Local user %s is connecting from an IP address %s that is not whitelisted", username, ip_address)
                return None
            return None
        # service to service calls
        elif provider == "service":
            ret = {"role": "service"}
            service_users = providers[provider].get("users")
            for config_username, cfg in service_users.iteritems():
                if config_username.lower() == username.lower():
                    if cfg["password"] == password:
                        role = cfg["role"]
                        log.info("Service user %s has authenticated with role %s", username, role)
                        return ret
                    else:
                        log.error("Service user %s tried to log in with an incorrect password", username)
            return None

        endpoint = providers[provider].get("endpoint")
        data = {"username": username, "password": password}
        resp = requests.post(endpoint, data=json.dumps(data), headers={'Content-Type' : 'application/json'}, timeout=5.0, verify=False)
        if resp.status_code != 200:
            log.warning("Could not authenticate %s against provider %s. Status code was %s", username, provider, resp.status_code)
            log.warning(resp.content)
            return None
        token = resp.json()["token"]
        provider_info = pyjwt.decode(token, verify=False) #! TODO: Add signature verification
        provider_info["role"] = "player"
        is_active = provider_info.get("is_active", True)
        is_superuser = provider_info.get("is_superuser", False)
        is_staff = provider_info.get("is_staff", False)

        callsign = provider_info.get("callsign", provider_info.get("username", "Unknown").split("@")[0])
        tenants = provider_info.get("tenants", [])
        if not tenants: #! TODO: temporary backwards-compatibility hack
            tenants = provider_info.get("tenants", [])
        if not is_active:
            return None
        current_tenant = g.ccpenv["name"]
        if current_tenant not in tenants:
            if is_staff or is_superuser:
                log.info("User %s should not have access to this tenant but he is a superuser so we'll let him in", username)
            else:
                log.warning("User %s does not have access to tenant %s. He has access to tenants %s", username, current_tenant, ",".join(tenants))
                return None

        return provider_info

    @jwt.authentication_handler
    def authenticate(username, password, provider=None):
        """
        Example usage:
        POST http://localhost:10080/auth

        { "username": "username", "password": "password", "provider": "signup"}
        """
        if not provider:
            log.warning("No provider specified for %s. We really should raise at this point!", username)
            provider = "local"

        #! TODO: for temporary backwards compatibility
        if username.startswith("$") and username.endswith("$"):
            provider = "service"

        if provider:
            log.info("This call requires real authentication for %s against provider %s", username, provider)
            provider_info = authenticate_provider(username, password, provider)
            if not provider_info:
                abort(401)

        dbconn = get_service_db_conn("pilot")
        curr = dbconn.cursor()
        curr.callproc("pilot.Users_Logon", {"@userName": username})
        rows = curr.fetchall()
        dbconn.close()
        if len(rows) != 1:
            log.error("Could not authenticate %s, no db row returned!", username)
            abort(404)
        row = rows[0]
        user_id = row["userID"]
        pilot_id = row["pilotID"]
        pilot_name = row["pilotName"]
        customer_id = -1
        log.info("%s has authenticated with pilot_id %s, role %s", username, pilot_id, provider_info["role"])

        ret = {
            "user_name": username,
            "pilot_id": pilot_id,
            "user_id": user_id,
            "pilot_name": pilot_name,
            "customer_id": customer_id,
        }
        ret["role"] = provider_info["role"]
        return ret

    @jwt.payload_handler
    def make_payload(user):
        return user

    @jwt.user_handler
    def load_user(payload):
        return payload
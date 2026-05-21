"""
sf_client.py
------------
Handles all Salesforce authentication logic.
Supports Username+Password+Security Token and OAuth 2.0 flows.
"""

import logging
import requests
from simple_salesforce import Salesforce, SalesforceAuthenticationFailed

logger = logging.getLogger(__name__)


class SalesforceClient:
    """
    Wraps simple-salesforce to provide authenticated Salesforce connections.
    Supports two auth methods:
      - 'password'  : Username + Password + Security Token (most common)
      - 'oauth'     : OAuth 2.0 Client Credentials / Connected App flow
    """

    def __init__(self, org_config: dict):
        """
        org_config is one entry from the "orgs" list in config.json.
        """
        self.alias = org_config.get("alias", "UnknownOrg")
        self.auth_method = org_config.get("auth_method", "password").lower()
        self.org_config = org_config
        self._sf = None  # Will hold the authenticated Salesforce object

    def connect(self) -> Salesforce:
        """
        Authenticates to Salesforce and returns a Salesforce connection object.
        Raises RuntimeError if authentication fails.
        """
        logger.info(f"[{self.alias}] Connecting via '{self.auth_method}' auth...")

        if self.auth_method == "password":
            return self._connect_password()
        elif self.auth_method == "oauth":
            return self._connect_oauth()
        else:
            raise ValueError(
                f"[{self.alias}] Unknown auth_method '{self.auth_method}'. "
                f"Use 'password' or 'oauth'."
            )

    def _connect_password(self) -> Salesforce:
        """
        Authenticates using Username + Password + Security Token.
        This is the most common method for scripts and automation.
        """
        required_fields = ["username", "password", "security_token", "instance_url"]
        for field in required_fields:
            if not self.org_config.get(field):
                raise ValueError(
                    f"[{self.alias}] Missing required field '{field}' in config.json "
                    f"for password auth."
                )

        username = self.org_config["username"]
        password = self.org_config["password"]
        security_token = self.org_config["security_token"]
        instance_url = self.org_config["instance_url"]
        is_sandbox = self.org_config.get("is_sandbox", False)

        # simple-salesforce uses 'domain' to distinguish sandbox vs production
        # Production login: login.salesforce.com  → domain = None (default)
        # Sandbox login:    test.salesforce.com   → domain = 'test'
        domain = "test" if is_sandbox else None

        try:
            sf = Salesforce(
                username=username,
                password=password,
                security_token=security_token,
                domain=domain,
            )
            logger.info(f"[{self.alias}] Successfully authenticated as {username}")
            self._sf = sf
            return sf

        except SalesforceAuthenticationFailed as e:
            raise RuntimeError(
                f"[{self.alias}] Authentication FAILED for user '{username}'.\n"
                f"  Reason: {str(e)}\n"
                f"  Common causes:\n"
                f"    1. Wrong password or security token\n"
                f"    2. IP not whitelisted — reset security token\n"
                f"    3. Used login.salesforce.com for a sandbox (set is_sandbox: true)\n"
                f"    4. API access not enabled for this user profile"
            )
        except Exception as e:
            raise RuntimeError(
                f"[{self.alias}] Unexpected error during authentication: {str(e)}"
            )

    def _connect_oauth(self) -> Salesforce:
        """
        Authenticates using OAuth 2.0 (Connected App, client_credentials flow).
        Requires 'client_id', 'client_secret', and 'instance_url' in config.
        """
        required_fields = ["client_id", "client_secret", "instance_url"]
        for field in required_fields:
            if not self.org_config.get(field):
                raise ValueError(
                    f"[{self.alias}] Missing required field '{field}' for OAuth auth."
                )

        token_url = self.org_config["instance_url"].rstrip("/") + "/services/oauth2/token"
        client_id = self.org_config["client_id"]
        client_secret = self.org_config["client_secret"]

        try:
            response = requests.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=30,
            )
            response.raise_for_status()
            token_data = response.json()

            access_token = token_data.get("access_token")
            instance_url = token_data.get("instance_url")

            if not access_token:
                raise RuntimeError(
                    f"[{self.alias}] OAuth token response did not contain access_token. "
                    f"Response: {token_data}"
                )

            sf = Salesforce(
                instance_url=instance_url,
                session_id=access_token,
            )
            logger.info(f"[{self.alias}] Successfully authenticated via OAuth 2.0")
            self._sf = sf
            return sf

        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"[{self.alias}] OAuth HTTP request failed: {str(e)}"
            )
        except Exception as e:
            raise RuntimeError(
                f"[{self.alias}] OAuth authentication error: {str(e)}"
            )

import logging

from fastmcp.server.auth.providers.github import GitHubProvider
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.routes import build_resource_metadata_url
from pydantic import AnyHttpUrl

from .errors import APIError
from .oauth_storage import BoundedOAuthFileTreeStore

logger = logging.getLogger(__name__)
OAUTH_STORAGE_BYTES = 8 * 1024 * 1024
OAUTH_STORAGE_FILES = 512


class _SafeExchangeClient:
    def __init__(self, upstream):
        self.upstream = upstream

    def __getattr__(self, name):
        return getattr(self.upstream, name)

    async def fetch_token(self, **params):
        try:
            return await self.upstream.fetch_token(**params)
        except Exception as exc:
            logger.warning("GitHub OAuth token exchange failed (%s)", type(exc).__name__)
            # FastMCP displays the exchange error in the callback response.
            raise RuntimeError("GitHub did not complete the token exchange.") from None


class _DecisionGitHubProvider(GitHubProvider):
    def _create_upstream_oauth_client(self):
        return _SafeExchangeClient(super()._create_upstream_oauth_client())


class DecisionOAuth:
    def __init__(self, config, callers, state_dir):
        self.principals = {}
        for principal, scope in config.principals.items():
            candidates = [caller for caller in callers.values() if caller.caller_scope == scope]
            if (not principal.startswith("github:") or principal != principal.casefold()
                    or not candidates or any(caller != candidates[0] for caller in candidates[1:])):
                raise ValueError("OAuth principals must map to one existing caller policy")
            self.principals[principal] = candidates[0]

        public = str(config.public_base_url).rstrip("/")
        signing_key = config.signing_key.get_secret_value()
        client_id = config.client_id.get_secret_value()
        client_secret = config.client_secret.get_secret_value()
        if len(signing_key) < 43 or not client_id or not client_secret:
            raise ValueError("Independent OAuth credentials are required")
        storage = FernetEncryptionWrapper(
            BoundedOAuthFileTreeStore(state_dir, OAUTH_STORAGE_BYTES, OAUTH_STORAGE_FILES),
            source_material=signing_key,
            salt="decision-service/oauth-state",
        )
        self.provider = _DecisionGitHubProvider(
            client_id=client_id, client_secret=client_secret,
            base_url=public, issuer_url=public, resource_base_url=public,
            redirect_path="/auth/callback", required_scopes=["read:user"],
            jwt_signing_key=signing_key, client_storage=storage,
            require_authorization_consent=True, enable_cimd=False, forward_resource=False,
            allowed_client_redirect_uris=config.allowed_client_redirect_uris,
        )
        resource_metadata = build_resource_metadata_url(AnyHttpUrl(public + "/mcp"))
        self.challenge = f'Bearer resource_metadata="{resource_metadata}", scope="read:user"'
        # Discovery paths include the public prefix per RFC 8414 and RFC 9728.
        # The proxy strips the prefix only from the operational OAuth routes.
        prefix = (config.public_base_url.path or "").rstrip("/")
        metadata_paths = {
            "/.well-known/oauth-authorization-server" + prefix,
            "/.well-known/openid-configuration" + prefix,
            resource_metadata.path,
        }
        self.routes = [
            route for route in self.provider.get_routes("/mcp") if not route.path.startswith("/.well-known/")
        ] + [
            route for route in self.provider.get_well_known_routes("/mcp") if route.path in metadata_paths
        ]

    async def authenticate(self, authorization):
        scheme, _, bearer = (authorization or "").partition(" ")
        token = await self.provider.verify_token(bearer) if scheme.lower() == "bearer" and bearer else None
        if token is None or not set(self.provider.required_scopes).issubset(token.scopes):
            raise APIError("unauthenticated")
        login = (token.claims or {}).get("login")
        caller = self.principals.get("github:" + login.casefold()) if isinstance(login, str) else None
        if caller is None:
            raise APIError("forbidden_scope")
        return caller

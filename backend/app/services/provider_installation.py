"""OAuth installation contracts for Slack and Microsoft Teams."""

from urllib.parse import urlencode
import httpx
from jose import jwt, JWTError
from app.core.config import settings
from app.services.calendar_oauth import default_secret_store


def _config(provider: str) -> tuple[str, str, str, str]:
    if provider == "slack":
        return ("https://slack.com/oauth/v2/authorize", "https://slack.com/api/oauth.v2.access",
                settings.SLACK_CLIENT_ID or "", settings.SLACK_REDIRECT_URI)
    if provider == "teams":
        return ("https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                settings.TEAMS_CLIENT_ID or "", settings.TEAMS_REDIRECT_URI)
    raise ValueError("Unsupported provider")


def installation_url(provider: str, tenant_id: str) -> str:
    authorize, _, client_id, redirect = _config(provider)
    if not client_id:
        raise RuntimeError(f"{provider} OAuth client is not configured")
    state = jwt.encode({"tenant": tenant_id, "provider": provider},
                       settings.CALENDAR_OAUTH_STATE_SECRET, algorithm="HS256")
    scope = "chat:write,channels:read,groups:read" if provider == "slack" else "offline_access https://graph.microsoft.com/.default"
    return f"{authorize}?{urlencode({'client_id': client_id, 'scope': scope, 'redirect_uri': redirect, 'state': state, 'response_type': 'code'})}"


def validate_installation_state(state: str, provider: str) -> str:
    try:
        claims = jwt.decode(state, settings.CALENDAR_OAUTH_STATE_SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise ValueError("Invalid or expired installation state") from exc
    if claims.get("provider") != provider:
        raise ValueError("Invalid installation state")
    return str(claims["tenant"])


async def exchange_installation(provider: str, code: str) -> dict:
    _, token_url, client_id, redirect = _config(provider)
    secret = settings.SLACK_CLIENT_SECRET if provider == "slack" else settings.TEAMS_CLIENT_SECRET
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(token_url, data={"code": code, "client_id": client_id,
            "client_secret": secret, "redirect_uri": redirect, "grant_type": "authorization_code"})
        response.raise_for_status()
        payload = response.json()
    if provider == "slack" and not payload.get("ok", True):
        raise ValueError("Slack installation was rejected")
    token = payload.get("access_token")
    if not token:
        raise ValueError("Provider returned no installation token")
    payload["access_token_ref"] = await default_secret_store().store(token, hint=f"{provider}-installation")
    payload.pop("access_token", None)
    return payload

"""Use the deployed FinSight (AgentCore Runtime) from the terminal: log in, then chat.

Login is OAuth 2.0 "authorization code + PKCE" with Cognito's hosted page:
  1. We make a random secret (the verifier) and put only its SHA-256 hash (the challenge)
     in the login link.
  2. You sign in (password + authenticator code) in the browser. Cognito redirects to
     http://localhost:8501/ with a one-time code, which a tiny local server here catches.
  3. We trade the code AND the verifier for tokens. Anyone who intercepts the code can't
     use it without the verifier, which never leaves this process.

Tokens stay in memory only (never written to disk) and expire after an hour. AgentCore
checks each request's token (signature, expiry, our app client) before FinSight runs.

RemoteAgent has the same interface as ResearchAgent (send, reset, write_note, total_usage),
and turns the server's events back into the same event objects, so the CLI chat renders a
remote answer exactly like a local one.
"""

import base64
import hashlib
import json
import secrets
import urllib.parse
import uuid
import webbrowser
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from finsight import config
from finsight.agent import (
    Done,
    Event,
    GuardrailBlocked,
    GuardrailReport,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from finsight.api import SESSION_HEADER
from finsight.guardrail import FlaggedParagraph, Grounding, Verdict
from finsight.notes import ResearchNote

REDIRECT_URI = "http://localhost:8501/"  # must match the Cognito app client exactly
CALLBACK_PORT = 8501
AGENTCORE = "https://bedrock-agentcore.us-east-1.amazonaws.com"
TIMEOUT = httpx.Timeout(10.0, read=300.0)  # answers can take minutes (tools + thinking)


class LoginError(Exception):
    pass


class RemoteError(Exception):
    pass


# ---------- login (authorization code + PKCE) ----------


def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge): challenge = base64url(sha256(verifier)), as in RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    return verifier, challenge_for(verifier)


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(domain: str, client_id: str, challenge: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": "openid email",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,  # a random value we check on return (stops forged redirects)
        }
    )
    return f"https://{domain}/oauth2/authorize?{query}"


def parse_callback(path: str, state: str) -> str | None:
    """The code from Cognito's redirect, None for unrelated requests (e.g. favicon)."""
    params = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    if "error" in params:
        raise LoginError(f"login failed: {params['error'][0]}")
    if "code" not in params:
        return None
    if params.get("state", [""])[0] != state:
        raise LoginError("login response didn't match this login attempt (state mismatch)")
    return params["code"][0]


def wait_for_code(state: str, timeout: float = 300) -> str:
    """Run a one-shot local web server until Cognito redirects the browser back to it."""
    result: dict[str, str | Exception] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                code = parse_callback(self.path, state)
            except LoginError as e:
                result["error"] = e
                code = None
            if code:
                result["code"] = code
            done = "code" in result or "error" in result
            self.send_response(200 if done else 404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if done:
                message = "Logged in to FinSight. You can close this tab."
                if "error" in result:
                    message = f"FinSight login failed: {result['error']}"
                self.wfile.write(message.encode())

        def log_message(self, *args):  # keep the terminal quiet
            pass

    try:
        server = _CallbackServer(("localhost", CALLBACK_PORT), Handler)
    except OSError:
        raise LoginError(
            f"port {CALLBACK_PORT} is busy (is `finsight ui` running?) - stop it and retry"
        ) from None
    server.timeout = timeout
    with server:
        while not result:
            server.handle_request()  # returns after one request, or after `timeout`
            if server.timed_out:
                raise LoginError("timed out waiting for the browser login")
    if "error" in result:
        raise result["error"]
    return result["code"]


class _CallbackServer(HTTPServer):
    timed_out = False

    def handle_timeout(self) -> None:
        self.timed_out = True


def exchange_code(http: httpx.Client, domain: str, client_id: str, code: str, verifier: str) -> str:
    """Trade the one-time code + PKCE verifier for tokens; returns the access token."""
    response = http.post(
        f"https://{domain}/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    if response.status_code != 200:
        raise LoginError(f"token exchange failed: {response.text[:200]}")
    return response.json()["access_token"]


def login(open_browser=webbrowser.open, http: httpx.Client | None = None) -> str:
    domain, client_id = config.COGNITO_DOMAIN, config.COGNITO_CLIENT_ID
    if not (domain and client_id):
        raise LoginError("set FINSIGHT_COGNITO_DOMAIN and FINSIGHT_COGNITO_CLIENT_ID in .env")
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = authorize_url(domain, client_id, challenge, state)
    print(f"Opening the FinSight login page in your browser...\n  {url}\n")
    open_browser(url)
    code = wait_for_code(state)
    with http or httpx.Client(timeout=TIMEOUT) as client:
        return exchange_code(client, domain, client_id, code, verifier)


# ---------- calling the deployed agent ----------


def invocation_url(runtime_arn: str) -> str:
    arn = urllib.parse.quote(runtime_arn, safe="")
    return f"{AGENTCORE}/runtimes/{arn}/invocations?qualifier=DEFAULT"


def dict_to_event(data: dict) -> Event:
    """The reverse of api.event_to_dict."""
    match data["type"]:
        case "text":
            return TextDelta(data["text"])
        case "tool_call":
            return ToolCall(data["name"], data["input"])
        case "tool_result":
            return ToolResult(data["name"], data["is_error"])
        case "guardrail_blocked":
            return GuardrailBlocked(data["message"], data["reasons"])
        case "guardrail_report":
            output, grounding = data.get("output"), data.get("grounding")
            return GuardrailReport(
                output=Verdict(**output) if output else None,
                grounding=Grounding(
                    checked=grounding["checked"],
                    flagged=[FlaggedParagraph(**p) for p in grounding["flagged"]],
                )
                if grounding
                else None,
                error=data.get("error"),
            )
        case "done":
            return Done(data["text"], Usage(**data["usage"]), data["model"], data["stop_reason"])
        case "error":
            raise RemoteError(data["message"])
    raise RemoteError(f"unknown event from the server: {data['type']!r}")


class RemoteAgent:
    """Talks to the deployed agent; one conversation = one AgentCore session."""

    def __init__(self, token: str, runtime_arn: str, http: httpx.Client | None = None) -> None:
        self.url = invocation_url(runtime_arn)
        self.http = http or httpx.Client(timeout=TIMEOUT)
        self.token = token
        self.total_usage = Usage()
        self._new_session()

    def _new_session(self) -> None:
        # AgentCore session ids must be at least 33 characters; each one gets its own micro-VM
        self.session_id = uuid.uuid4().hex + uuid.uuid4().hex

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            SESSION_HEADER: self.session_id,
            "Content-Type": "application/json",
        }

    def send(self, prompt: str) -> Iterator[Event]:
        body = {"prompt": prompt, "action": "chat"}
        with self.http.stream("POST", self.url, headers=self._headers(), json=body) as response:
            _check(response)
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue  # blank separator lines
                event = dict_to_event(json.loads(line.removeprefix("data: ")))
                if isinstance(event, Done):
                    self._count(event.usage)
                yield event

    def write_note(self) -> tuple[ResearchNote, Usage]:
        response = self.http.post(self.url, headers=self._headers(), json={"action": "note"})
        if response.status_code == 400:
            raise ValueError(response.json().get("error", "could not write the note"))
        _check(response)
        data = response.json()
        usage = Usage(**data.get("usage", {}))
        self._count(usage)
        return ResearchNote(**data["note"]), usage

    def reset(self) -> None:
        """Forget the conversation (the session's micro-VM stays, so no new cold start)."""
        response = self.http.post(self.url, headers=self._headers(), json={"action": "reset"})
        _check(response)

    def _count(self, usage: Usage) -> None:
        self.total_usage.input_tokens += usage.input_tokens
        self.total_usage.output_tokens += usage.output_tokens
        self.total_usage.cache_read_tokens += usage.cache_read_tokens
        self.total_usage.cache_write_tokens += usage.cache_write_tokens


def _check(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise RemoteError("not logged in or login expired (tokens last 1 hour) - run it again")
    if response.status_code != 200:
        response.read()
        raise RemoteError(f"server returned {response.status_code}: {response.text[:300]}")

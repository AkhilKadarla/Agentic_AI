"""Tests for the AgentCore deploy script (fake control-plane client; no AWS calls)."""

import pytest

from deploy.agentcore import DeployError, deploy, discovery_url, runtime_request

IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/finsight:abc123"
ENV = {
    "RUNTIME_ROLE_ARN": "arn:aws:iam::123456789012:role/finsight-agentcore-runtime",
    "COGNITO_USER_POOL_ID": "us-east-1_TEST",
    "COGNITO_CLIENT_ID": "client123",
    "SEC_USER_AGENT": "Test test@example.com",
    "FINSIGHT_BEDROCK_MODEL": "us.anthropic.claude-sonnet-4-6",
    "FINSIGHT_GUARDRAIL_ID": "gr123",
    "FINSIGHT_GUARDRAIL_VERSION": "3",
    "FINSIGHT_KB_ID": "kb123",
    "GITHUB_TOKEN": "must-not-leak",
}


class FakePaginator:
    def __init__(self, runtimes):
        self.runtimes = runtimes

    def paginate(self):
        yield {"agentRuntimes": self.runtimes}


class FakeControl:
    def __init__(self, existing=None, statuses=("CREATING", "READY"), failure=""):
        self.existing = existing or []
        self.statuses = list(statuses)
        self.failure = failure
        self.calls = []

    def get_paginator(self, name):
        assert name == "list_agent_runtimes"
        return FakePaginator(self.existing)

    def create_agent_runtime(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"agentRuntimeId": "finsight-NEW", "status": "CREATING"}

    def update_agent_runtime(self, **kwargs):
        self.calls.append(("update", kwargs))
        return {"agentRuntimeId": kwargs["agentRuntimeId"], "status": "UPDATING"}

    def get_agent_runtime(self, agentRuntimeId):
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {
            "agentRuntimeId": agentRuntimeId,
            "agentRuntimeVersion": "2",
            "status": status,
            "failureReason": self.failure,
        }


def no_sleep(_seconds):
    pass


def test_request_requires_login_and_passes_only_app_settings():
    request = runtime_request(IMAGE, ENV)
    jwt = request["authorizerConfiguration"]["customJWTAuthorizer"]
    assert jwt["discoveryUrl"] == discovery_url("us-east-1_TEST")
    assert jwt["discoveryUrl"].endswith("/us-east-1_TEST/.well-known/openid-configuration")
    assert jwt["allowedClients"] == ["client123"]
    assert request["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"] == IMAGE
    env = request["environmentVariables"]
    assert env["FINSIGHT_PROVIDER"] == "bedrock"
    assert env["FINSIGHT_GUARDRAIL_VERSION"] == "3"
    assert "GITHUB_TOKEN" not in env  # nothing else from the CI environment leaks in
    assert "RUNTIME_ROLE_ARN" not in env


def test_missing_settings_are_listed():
    env = {k: v for k, v in ENV.items() if k not in ("FINSIGHT_KB_ID", "COGNITO_CLIENT_ID")}
    with pytest.raises(DeployError, match="COGNITO_CLIENT_ID, FINSIGHT_KB_ID"):
        runtime_request(IMAGE, env)


def test_first_deploy_creates_the_runtime():
    client = FakeControl()
    runtime = deploy(client, IMAGE, ENV, sleep=no_sleep)
    (kind, kwargs), *_ = client.calls
    assert kind == "create"
    assert kwargs["agentRuntimeName"] == "finsight"
    assert "customJWTAuthorizer" in kwargs["authorizerConfiguration"]
    assert runtime["status"] == "READY"


def test_later_deploys_update_the_existing_runtime():
    existing = [
        {"agentRuntimeName": "other", "agentRuntimeId": "other-1"},
        {"agentRuntimeName": "finsight", "agentRuntimeId": "finsight-ABC"},
    ]
    client = FakeControl(existing=existing, statuses=("UPDATING", "UPDATING", "READY"))
    deploy(client, IMAGE, ENV, sleep=no_sleep)
    (kind, kwargs), *_ = client.calls
    assert kind == "update"
    assert kwargs["agentRuntimeId"] == "finsight-ABC"
    assert "agentRuntimeName" not in kwargs  # the name can't change on update


def test_failed_update_reports_the_reason():
    client = FakeControl(statuses=("UPDATE_FAILED",), failure="image not found")
    with pytest.raises(DeployError, match="UPDATE_FAILED: image not found"):
        deploy(client, IMAGE, ENV, sleep=no_sleep)

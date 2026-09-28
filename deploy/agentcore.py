"""Deploy FinSight to Amazon Bedrock AgentCore Runtime: create it the first time, update it after.

Run by .github/workflows/deploy.yml as the GitHub deploy role (infra/iam/github-deploy/),
after the container image is pushed to ECR:

    python -m deploy.agentcore --image <registry>/finsight:<git-sha>

Settings come from environment variables (the GitHub `production` environment); none are
secrets, but the output avoids printing ARNs because this repository's logs are public.
Every update creates a new immutable runtime version, and the DEFAULT endpoint moves to it
once it is READY, so a failed update leaves the previous version serving.
"""

import argparse
import os
import sys
import time

import boto3

RUNTIME_NAME = "finsight"  # letters, digits and _ only; AgentCore adds a random id suffix
REGION = "us-east-1"
FAILED = {"CREATE_FAILED", "UPDATE_FAILED"}
TAGS = {"project": "finsight"}  # for cost reports and audits

# Required deploy settings (GitHub environment variables / secrets).
REQUIRED = ["RUNTIME_ROLE_ARN", "COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID", "SEC_USER_AGENT"]
# App settings passed straight through to the container (read by finsight/config.py).
APP_SETTINGS = [
    "FINSIGHT_BEDROCK_MODEL",
    "FINSIGHT_GUARDRAIL_ID",
    "FINSIGHT_GUARDRAIL_VERSION",
    "FINSIGHT_KB_ID",
    "SEC_USER_AGENT",
]


class DeployError(Exception):
    pass


def discovery_url(user_pool_id: str) -> str:
    return (
        f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}"
        "/.well-known/openid-configuration"
    )


def runtime_request(image: str, env: dict[str, str]) -> dict:
    """The runtime settings shared by create and update."""
    missing = [name for name in REQUIRED + APP_SETTINGS if not env.get(name)]
    if missing:
        raise DeployError(f"missing settings: {', '.join(sorted(set(missing)))}")
    return {
        "description": "FinSight research agent (deployed by GitHub Actions)",
        "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": image}},
        "roleArn": env["RUNTIME_ROLE_ARN"],
        "networkConfiguration": {"networkMode": "PUBLIC"},  # needs the internet for SEC EDGAR
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        # Login required: AgentCore rejects any request without a valid Cognito access token
        # from our app client, before it reaches the container. (The deploy role's IAM policy
        # also refuses to create or update a runtime without this.)
        "authorizerConfiguration": {
            "customJWTAuthorizer": {
                "discoveryUrl": discovery_url(env["COGNITO_USER_POOL_ID"]),
                "allowedClients": [env["COGNITO_CLIENT_ID"]],
            }
        },
        # A session's micro-VM (and its conversation memory) ends after 15 idle minutes,
        # and after 8 hours at most.
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 900, "maxLifetime": 28800},
        "environmentVariables": {
            "FINSIGHT_PROVIDER": "bedrock",
            # Trace files would vanish with each micro-VM; CloudWatch tracing comes in 8.6.
            "FINSIGHT_TRACING": "off",
            **{name: env[name] for name in APP_SETTINGS},
        },
    }


def find_runtime(client) -> dict | None:
    for page in client.get_paginator("list_agent_runtimes").paginate():
        for runtime in page["agentRuntimes"]:
            if runtime["agentRuntimeName"] == RUNTIME_NAME:
                return runtime
    return None


def wait_until_ready(
    client, runtime_id: str, timeout: float = 900, poll: float = 10, sleep=time.sleep
) -> dict:
    waited = 0.0
    while True:
        runtime = client.get_agent_runtime(agentRuntimeId=runtime_id)
        status = runtime["status"]
        if status == "READY":
            return runtime
        if status in FAILED:
            raise DeployError(f"{status}: {runtime.get('failureReason', 'no reason given')}")
        if waited >= timeout:
            raise DeployError(f"still {status} after {timeout:.0f}s")
        print(f"  {status}...", flush=True)
        sleep(poll)
        waited += poll


def deploy(client, image: str, env: dict[str, str], sleep=time.sleep) -> dict:
    request = runtime_request(image, env)
    existing = find_runtime(client)
    if existing:
        print(f"Updating runtime {existing['agentRuntimeId']}", flush=True)
        response = client.update_agent_runtime(agentRuntimeId=existing["agentRuntimeId"], **request)
    else:
        print(f"Creating runtime {RUNTIME_NAME}", flush=True)
        response = client.create_agent_runtime(agentRuntimeName=RUNTIME_NAME, **request)
        # Tag after creating, not during: at create time IAM checks tagging against
        # runtime/* (no id yet); now the deploy role's finsight-* tagging rule applies.
        client.tag_resource(resourceArn=response["agentRuntimeArn"], tags=TAGS)
    runtime = wait_until_ready(client, response["agentRuntimeId"], sleep=sleep)
    print(f"READY: runtime {runtime['agentRuntimeId']} version {runtime['agentRuntimeVersion']}")
    return runtime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--image", required=True, help="ECR image URI with an immutable tag")
    args = parser.parse_args()
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    try:
        deploy(client, args.image, dict(os.environ))
    except DeployError as e:
        sys.exit(f"Deploy failed: {e}")


if __name__ == "__main__":
    main()

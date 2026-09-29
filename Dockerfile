# FinSight API for Amazon Bedrock AgentCore Runtime (requires linux/arm64).
# Build: docker build --platform linux/arm64 -t finsight-api .
FROM python:3.12-slim

# uv (pinned to the version used in development) installs the locked dependencies.
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first (cached between builds unless the lockfile changes). No dev tools
# and no UI libraries: --no-default-groups skips the "dev" and "ui" groups; the "cloud"
# group adds the AWS Distro for OpenTelemetry (traces to CloudWatch).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-default-groups --group cloud --no-install-project

COPY src ./src
RUN uv sync --locked --no-default-groups --group cloud

# Run as an unprivileged user, never root.
RUN useradd --create-home --uid 1000 finsight
USER finsight

# Settings come from environment variables set on the runtime - never from a baked-in .env.
EXPOSE 8080
# opentelemetry-instrument (ADOT) sets up tracing before the app starts; AgentCore Runtime
# supplies its settings (where to send spans) through environment variables.
CMD ["opentelemetry-instrument", "uvicorn", "finsight.api:app", "--host", "0.0.0.0", "--port", "8080"]

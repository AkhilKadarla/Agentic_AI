# IAM policies (policy as code)

| File | Attached to | Notes |
|---|---|---|
| `finsight-developer.json` | SSO permission set `FinSightDeveloper` (inline) | Permanent developer access, alongside the AWS managed `AmazonBedrockFullAccess` |
| `finsight-developer-with-temporary-iam.json` | Same, **only during setup** | Adds just-in-time rights to create one role; revert to `finsight-developer.json` right after |
| `finsight-developer-with-temporary-cognito.json` | Same, **only during setup** | Adds just-in-time rights to create the Cognito user pool (Phase 8.2, `infra/cognito/`); revert right after |
| `finsight-developer-with-temporary-runtime-setup.json` | Same, **only during setup** | Adds just-in-time rights to create the ECR repo `finsight` and the role below (Phase 8.3); revert right after |
| `agentcore-runtime/` | Role `finsight-agentcore-runtime` (inline policy `finsight-runtime`) | The deployed app's own identity. Read-only: pull its image, write its logs/traces, call Sonnet 4.6 **only via the `us.` profile** (data residency enforced by IAM), apply the FinSight guardrail, search the FinSight KB. No S3, no IAM, no writes |
| `finsight-developer-with-temporary-deploy-setup.json` | Same, **only during setup** | Adds just-in-time rights to create the GitHub OIDC provider, the deploy role, AgentCore's runtime-identity service-linked role, and to trim the runtime role (Phase 8.4); revert right after |
| `github-deploy/` | Role `finsight-github-deploy` (inline policy `finsight-deploy`) | Assumed by GitHub Actions via OIDC, **only** from this repo's `production` environment (main only, owner approval). Pushes the `finsight` image; creates/updates the `finsight` runtime **only with a JWT (Cognito) authorizer**; may pass **only** `finsight-agentcore-runtime`. Cannot delete anything |
| `bedrock-invocation-logging/` | Role `finsight-bedrock-invocation-logging` | Lets Bedrock (and only this account's Bedrock) write model invocation logs to `/finsight/bedrock-invocations` |

Replace `ACCOUNT_ID` (and `GUARDRAIL_ID`, `KB_ID` from `.env`) in the templates before use.
If the guardrail, knowledge base or Bedrock model changes, update the runtime policy too.

ECR repository `finsight` (`infra/ecr/`): immutable tags (a published version can never be
swapped), scan on push, AES-256 encryption, keeps the 20 newest images for rollback. Resources are scoped by the `finsight-`
naming convention so these permissions can't touch anything else in the account.

Bedrock model invocation logging (enabled Phase 7): text only, CloudWatch Logs,
log group `/finsight/bedrock-invocations`, 30-day retention. It is the independent audit
record of every model call (who, when, model, tokens, request and response).

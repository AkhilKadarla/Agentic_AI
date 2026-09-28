# IAM policies (policy as code)

| File | Attached to | Notes |
|---|---|---|
| `finsight-developer.json` | SSO permission set `FinSightDeveloper` (inline) | Permanent developer access, alongside the AWS managed `AmazonBedrockFullAccess` |
| `finsight-developer-with-temporary-iam.json` | Same, **only during setup** | Adds just-in-time rights to create one role; revert to `finsight-developer.json` right after |
| `bedrock-invocation-logging/` | Role `finsight-bedrock-invocation-logging` | Lets Bedrock (and only this account's Bedrock) write model invocation logs to `/finsight/bedrock-invocations` |

Replace `ACCOUNT_ID` in the templates before use. Resources are scoped by the `finsight-`
naming convention so these permissions can't touch anything else in the account.

Bedrock model invocation logging (enabled Phase 7): text only, CloudWatch Logs,
log group `/finsight/bedrock-invocations`, 30-day retention. It is the independent audit
record of every model call (who, when, model, tokens, request and response).

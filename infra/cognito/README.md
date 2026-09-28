# Cognito: who may use FinSight (Phase 8.2)

Amazon Cognito is FinSight's login system. People sign in on Cognito's hosted page; FinSight
receives a signed token (JWT) that the deployed API (AgentCore Runtime) verifies on every
request. FinSight itself never sees or stores passwords.

The IDs live in `.env` (`FINSIGHT_COGNITO_*`, see `.env.example`). Created once with the
AWS CLI under the just-in-time policy `infra/iam/finsight-developer-with-temporary-cognito.json`;
the commands below are the record of exactly how.

## Settings and why

| Setting | Value | Why |
|---|---|---|
| Sign-up | Invite only (admin creates users) | Internal tool: no public sign-up page |
| Username | Email | |
| Password | 12+ chars, upper/lower/number/symbol; invites expire in 7 days | |
| MFA | **Required**, authenticator app (TOTP) only | SMS codes can be stolen by SIM swap |
| Deletion protection | On | Deleting the pool would lock everyone out |
| Tier | Essentials | Includes managed login (v2); 10,000 monthly active users free |
| App client | Public (no secret), code flow + PKCE | A secret can't be kept safe in a laptop app; PKCE proves the app that started a login is the one finishing it |
| Direct password login | Off (refresh tokens only) | Every login goes through the hosted page, where MFA is enforced |
| Tokens | Access/ID 1 hour, refresh 12 hours, revocation on | Log in once per working day; logout kills the session |
| User existence errors | Hidden | The login page never reveals whether an email has an account |
| Callback / logout URL | `http://localhost:8501/` | Development; the deployed UI address is added in Phase 8.5 |

## How it was created

```zsh
# POOL and CLIENT are the IDs printed by the create commands (FINSIGHT_COGNITO_* in .env)
aws cognito-idp create-user-pool --profile finsight --region us-east-1 \
  --pool-name finsight-users --username-attributes email --auto-verified-attributes email \
  --admin-create-user-config AllowAdminCreateUserOnly=true \
  --policies 'PasswordPolicy={MinimumLength=12,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=true,TemporaryPasswordValidityDays=7}' \
  --account-recovery-setting 'RecoveryMechanisms=[{Priority=1,Name=verified_email}]' \
  --deletion-protection ACTIVE --user-pool-tier ESSENTIALS --user-pool-tags project=finsight

aws cognito-idp set-user-pool-mfa-config --profile finsight --region us-east-1 \
  --user-pool-id ${POOL} --software-token-mfa-configuration Enabled=true --mfa-configuration ON

aws cognito-idp create-user-pool-domain --profile finsight --region us-east-1 \
  --user-pool-id ${POOL} --domain finsight-$(openssl rand -hex 3) --managed-login-version 2

aws cognito-idp create-user-pool-client --profile finsight --region us-east-1 \
  --user-pool-id ${POOL} --client-name finsight-app --no-generate-secret \
  --allowed-o-auth-flows-user-pool-client --allowed-o-auth-flows code \
  --allowed-o-auth-scopes openid email --supported-identity-providers COGNITO \
  --callback-urls http://localhost:8501/ --logout-urls http://localhost:8501/ \
  --explicit-auth-flows ALLOW_REFRESH_TOKEN_AUTH \
  --access-token-validity 60 --id-token-validity 60 --refresh-token-validity 720 \
  --token-validity-units AccessToken=minutes,IdToken=minutes,RefreshToken=minutes \
  --enable-token-revocation --prevent-user-existence-errors ENABLED

aws cognito-idp create-managed-login-branding --profile finsight --region us-east-1 \
  --user-pool-id ${POOL} --client-id ${CLIENT} --use-cognito-provided-values
```

## Adding a user

Each person is invited by an admin; Cognito emails them a temporary password. On first
login they choose a new password and scan a QR code into an authenticator app.

```zsh
aws cognito-idp admin-create-user --profile finsight --region us-east-1 \
  --user-pool-id ${POOL} --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Cognito's built-in email sender allows about 50 emails a day, which is plenty for invites;
a firm would switch to Amazon SES with its own domain.

## Verifying tokens

Discovery URL (AgentCore's JWT authorizer reads it to find the signing keys):
`https://cognito-idp.us-east-1.amazonaws.com/${POOL}/.well-known/openid-configuration`

# Deployment

```
Browser ──HTTPS──▶ drxl-chatbot.toandrew.com (DNS A record → Elastic IP)
                    │
     ┌──────────────┴─── EC2 t4g.small, us-east-1 (ports 80/443 only, no SSH) ───┐
     │  Docker Compose:  Caddy (Let's Encrypt) → FastAPI app → Postgres + pgvector  │
     │  systemd timers:  health check · nightly cleanup + backup · daily ISSS update │
     └───────────────────────────────────────────────────────────────────────────────┘
       ECR (images) · S3 (backups, 5 days) · Parameter Store (secrets) · SES (login codes)
       CloudWatch (logs, alarms, dashboard) · SNS (alarm email) · Budgets
                    ▲
GitHub Actions: test → build ARM image → push to ECR → deploy through SSM → check /health
                (logs in to AWS with OIDC; no AWS keys stored in GitHub)
```

Everything in AWS is Terraform code in `infra/`. The server's scripts, Compose files and timers live in `deploy/` and ship inside the app image, so they're versioned with the code.

## CI/CD

- **CI** (`.github/workflows/ci.yml`) runs on every pull request and every push to `main`: `ruff`, then all tests against a throwaway Postgres service. Tests use a fake Claude client, so CI needs no API keys.
- **Deploy** (`.github/workflows/deploy.yml`) starts when CI passes on `main`, or by hand from **Actions → Deploy → Run workflow**. It assumes an AWS role through GitHub's OIDC (trusted only for this repository's `production` environment), builds the ARM64 image tagged with the commit SHA, pushes it to ECR, and runs `deploy/ssm-deploy.sh` on the server through SSM Run Command.
- **On the server,** `deploy.sh` loads the secrets, runs database migrations and starts the containers, waiting for their health checks. If the new version isn't healthy, it starts the previous image again and the workflow fails. The workflow then checks the site's `/health` endpoint from GitHub.
- The workflow reads these repository variables (none are secret): `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `ECR_REPOSITORY`, `INSTANCE_ID`, `SITE_URL`. Until `AWS_DEPLOY_ROLE_ARN` exists, Deploy skips itself.

## Secrets

API keys and generated secrets are `SecureString` parameters under `/drxl-chatbot/` in AWS Parameter Store. They never pass through Terraform, so its state holds none. `deploy/put-secrets.sh` saves them from your own computer. It asks for the Anthropic and Voyage keys with hidden input, and creates `JWT_SECRET`, `IP_HASH_SECRET` and `POSTGRES_PASSWORD` once. Running it again never changes those, because changing them would log everyone out or lock the app out of its database.

```bash
AWS_PROFILE=<your profile> deploy/put-secrets.sh
```

On the server, `load-secrets.sh` writes them into root-only env files at each deploy. Non-secret settings come from `deploy/app.env.defaults`.

## First-time setup

1. **Terraform state bucket**, once: `cd infra/bootstrap && terraform init && terraform apply`.
2. **Everything else:** copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars` and set `alarm_email`, then `cd infra && terraform init && terraform plan -out=tfplan && terraform apply tfplan`. Confirm the SNS email AWS sends.
3. **DNS:** add the records from `terraform output dns_records` at the domain's DNS provider: the A record, 3 DKIM CNAMEs for SES, and the MAIL FROM MX/SPF and DMARC records.
4. **Secrets:** run `deploy/put-secrets.sh`.
5. **SES:** request production access in the SES console. Until it's approved, SES only emails addresses verified in SES.
6. **GitHub:** create the `production` environment (deployments from `main` only) and the repository variables from `terraform output github_variables`.
7. **First deploy and index:** merge to `main` (or push an image and run `deploy/ssm-deploy.sh <tag>`), then fill the search index with `deploy/ssm-run.sh 'systemctl start drxl-chatbot-update.service'`.

The commands that talk to the server need `AWS_REGION`, `INSTANCE_ID` and (for deploys) `ECR_REPOSITORY` set, plus an AWS login (`aws login --profile <your profile>`).

## Operations

| Task | How |
|---|---|
| Run a command on the server | `deploy/ssm-run.sh '<command>'` (SSM Run Command, no SSH); for an interactive shell, **EC2 → Connect → Session Manager** |
| See what's running | `deploy/ssm-run.sh '/opt/drxl-chatbot/compose.sh ps'` |
| Read logs | CloudWatch log groups `/drxl-chatbot/app`, `/drxl-chatbot/caddy` and `/drxl-chatbot/jobs`, e.g. `aws logs tail /drxl-chatbot/app --follow` |
| Roll back a bad release | Revert the commit and merge, so `main` matches what runs. In an emergency, `deploy/ssm-deploy.sh <earlier commit SHA>` (ECR keeps the last 10 images) |
| Test the newest backup | `deploy/ssm-run.sh '/opt/drxl-chatbot/restore.sh'` restores it into a scratch database and compares row counts with the live one |
| Restore over the live database | In a Session Manager shell: `sudo /opt/drxl-chatbot/restore.sh <backup key> --replace` (asks you to type REPLACE) |
| Update the ISSS index now | `deploy/ssm-run.sh 'systemctl start drxl-chatbot-update.service'` |

Scheduled jobs (UTC):
- **Every 5 minutes:** a health check through Caddy.
- **08:00:** chats idle for longer than `CHAT_RETENTION_DAYS` are deleted, then a `pg_dump` backup goes to S3, which keeps backups for 5 days.
- **09:00:** the ISSS site is crawled and changed pages are indexed.

## Monitoring

The CloudWatch dashboard `drxl-chatbot` shows questions per day, feedback, errors, health checks, and the server's CPU, memory and disk. Alarms email the address in `alarm_email` when any of these happen:
- the site fails health checks for 10 minutes;
- the server fails AWS status checks (it's then recovered or rebooted automatically);
- the disk is over 80% full;
- answers or searches keep failing;
- a login email can't be sent;
- the daily spending limit is reached;
- a nightly job fails.

An AWS budget also sends warnings as monthly spending approaches its limit.

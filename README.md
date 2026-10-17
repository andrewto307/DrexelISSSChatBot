# DrexelISSSChatBot

An unofficial chatbot that answers international students' questions using the public website of Drexel University's International Students and Scholars Services (ISSS). It searches the ISSS pages first, then has Claude answer from what it found, with links to the pages it used.

Not affiliated with Drexel University or ISSS, and not legal advice.

Live at https://drxl-chatbot.toandrew.com (sign-up needs a `@drexel.edu` email).

## How it works

1. **Crawl:** downloads the ISSS pages and the ISSS documents they link to. Links to other sites are recorded but never read.
2. **Index:** splits each page into sections, embeds them with Voyage AI, and stores them in Postgres with pgvector and a full-text index.
3. **Answer:** hybrid search (vector and keyword results merged with reciprocal rank fusion) picks the most relevant sections. Newer announcements that update a linked announcement are added too. Claude then answers from them.
4. **Chat:** a FastAPI app streams answers to a web page, with source links, feedback buttons, and conversations saved in Postgres.
5. **Accounts:** anyone can open the chat page, but asking a question needs an account, and only verified `@drexel.edu` addresses can sign up. Each person sees only the chat they're in; old chats are deleted after 15 days. Daily limits cap questions per person and total spending per day.
6. **Deployment:** one AWS server runs the app, Postgres and Caddy in Docker, built with Terraform and deployed by GitHub Actions on every merge to `main` (see [Deployment](#deployment)).

## Setup

Requires Python 3.12+, Docker, an [Anthropic API key](https://console.anthropic.com/) and a [Voyage AI API key](https://dashboard.voyageai.com/).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt         # the app's packages plus pytest, ruff and Playwright
python -m playwright install chromium   # only needed for the browser tests
cp .env.example .env                    # then fill in ANTHROPIC_API_KEY, VOYAGE_API_KEY and JWT_SECRET
docker compose up -d                    # Postgres + pgvector on localhost:5433
python scripts/check_setup.py
```

## Usage

```bash
python scripts/update_index.py all      # crawl the site, then embed new or changed pages
uvicorn app.main:app --reload           # the chat page at http://localhost:8000
python scripts/chat_cli.py --sources    # or chat in the terminal
python -m isss_bot.search "Can I do CPT in my first year?"
```

Set `DEV_MODE=true` to show each answer's cost and search queries on the page. Database migrations run automatically; `python scripts/migrate.py` runs them by hand.

## Accounts

Open http://localhost:8000, click **Log in** in the top right, then **Create an account** with a `@drexel.edu` address. Locally, emails aren't sent: the sign-up and password reset codes are printed in the terminal running uvicorn.

| Setting | Default | What it does |
|---|---|---|
| `JWT_SECRET` | random at each start | Signs login sessions. Set it to a long random value, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`, or everyone is logged out whenever the server restarts. |
| `COOKIE_SECURE` | `true` | Sends the session cookie over HTTPS only. Chrome and Firefox accept it on `http://localhost`; if logging in doesn't stick in another browser locally, set it to `false` there. |
| `ALLOWED_EMAIL_DOMAINS` | `drexel.edu` | Comma-separated email domains that can sign up. |
| `DAILY_QUESTION_LIMIT` | `30` | Questions per person per day. |
| `DAILY_COST_CAP_USD` | `3` | Total Claude spending per day before the assistant rests until midnight (Philadelphia time). |

## Feedback and evaluation

```bash
python scripts/review_feedback.py               # answers students rated not helpful
python scripts/review_feedback.py --questions 20 # recent questions as draft eval lines
python evals/run_eval.py --label my-run --retrieval-only   # search quality only
python evals/run_eval.py --label my-run                    # answers graded by Claude
```

`evals/questions.jsonl` holds 82 test questions. Each one lists the ISSS pages that should answer it and the key facts a correct answer needs. They cover facts, procedures, answers spread over several pages, follow-up questions, exact terms such as form numbers, questions in seven other languages, rules that changed over time, and questions the ISSS site doesn't cover, which the assistant should decline. Claude Opus 5.5 grades each answer: is it correct, is everything it says backed by the ISSS text it was given, and is it in the student's language. Whether the answer links an expected page is checked in code. Run results are saved in `evals/results/`, which isn't committed.

### Latest results

Full run on October 15, 2026, with 80 questions (the 2 newest were added after it):

| Check | Result |
|---|---|
| Search puts an expected page in the top 6 | 100% (73/73) |
| Answer is correct | 100% (73/73) |
| Question outside the ISSS site is declined | 100% (7/7) |
| Everything in the answer is backed by ISSS text | 99% (79/80) |
| Answer links an expected page | 100% (73/73) |
| Answer is in the student's language | 100% (80/80) |

### What the evaluations decided

- **Chat model: Claude Sonnet 5.5 at low effort.** Haiku 4.5 added unsupported claims to nearly a third of its answers and answered a question it should have declined. Opus 5.5 was as accurate as Sonnet but costs more and stuck to the sources slightly less often.
- **Search: vector search blended with keyword matches, weighted by how rare each word is.** This raised the share of questions with an expected page in the top 6 from 95% to 100%.
- **Embeddings: `voyage-4`.** The larger `voyage-4-large` found no more pages.
- **Follow-up questions are searched two ways at once:** rewritten as a standalone question by Claude Haiku 4.5, and as the conversation's questions joined together. It was the only setup that got every follow-up right.
- **Prompt rules:** forbidding guesses and outside websites raised the share of fully backed answers from 95% to 99%. Putting links in the sentences they support, instead of a list at the end, made answers about 10% shorter.
- **Announcements older than 3 years rank slightly lower.** Their share of search slots fell from 25 to 4 of 480, and no expected page was lost.

**Known issue:** when search returns both a proposed rule and the final rule that replaced it, an answer occasionally carries a detail from the proposal over to the final rule.

## Deployment

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

Everything in AWS is Terraform code in `infra/`. The server's scripts, Compose files and timers live in `deploy/` and ship inside the app image, so they're versioned with the code. Infrastructure costs about $18–19 a month (mostly the server and its fixed IP), plus Claude usage.

### CI/CD

- **CI** (`.github/workflows/ci.yml`) runs on every pull request and every push to `main`: `ruff`, then all tests against a throwaway Postgres service. Tests use a fake Claude client, so CI needs no API keys.
- **Deploy** (`.github/workflows/deploy.yml`) starts when CI passes on `main`, or by hand from **Actions → Deploy → Run workflow**. It assumes an AWS role through GitHub's OIDC (trusted only for this repository's `production` environment), builds the ARM64 image tagged with the commit SHA, pushes it to ECR, and runs `deploy/ssm-deploy.sh` on the server through SSM Run Command.
- **On the server,** `deploy.sh` loads the secrets, runs database migrations and starts the containers, waiting for their health checks. If the new version isn't healthy, it starts the previous image again and the workflow fails. The workflow then checks `https://drxl-chatbot.toandrew.com/health` from GitHub.
- The workflow reads these repository variables (none are secret): `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN`, `ECR_REPOSITORY`, `INSTANCE_ID`, `SITE_URL`. Until `AWS_DEPLOY_ROLE_ARN` exists, Deploy skips itself.

### Secrets

API keys and generated secrets are `SecureString` parameters under `/drxl-chatbot/` in AWS Parameter Store. They never pass through Terraform, so its state holds none. `deploy/put-secrets.sh` saves them from your own computer: it asks for the Anthropic and Voyage keys with hidden input and creates `JWT_SECRET`, `IP_HASH_SECRET` and `POSTGRES_PASSWORD` once (running it again never changes those, which would log everyone out or lock the app out of its database).

```bash
AWS_PROFILE=<your profile> deploy/put-secrets.sh
```

On the server, `load-secrets.sh` writes them into root-only env files; non-secret settings come from `deploy/app.env.defaults` (`MAILER=ses`, `MAIL_FROM`, `TRUSTED_PROXIES`, region).

### First-time setup

1. **Terraform state bucket**, once: `cd infra/bootstrap && terraform init && terraform apply`.
2. **Everything else:** copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars` and set `alarm_email`, then `cd infra && terraform init && terraform plan -out=tfplan && terraform apply tfplan`. Confirm the SNS email AWS sends.
3. **DNS:** add the records from `terraform output dns_records` at the domain's DNS provider: the A record, 3 DKIM CNAMEs for SES, and the MAIL FROM MX/SPF and DMARC records.
4. **Secrets:** run `deploy/put-secrets.sh`.
5. **SES:** request production access in the SES console. Until it's approved, SES only emails addresses verified in SES.
6. **GitHub:** create the `production` environment (deployments from `main` only) and the repository variables from `terraform output github_variables`.
7. **First deploy and index:** merge to `main` (or push an image and run `deploy/ssm-deploy.sh <tag>`), then fill the search index with `deploy/ssm-run.sh 'systemctl start drxl-chatbot-update.service'`.

The commands that talk to the server need `AWS_REGION`, `INSTANCE_ID` and (for deploys) `ECR_REPOSITORY` set, plus an AWS login (`aws login --profile <your profile>`).

### Running it

| Task | How |
|---|---|
| Run a command on the server | `deploy/ssm-run.sh '<command>'` (SSM Run Command, no SSH); for an interactive shell, **EC2 → Connect → Session Manager** |
| See what's running | `deploy/ssm-run.sh '/opt/drxl-chatbot/compose.sh ps'` |
| Read logs | CloudWatch log groups `/drxl-chatbot/app`, `/drxl-chatbot/caddy` and `/drxl-chatbot/jobs`, e.g. `aws logs tail /drxl-chatbot/app --follow` |
| Roll back a bad release | Revert the commit and merge, so `main` matches what runs. In an emergency, `deploy/ssm-deploy.sh <earlier commit SHA>` (ECR keeps the last 10 images) |
| Test the newest backup | `deploy/ssm-run.sh '/opt/drxl-chatbot/restore.sh'` restores it into a scratch database and compares row counts with the live one |
| Restore over the live database | In a Session Manager shell: `sudo /opt/drxl-chatbot/restore.sh <backup key> --replace` (asks you to type REPLACE) |
| Update the ISSS index now | `deploy/ssm-run.sh 'systemctl start drxl-chatbot-update.service'` |

Scheduled jobs (UTC): a health check through Caddy every 5 minutes; at 08:00, deleting chats idle for 15 days (`CHAT_RETENTION_DAYS`) and then a `pg_dump` backup to S3, which keeps backups for 5 days; at 09:00, crawling the ISSS site and indexing changed pages.

### Monitoring

The CloudWatch dashboard `drxl-chatbot` shows questions and Claude cost per day, feedback, errors, health checks, and the server's CPU, memory and disk. Alarms email the address in `alarm_email` when the site stops passing health checks for 10 minutes, the server fails AWS's status checks (it's recovered or rebooted automatically), the disk is over 80% full, answers or searches keep failing, a login email can't be sent, the daily cost cap is reached, or a nightly job fails. An AWS budget warns at 80% and 100% of $25 a month.

## Tests

```bash
pytest                       # no API calls; uses a separate isss_test database
pytest -m "not browser"      # skip the Playwright browser tests
ruff check . && ruff format --check .
```

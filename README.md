# ISSS Assistant

[![CI](https://github.com/andrewto307/DrexelISSSChatBot/actions/workflows/ci.yml/badge.svg)](https://github.com/andrewto307/DrexelISSSChatBot/actions/workflows/ci.yml)

An unofficial assistant that answers international students' questions from the public website of Drexel University's International Students and Scholars Services (ISSS). Every answer comes from the ISSS pages and links to the pages it used.

**Try it:** [drxl-chatbot.toandrew.com](https://drxl-chatbot.toandrew.com) (sign-up requires a `@drexel.edu` email address)

> Not affiliated with Drexel University or ISSS. Answers are for information only and are not legal advice.

## Features

- **Grounded answers:** answers only from ISSS pages and documents, links its sources inline, and says so when the site doesn't cover a question.
- **Up to date:** the site is re-crawled daily, and newer announcements take precedence over older ones.
- **Conversational:** follow-up questions build on the chat, and replies come in the student's language.
- **Built for real use:** streaming answers with source cards and feedback, sign-in for verified Drexel email addresses, and usage limits per person and per day.

## How it works

```
ISSS website ──crawl──▶ page sections ──embed──▶ Postgres (pgvector + full-text index)
                                                          │
question ──▶ hybrid search (vector + keyword) ──▶ top sections ──▶ Claude ──▶ answer with links
```

1. **Crawl:** downloads the ISSS pages and the ISSS documents they link to, and detects changed pages by their content.
2. **Index:** splits pages into sections, embeds them with Voyage AI, and stores them in Postgres with pgvector and a full-text index.
3. **Search:** merges vector and keyword results with reciprocal rank fusion. Follow-up questions are rewritten into standalone searches, and newer announcements that update a retrieved one are added.
4. **Answer:** Claude Sonnet 5.5 answers from the retrieved sections, and a FastAPI app streams the answer to the browser.

## Quickstart

Requires Python 3.12+, Docker, an [Anthropic API key](https://console.anthropic.com/) and a [Voyage AI API key](https://dashboard.voyageai.com/).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # add ANTHROPIC_API_KEY, VOYAGE_API_KEY and JWT_SECRET
docker compose up -d                 # Postgres with pgvector on localhost:5433
python scripts/check_setup.py
python scripts/update_index.py all   # crawl the ISSS site and build the index
uvicorn app.main:app --reload        # open http://localhost:8000
```

Locally, sign-up and password-reset codes are printed in the uvicorn terminal instead of being emailed. To chat in the terminal instead, run `python scripts/chat_cli.py`.

## Configuration

Settings are environment variables, read from `.env` during local development.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` | | API keys for answering and embeddings |
| `JWT_SECRET` | random per start | Signs login sessions; set it so sessions survive restarts |
| `ALLOWED_EMAIL_DOMAINS` | `drexel.edu` | Email domains allowed to sign up |
| `DAILY_QUESTION_LIMIT` | `30` | Questions per person per day |
| `DAILY_COST_CAP_USD` | `3` | Daily API spending limit, after which the assistant pauses until midnight |
| `CHAT_RETENTION_DAYS` | `15` | Days before inactive chats are deleted |
| `DEV_MODE` | off | Shows search queries and usage under each answer |

All settings are in [`isss_bot/config.py`](isss_bot/config.py).

## Evaluation

Claude Opus 5.5 grades each answer for correctness, for whether every claim is backed by the ISSS text the assistant was given, and for language. There are two question sets: 87 development questions used while building the system, and 50 test questions written separately and run once on the final version.

| | Development set | Test set |
|---|---|---|
| Correct answers | 100% | 88% |
| Out-of-scope questions declined | 100% | 100% |
| Answers fully backed by ISSS text | 98% | 96% |
| Expected page found by search | 100% | 98% |

The development scores are optimistic, since the system was tuned on those questions. See [docs/evaluation.md](docs/evaluation.md) for the method, the question types and the design decisions the results informed.

## Deployment

The live site runs on a single AWS EC2 instance, with Caddy (automatic HTTPS), the app and Postgres in Docker Compose. Terraform in [`infra/`](infra) defines the AWS resources. GitHub Actions tests every change, then deploys `main` through OIDC and rolls back automatically if the new version fails its health checks. Scheduled jobs refresh the index daily and back up the database nightly.

See [docs/deployment.md](docs/deployment.md) for the architecture, first-time setup and operations.

## Development

```bash
pytest                                             # unit, API and browser tests; no API calls
pytest -m "not browser"                            # skip the Playwright browser tests
ruff check . && ruff format --check .
python -m isss_bot.search "Can I do CPT in my first year?"   # inspect search results
```

The browser tests need `python -m playwright install chromium`, and the tests use a separate `isss_test` database. Database migrations run automatically at startup.

## Project structure

```
app/          FastAPI app, accounts and the chat page (static/)
isss_bot/     crawling, indexing, search and answering
scripts/      index updates, terminal chat and maintenance
evals/        question sets and the evaluation runner
migrations/   database schema
infra/        Terraform for AWS
deploy/       server scripts, Compose files and timers
tests/        pytest suite
```

## License

[Apache 2.0](LICENSE)

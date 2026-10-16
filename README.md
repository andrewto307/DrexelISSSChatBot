# DrexelISSSChatBot

An unofficial chatbot that answers international students' questions using the public website of Drexel University's International Students and Scholars Services (ISSS). It searches the ISSS pages first, then has Claude answer from what it found, with links to the pages it used.

Not affiliated with Drexel University or ISSS, and not legal advice.

## How it works

1. **Crawl:** downloads the ISSS pages and the ISSS documents they link to. Links to other sites are recorded but never read.
2. **Index:** splits each page into sections, embeds them with Voyage AI, and stores them in Postgres with pgvector and a full-text index.
3. **Answer:** hybrid search (vector and keyword results merged with reciprocal rank fusion) picks the most relevant sections. Newer announcements that update a linked announcement are added too. Claude then answers from them.
4. **Chat:** a FastAPI app streams answers to a web page, with source links, feedback buttons, and conversations saved in Postgres.
5. **Accounts:** anyone can open the chat page, but asking a question needs an account, and only verified `@drexel.edu` addresses can sign up. Each person's chats are private to them, and daily limits cap questions per person and total spending per day.

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

## Tests

```bash
pytest                       # no API calls; uses a separate isss_test database
pytest -m "not browser"      # skip the Playwright browser tests
ruff check . && ruff format --check .
```

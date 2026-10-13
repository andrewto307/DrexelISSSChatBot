# DrexelISSSChatBot

An unofficial chatbot that answers international students' questions using the public website of Drexel University's International Students and Scholars Services (ISSS). It searches the ISSS pages first, then has Claude answer from what it found, with links to the pages it used.

Not affiliated with Drexel University or ISSS, and not legal advice.

## How it works

1. **Crawl:** downloads the ISSS pages and the ISSS documents they link to. Links to other sites are recorded but never read.
2. **Index:** splits each page into sections, embeds them with Voyage AI, and stores them in Postgres with pgvector and a full-text index.
3. **Answer:** hybrid search (vector and keyword results merged with reciprocal rank fusion) picks the most relevant sections, and Claude answers from them.

## Setup

Requires Python 3.12+, Docker, an [Anthropic API key](https://console.anthropic.com/) and a [Voyage AI API key](https://dashboard.voyageai.com/).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in ANTHROPIC_API_KEY and VOYAGE_API_KEY
docker compose up -d          # Postgres + pgvector on localhost:5433
python scripts/check_setup.py
```

## Usage

```bash
python scripts/update_index.py all      # crawl the site, then embed new or changed pages
python -m isss_bot.search "Can I do CPT in my first year?"
python scripts/chat_cli.py --sources    # chat in the terminal
```

## Tests and evaluation

```bash
pytest                                  # no API calls; database tests roll back their changes
ruff check . && ruff format --check .
python evals/run_eval.py --label my-run --retrieval-only   # search quality only
python evals/run_eval.py --label my-run                    # answers graded by Claude
```

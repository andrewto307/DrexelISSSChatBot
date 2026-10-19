import argparse
import json
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
import voyageai.error

from isss_bot import config, db
from isss_bot.answer import (
    Answer,
    AnswerError,
    Conversation,
    concat_query,
    format_sources,
    retrieve,
    search_queries_for,
)
from isss_bot.embed import embed_queries, embed_query
from isss_bot.pricing import cost_usd
from isss_bot.search import DEFAULT_LIMIT, SearchResult, search
from isss_bot.urls import linked_url_keys, url_key

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = ROOT / "evals" / "questions.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"
DEFAULT_GRADER_MODEL = "claude-opus-5-5"

GRADER_SYSTEM_PROMPT = """You grade answers from a chatbot for international students. The chatbot must answer only from excerpts of Drexel University's International Students and Scholars Services (ISSS) website, which are shown to you exactly as the chatbot saw them."""

GRADER_INSTRUCTIONS = """Grade the chatbot's answer.

- correct: true if the answer gives the core facts in <reference> and doesn't contradict it. Small omissions are fine. For an out-of-scope question, correct means the answer says it couldn't find this on the ISSS website or that it can only help with ISSS topics, and it doesn't answer from general knowledge. For a mixed question, which the ISSS website only partly answers, correct also requires the answer to say which part it couldn't find on the ISSS website; leaving that part out without saying so is not a small omission.
- grounded: true if every factual claim in the answer is supported by the excerpts. Adding facts that aren't in the excerpts, even true ones, makes it false. Pointing the student to ISSS, an ISSS advisor, the ISSS website or where ISSS contact details are doesn't count as a claim.
- right_language: true if the answer is written in the same language as the question.
- explanation: one or two sentences on any problem found."""

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "correct": {"type": "boolean"},
        "grounded": {"type": "boolean"},
        "right_language": {"type": "boolean"},
        "explanation": {"type": "string"},
    },
    "required": ["correct", "grounded", "right_language", "explanation"],
    "additionalProperties": False,
}


class QueryVectors:
    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self.embed_lock = threading.Lock()

    def prefetch(self, queries: list[str]) -> None:
        missing = sorted(set(queries) - self.vectors.keys())
        if missing:
            self.vectors.update(zip(missing, embed_queries(missing), strict=True))

    def search(self, conn, query: str, limit: int = DEFAULT_LIMIT) -> list[SearchResult]:
        with self.lock:
            vector = self.vectors.get(query)
        if vector is None:
            with self.embed_lock:
                vector = self.vectors.get(query) or embed_query(query)
            with self.lock:
                self.vectors[query] = vector
        return search(conn, query, limit=limit, query_vector=vector)


def planned_queries(item: dict) -> list[str]:
    asked: list[str] = []
    queries = []
    for question in [*item["history"], item["question"]]:
        queries.append(concat_query(question, asked) if asked else question)
        asked.append(question)
    return queries


def load_questions(path: Path, ids: set[str] | None, types: set[str] | None) -> list[dict]:
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [item for item in items if (not ids or item["id"] in ids) and (not types or item["type"] in types)]


def score_retrieval(item: dict, results: list[SearchResult]) -> dict:
    expected = {url_key(url) for url in item["expected_urls"]}
    ranks = [rank for rank, result in enumerate(results, start=1) if url_key(result.url) in expected]
    return {
        "hit": bool(ranks) if expected else None,
        "first_rank": ranks[0] if ranks else None,
        "retrieved": [{"url": result.url, "section": result.heading_path} for result in results],
    }


def cites_expected(item: dict, text: str) -> bool | None:
    if not item["expected_urls"]:
        return None
    return bool(linked_url_keys(text) & {url_key(url) for url in item["expected_urls"]})


def grade(client: anthropic.Anthropic, model: str, item: dict, answer: Answer) -> tuple[dict, float]:
    earlier = "\n".join(f"- {text}" for text in item["history"]) or "(none)"
    content = (
        f"<question_type>{item['type']}</question_type>\n"
        f"<earlier_questions>\n{earlier}\n</earlier_questions>\n"
        f"<question>{item['question']}</question>\n"
        f"<reference>{item['notes']}</reference>\n\n"
        f"{format_sources(answer.sources)}\n\n"
        f"<answer>\n{answer.text}\n</answer>\n\n{GRADER_INSTRUCTIONS}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=GRADER_SYSTEM_PROMPT,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": GRADE_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text), cost_usd(model, response.usage)


def _new_record(item: dict) -> dict:
    return {"id": item["id"], "type": item["type"], "question": item["question"], "history": item["history"]}


def _retrieval_record(item: dict, queries: list[str], query_cost: float, vectors: QueryVectors) -> dict:
    record = _new_record(item)
    with db.connect() as conn:
        results = retrieve(conn, queries, vectors.search)
    record.update(search_queries=queries, cost=query_cost)
    record.update(score_retrieval(item, results))
    return record


def _answer_record(item: dict, args: argparse.Namespace, client: anthropic.Anthropic, vectors: QueryVectors) -> dict:
    record = _new_record(item)
    with db.connect() as conn:
        conversation = Conversation(
            conn,
            client,
            model=args.model,
            effort=args.effort,
            followup_search=args.followup_search,
            search=vectors.search,
        )
        history_cost = 0.0
        for earlier in item["history"]:
            history_cost += next(event for event in conversation.ask(earlier) if isinstance(event, Answer)).cost_usd
        answer = next(event for event in conversation.ask(item["question"]) if isinstance(event, Answer))

    record.update(search_queries=answer.search_queries, answer=answer.text, stop_reason=answer.stop_reason)
    record.update(score_retrieval(item, answer.sources))
    record["cites_expected_url"] = cites_expected(item, answer.text)
    record["answer_cost"] = answer.cost_usd
    record["output_tokens"] = answer.usage.output_tokens
    record["grade"], grade_cost = grade(client, args.grader_model, item, answer)
    record["cost"] = answer.cost_usd + history_cost + grade_cost
    return record


def safely(item: dict, work) -> dict:
    try:
        return work()
    except (AnswerError, anthropic.APIError, voyageai.error.VoyageError, json.JSONDecodeError) as error:
        return {"id": item["id"], "type": item["type"], "question": item["question"], "error": repr(error), "cost": 0.0}


def rate(values: list) -> str:
    known = [value for value in values if value is not None]
    if not known:
        return "-"
    return f"{100 * sum(known) / len(known):.0f}% ({sum(known)}/{len(known)})"


def summarize(records: list[dict], retrieval_only: bool) -> dict:
    completed = [record for record in records if "error" not in record]
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in completed:
        groups[record["type"]].append(record)
    groups = {"all": completed, **dict(sorted(groups.items()))}

    summary = {}
    for name, group in groups.items():
        row = {"count": len(group), "hit@6": rate([r["hit"] for r in group])}
        if not retrieval_only:
            in_scope = [r for r in group if r["type"] != "out-of-scope"]
            row["correct"] = rate([r["grade"]["correct"] for r in in_scope])
            row["declined"] = rate([r["grade"]["correct"] for r in group if r["type"] == "out-of-scope"])
            row["grounded"] = rate([r["grade"]["grounded"] for r in group])
            row["cites_expected"] = rate([r["cites_expected_url"] for r in in_scope])
            row["right_language"] = rate([r["grade"]["right_language"] for r in group])
            row["avg_answer_cost"] = f"${sum(r['answer_cost'] for r in group) / len(group):.4f}" if group else "-"
        summary[name] = row
    summary["errors"] = len(records) - len(completed)
    summary["total_cost"] = f"${sum(record['cost'] for record in records):.4f}"
    return summary


def print_summary(summary: dict) -> None:
    rows = {name: row for name, row in summary.items() if isinstance(row, dict)}
    columns = list(next(iter(rows.values())).keys())
    widths = {column: max(len(column), *(len(str(row.get(column, ""))) for row in rows.values())) for column in columns}
    print("\n" + "type".ljust(14) + "  ".join(column.ljust(widths[column]) for column in columns))
    for name, row in rows.items():
        print(name.ljust(14) + "  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))
    print(
        f"\nTotal cost of this run: {summary['total_cost']}. Questions that failed with an error: {summary['errors']}"
    )


def print_misses(records: list[dict], retrieval_only: bool) -> None:
    for record in records:
        if "error" in record:
            print(f"  {record['id']} (error): {record['error']}")
            continue
        problems = []
        if record["hit"] is False:
            problems.append("expected page not retrieved")
        if not retrieval_only:
            grade_ = record["grade"]
            if not grade_["correct"]:
                problems.append("incorrect")
            if not grade_["grounded"]:
                problems.append("not grounded")
            if not grade_["right_language"]:
                problems.append("wrong language")
        if problems:
            explanation = "" if retrieval_only else f" {record['grade']['explanation']}"
            print(f"  {record['id']} ({', '.join(problems)}): {record['question']}{explanation}")


def code_version() -> str:
    def git(*command: str) -> str:
        return subprocess.run(["git", *command], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    commit = git("rev-parse", "--short", "HEAD") or "unknown"
    return f"{commit}+uncommitted" if git("status", "--porcelain", "--untracked-files=no") else commit


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and answers against a question set.")
    parser.add_argument("--label", required=True, help="name for this run, used in the results file name")
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH, help="question set (JSON lines)")
    parser.add_argument("--retrieval-only", action="store_true", help="only check search results (no Claude answers)")
    parser.add_argument("--followup-search", choices=["concat", "rewrite"], default=config.FOLLOWUP_SEARCH)
    parser.add_argument("--model", default=config.CHAT_MODEL)
    parser.add_argument("--effort", default=config.CHAT_EFFORT, help='effort level, or "none" to omit it')
    parser.add_argument("--grader-model", default=DEFAULT_GRADER_MODEL)
    parser.add_argument("--ids", help="comma-separated question ids")
    parser.add_argument("--types", help="comma-separated question types")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.effort = None if args.effort == "none" else args.effort

    items = load_questions(
        args.questions,
        set(args.ids.split(",")) if args.ids else None,
        set(args.types.split(",")) if args.types else None,
    )
    client = anthropic.Anthropic(max_retries=4)
    vectors = QueryVectors()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        if args.retrieval_only:
            planned = list(
                pool.map(
                    lambda item: search_queries_for(item["question"], item["history"], args.followup_search, client),
                    items,
                )
            )
            vectors.prefetch([query for queries, _ in planned for query in queries])
            records = list(
                pool.map(
                    lambda pair: safely(pair[0], lambda: _retrieval_record(pair[0], *pair[1], vectors)),
                    zip(items, planned, strict=True),
                )
            )
        else:
            vectors.prefetch([query for item in items for query in planned_queries(item)])
            records = list(
                pool.map(lambda item: safely(item, lambda: _answer_record(item, args, client, vectors)), items)
            )

    summary = summarize(records, args.retrieval_only)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{date.today().isoformat()}-{args.label}.json"
    settings = {
        "label": args.label,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "questions": args.questions.name,
        "commit": code_version(),
        "retrieval_only": args.retrieval_only,
        "followup_search": args.followup_search,
        "voyage_model": config.VOYAGE_MODEL,
    }
    if not args.retrieval_only:
        settings.update(model=args.model, effort=args.effort, grader_model=args.grader_model)
    report = {"settings": settings, "summary": summary, "records": records}
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print_summary(summary)
    print("\nProblems:")
    print_misses(records, args.retrieval_only)
    seconds = time.monotonic() - started
    print(f"\nFinished {len(records)} questions in {seconds:.0f}s. Results: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

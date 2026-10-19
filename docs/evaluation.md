# Evaluation

The assistant is measured with two question sets, both in `evals/`. Each question lists the ISSS pages that should answer it and the facts a correct answer needs.

- **Development set** (`questions.jsonl`, 87 questions): used while building and tuning the system. It covers facts, procedures, answers spread over several pages, follow-up questions, exact terms such as form numbers, questions in seven other languages, rules that changed over time, questions the ISSS site doesn't cover (which the assistant should decline), and questions it only partly covers (where the assistant should answer that part and say what it couldn't find).
- **Test set** (`test_set.jsonl`, 50 questions): written separately by hand, never used for tuning, and run once on a frozen version.

## Grading

Claude Opus 5.5 grades each answer against the question's notes and the ISSS text the assistant was given:

- **Correct:** gives the key facts and doesn't contradict them. An out-of-scope question counts as correct only if the answer says it couldn't find the information on the ISSS website, and a partly covered question only if the answer says which part it couldn't find.
- **Grounded:** every factual claim is supported by the ISSS text.
- **Right language:** the answer is in the language of the question.

Code checks whether search found an expected page and whether the answer links one.

## Running

```bash
python evals/run_eval.py --label my-run --retrieval-only                   # search quality only
python evals/run_eval.py --label my-run                                    # answers graded by Claude
python evals/run_eval.py --label my-run --questions evals/test_set.jsonl   # the test set
python scripts/review_feedback.py                   # answers students rated not helpful
python scripts/review_feedback.py --questions 20    # recent questions as draft eval lines
```

Each run prints a table by question type and saves the details to `evals/results/`, which isn't committed. Results record the commit they ran on.

## Results

Both runs were on October 18, 2026, on the same code.

| Check | Development set (87) | Test set (50) |
|---|---|---|
| Search puts an expected page in the top 6 | 100% (80/80) | 98% (41/42) |
| Answer is correct | 100% (80/80) | 88% (37/42) |
| Partly covered question: answers that part, says what it couldn't find | 100% (5/5) | 87% (13/15) |
| Question outside the ISSS site is declined | 100% (7/7) | 100% (8/8) |
| Everything in the answer is backed by ISSS text | 98% (85/87) | 96% (48/50) |
| Answer links an expected page | 100% (80/80) | 93% (39/42) |
| Answer is in the student's language | 100% (87/87) | 100% (50/50) |

The development scores are optimistic, since the system was adjusted until those questions passed. The test set is the better estimate of how the assistant handles new questions, though with 42 answerable questions its figures carry a margin of several points.

## Design decisions

The development set drove these choices:

- **Chat model: Claude Sonnet 5.5 at low effort.** Haiku 4.5 added unsupported claims to nearly a third of its answers and answered a question it should have declined. Opus 5.5 was no more accurate and stuck to the sources slightly less often.
- **Hybrid search.** Vector search blended with keyword matches, weighted by how rare each word is, finds an expected page in the top 6 for every development question.
- **Embeddings: `voyage-4`.** The larger `voyage-4-large` did no better.
- **Follow-up questions are searched two ways:** rewritten as a standalone question by Claude Haiku 4.5, and as the conversation's questions joined together. Only this combination got every follow-up right.
- **Prompt rules.** Forbidding guesses and outside websites raised the share of fully backed answers from 95% to 99%. Putting links in the sentences they support, instead of a list at the end, made answers about 10% shorter.
- **Older announcements rank lower.** Announcements more than 3 years old fell from about 5% of search results to under 1%, and no expected page was lost.

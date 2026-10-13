import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isss_bot import db
from isss_bot.answer import Answer, AnswerError, Conversation, TextDelta


def print_sources(answer: Answer) -> None:
    print(f"\n(search: {' + '.join(answer.search_queries)})")
    for rank, source in enumerate(answer.sources, start=1):
        print(f"  {rank}. {source.heading_path}  {source.url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the ISSS assistant in the terminal.")
    parser.add_argument("--sources", action="store_true", help="show the search query and retrieved sections")
    args = parser.parse_args()

    with db.connect() as conn:
        conversation = Conversation(conn)
        print("Ask about Drexel ISSS. Type /new for a new chat, or press Enter on an empty line to quit.")
        while True:
            try:
                question = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if question.lower() in {"", "quit", "exit"}:
                break
            if question == "/new" or conversation.is_full:
                if conversation.is_full:
                    print(f"[This chat reached {conversation.max_questions} questions, so a new one was started.]")
                conversation = Conversation(conn)
                if question == "/new":
                    continue

            print("\nBot: ", end="", flush=True)
            try:
                for event in conversation.ask(question):
                    if isinstance(event, TextDelta):
                        print(event.text, end="", flush=True)
                    else:
                        answer = event
            except AnswerError as error:
                print(f"\n[{error}]")
                continue

            if answer.refused:
                print("\n[The model declined to answer, so ignore any partial text above. Try rephrasing.]")
            elif answer.cut_off:
                print("\n[The answer was cut off.]")
            if args.sources:
                print_sources(answer)
            usage = answer.usage
            print(
                f"\n(cost: ${answer.cost_usd:.4f} | input {usage.input_tokens}, "
                f"cache write {usage.cache_creation_input_tokens}, cache read {usage.cache_read_input_tokens}, "
                f"output {usage.output_tokens})"
            )


if __name__ == "__main__":
    main()

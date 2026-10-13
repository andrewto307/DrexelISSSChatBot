from functools import cache

import voyageai

from isss_bot import config
from isss_bot.chunk import estimate_tokens

BATCH_MAX_TEXTS = 128
BATCH_MAX_TOKENS = 8_000
MAX_RETRIES = 8


@cache
def _client() -> voyageai.Client:
    return voyageai.Client(max_retries=MAX_RETRIES)


def _embed(texts: list[str], input_type: str, model: str) -> tuple[list[list[float]], int]:
    result = _client().embed(texts, model=model, input_type=input_type, output_dimension=config.EMBEDDING_DIMENSIONS)
    return result.embeddings, result.total_tokens


def _batches(texts: list[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    tokens = 0
    for text in texts:
        size = estimate_tokens(text)
        if not batches or len(batches[-1]) >= BATCH_MAX_TEXTS or tokens + size > BATCH_MAX_TOKENS:
            batches.append([])
            tokens = 0
        batches[-1].append(text)
        tokens += size
    return batches


def _embed_batched(texts: list[str], input_type: str, model: str) -> tuple[list[list[float]], int]:
    vectors: list[list[float]] = []
    total_tokens = 0
    for batch in _batches(texts):
        batch_vectors, tokens = _embed(batch, input_type, model)
        vectors.extend(batch_vectors)
        total_tokens += tokens
    return vectors, total_tokens


def embed_documents(texts: list[str], model: str = config.VOYAGE_MODEL) -> tuple[list[list[float]], int]:
    return _embed_batched(texts, "document", model)


def embed_queries(texts: list[str], model: str = config.VOYAGE_MODEL) -> list[list[float]]:
    return _embed_batched(texts, "query", model)[0]


def embed_query(text: str, model: str = config.VOYAGE_MODEL) -> list[float]:
    return embed_queries([text], model)[0]

PRICES_PER_MILLION_TOKENS = {
    "claude-sonnet-5-5": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.20, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "cache_write": 1.25, "cache_read": 0.10, "output": 5.00},
    "claude-opus-5-5": {"input": 4.00, "cache_write": 5.00, "cache_read": 0.20, "output": 20.00},
}


def cost_usd(model: str, usage) -> float:
    prices = PRICES_PER_MILLION_TOKENS[model]
    return (
        usage.input_tokens * prices["input"]
        + (usage.cache_creation_input_tokens or 0) * prices["cache_write"]
        + (usage.cache_read_input_tokens or 0) * prices["cache_read"]
        + usage.output_tokens * prices["output"]
    ) / 1_000_000

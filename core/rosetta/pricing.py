"""Token → USD cost helper for Anthropic Claude models.

Per-million-token prices for Sonnet 4.5 (April 2026). Update if Anthropic
revises pricing.
"""

from __future__ import annotations

from decimal import Decimal

# Per 1M tokens
CLAUDE_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-sonnet-4-5": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-sonnet-4-6": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-opus-4-6": {
        "input": Decimal("15.00"),
        "output": Decimal("75.00"),
    },
    "claude-haiku-4-5-20251001": {
        "input": Decimal("1.00"),
        "output": Decimal("5.00"),
    },
}


def compute_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (input_cost_usd, output_cost_usd, total_cost_usd) for the call.

    Unknown models fall back to Sonnet pricing with a warning.
    """
    rates = CLAUDE_PRICING.get(model) or CLAUDE_PRICING["claude-sonnet-4-5"]
    million = Decimal("1000000")
    input_cost = (Decimal(input_tokens) / million) * rates["input"]
    output_cost = (Decimal(output_tokens) / million) * rates["output"]
    # Quantize to 6 decimals to match the Postgres Numeric(10,6) column
    q = Decimal("0.000001")
    return (
        input_cost.quantize(q),
        output_cost.quantize(q),
        (input_cost + output_cost).quantize(q),
    )

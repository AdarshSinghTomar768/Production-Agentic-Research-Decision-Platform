"""Per-call token/cost accounting records."""

from dataclasses import dataclass, field


@dataclass
class CallUsage:
    """Usage for a single LLM completion call."""

    node: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


@dataclass
class AgentUsage:
    """Aggregated usage across all calls made by one agent node invocation."""

    node: str
    calls: list[CallUsage] = field(default_factory=list)

    def add(self, u: CallUsage) -> None:
        self.calls.append(u)

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

    @property
    def total_latency_ms(self) -> int:
        return sum(c.latency_ms for c in self.calls)

    def as_dict(self) -> dict:
        return {
            "node": self.node,
            "calls": len(self.calls),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "total_latency_ms": self.total_latency_ms,
        }

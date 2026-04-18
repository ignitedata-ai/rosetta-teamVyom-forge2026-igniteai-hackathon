"""Conversation state for multi-turn chat sessions — Postgres-backed.

Wraps Akash's `Conversation` and `ConversationMessage` SQLAlchemy models so
our coordinator can use a simple in-memory `ConversationState` object during
a turn while persisting the two Rosetta-specific fields (`active_entity`,
`scenario_overrides`) back to Postgres on commit.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.models.conversation import Conversation, ConversationMessage

# --- In-memory dataclasses (per-turn working copy) ---


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str
    turn_id: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolCall:
    turn_id: int
    tool_name: str
    input: dict
    output: dict
    latency_ms: int = 0
    error: Optional[str] = None


@dataclass
class CachedAnswer:
    question_hash: str
    answer_text: str  # full marker-wrapped coordinator output (legacy field)
    evidence_refs: list[str]
    trace: Optional[dict]
    confidence: float
    audit_status: str
    cached_at: float = field(default_factory=time.time)
    # Short/detailed split and reasoning trace, populated since v1.6.
    # Optional so existing cache entries stay readable across restarts.
    short_answer: Optional[str] = None
    detailed_answer: Optional[str] = None
    reasoning_trace: Optional[dict] = None


@dataclass
class ConversationState:
    """In-memory working copy for the duration of a single turn.

    Loaded from Postgres at the start of a turn; mutated; persisted back at end.
    """

    session_id: str  # = Conversation.id (UUID string)
    workbook_id: str  # = data_source_id
    messages: list[ChatMessage] = field(default_factory=list)
    active_entity: Optional[str] = None
    scenario_overrides: dict[str, Any] = field(default_factory=dict)
    # Caches that don't persist
    answer_cache: dict[str, CachedAnswer] = field(default_factory=dict)
    tool_call_log: list[ToolCall] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # Accumulated token usage (for cost tracking across this turn)
    turn_input_tokens: int = 0
    turn_output_tokens: int = 0

    def current_turn_id(self) -> int:
        return len([m for m in self.messages if m.role == "user"])

    def append_user(self, content: str) -> int:
        turn_id = self.current_turn_id() + 1
        self.messages.append(ChatMessage(role="user", content=content, turn_id=turn_id))
        self.updated_at = time.time()
        return turn_id

    def append_assistant(self, content: str) -> None:
        turn_id = self.current_turn_id()
        self.messages.append(ChatMessage(role="assistant", content=content, turn_id=turn_id))
        self.updated_at = time.time()

    def log_tool_call(
        self, tool_name: str, input_args: dict, output: dict, latency_ms: int = 0, error: Optional[str] = None
    ) -> None:
        self.tool_call_log.append(
            ToolCall(
                turn_id=self.current_turn_id(),
                tool_name=tool_name,
                input=input_args,
                output=output,
                latency_ms=latency_ms,
                error=error,
            )
        )

    def set_scenario(self, overrides: dict[str, Any]) -> None:
        self.scenario_overrides = dict(overrides)
        self.updated_at = time.time()

    def clear_scenario(self, ref: Optional[str] = None) -> None:
        if ref is None:
            self.scenario_overrides = {}
        else:
            self.scenario_overrides.pop(ref, None)
        self.updated_at = time.time()


# --- In-process cache of answer caches, keyed by conversation_id ---
# Not persisted. Purpose: avoid recomputing identical (question, scenario)
# within the same runtime. Cleared on server restart; that's fine.
_ANSWER_CACHES: dict[str, dict[str, CachedAnswer]] = {}


def _get_answer_cache(conversation_id: str) -> dict[str, CachedAnswer]:
    c = _ANSWER_CACHES.get(conversation_id)
    if c is None:
        c = {}
        _ANSWER_CACHES[conversation_id] = c
    return c


# --- Postgres <-> in-memory bridge ---


async def load_state(
    session: AsyncSession,
    conversation: Conversation,
    *,
    include_history: bool = True,
) -> ConversationState:
    """Hydrate a ConversationState from an already-loaded Conversation row.

    The caller must have fetched `conversation` (typically via
    ConversationService.get_conversation()). Messages come from the
    SQLAlchemy relationship and should be eager-loaded by the caller
    if `include_history=True`.
    """
    state = ConversationState(
        session_id=conversation.id,
        workbook_id=conversation.data_source_id,
        active_entity=conversation.active_entity,
        scenario_overrides=dict(conversation.scenario_overrides or {}),
        answer_cache=_get_answer_cache(conversation.id),
        created_at=conversation.created_at.timestamp() if conversation.created_at else time.time(),
        updated_at=conversation.updated_at.timestamp() if conversation.updated_at else time.time(),
    )

    if include_history:
        msgs: list[ConversationMessage] = list(conversation.messages or [])
        state.messages = [
            ChatMessage(
                role=m.role,
                content=m.content,
                turn_id=idx + 1,
                timestamp=m.created_at.timestamp() if m.created_at else time.time(),
            )
            for idx, m in enumerate(msgs)
        ]
    return state


async def persist_state(
    session: AsyncSession,
    state: ConversationState,
    conversation: Conversation,
) -> None:
    """Persist Rosetta-specific columns back to the Conversation row.

    Does NOT save messages — those are persisted separately by
    ConversationService.add_message() as part of Akash's existing flow.
    """
    conversation.active_entity = state.active_entity
    conversation.scenario_overrides = dict(state.scenario_overrides)


# --- Helpers ---


def question_hash(question: str, scenario_overrides: dict[str, Any]) -> str:
    """Stable hash for cache keys. Case-insensitive, whitespace-normalized."""
    normalized = re.sub(r"\s+", " ", question.lower().strip())
    sig = f"{normalized}::{json.dumps(scenario_overrides, sort_keys=True, default=str)}"
    return hashlib.sha256(sig.encode()).hexdigest()[:16]


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


# --- Entity extraction (simple heuristics) ---


CELL_REF_PATTERN = re.compile(r"([A-Za-z_][\w &\-\.]*?)!(\$?[A-Z]{1,3}\$?[0-9]+)")


def extract_entity_from_text(text: str) -> Optional[str]:
    """Pull the first canonical cell ref from a string, if any."""
    m = CELL_REF_PATTERN.search(text)
    if m:
        sheet = m.group(1).strip()
        coord = m.group(2).replace("$", "")
        return f"{sheet}!{coord}"
    return None

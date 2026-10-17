"""Radio eligibility and message checks (spec §5.5)."""

from maze_lab.agent_contracts import RadioRejection, utf8_len


def next_eligible_tick(last_sent_tick: int | None, cooldown_ticks: int) -> int:
    return 1 if last_sent_tick is None else last_sent_tick + cooldown_ticks + 1


def check_radio(
    text: str, tick: int, last_sent_tick: int | None, cooldown_ticks: int, max_bytes: int
) -> RadioRejection | None:
    """None if the transmission is accepted at `tick`, else the rejection code."""
    if tick < next_eligible_tick(last_sent_tick, cooldown_ticks):
        return "radio_cooldown"
    if not text.strip():
        return "empty_radio"
    try:
        size = utf8_len(text)
    except UnicodeEncodeError:
        return "invalid_unicode"
    if size > max_bytes:
        return "radio_budget_exceeded"
    return None

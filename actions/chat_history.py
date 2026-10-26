"""
chat_history action for SAM — Retrieves previous conversation turns.
"""
from memory.chat_history import load_messages, get_recent_summary, clear_history
from core.llm_client import get_salutation


def chat_history(params: dict) -> str:
    action = params.get("action", "recent").lower()
    address = get_salutation()

    if action == "clear":
        clear_history()
        return f"All previous chat logs have been cleared, {address}."

    if action == "search":
        query = params.get("query", "")
        matches = load_messages(search=query, limit=10)
        if not matches:
            return f"No previous conversations matching '{query}' were found, {address}."
        lines = [f"Found {len(matches)} matching transmissions for '{query}':"]
        for m in matches:
            lines.append(f"[{m.get('timestamp', '')}] {m.get('role', '')}: {m.get('content', '')[:160]}")
        return "\n".join(lines)

    # Default: recent conversations summary
    limit = int(params.get("limit", 4))
    summary = get_recent_summary(max_turns=limit)
    return f"Here are your recent conversations, {address}:\n\n{summary}"

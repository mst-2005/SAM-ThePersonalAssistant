def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    city = parameters.get("city")
    when = parameters.get("time", "today")

    if not city or not isinstance(city, str) or not city.strip():
        from core.llm_client import get_salutation
        address = get_salutation()
        msg = f"{address}, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = city.strip()
    when = (when or "today").strip()

    try:
        from actions.web_search import _search
        report = _search(f"current weather in {city} {when}; temperature, conditions, and forecast")
    except Exception as e:
        msg = f"I couldn't retrieve live weather for {city}: {e}"
        _log(msg, player)
        return msg

    msg = f"Live weather for {city} ({when}):\n{report}"
    _log(msg, player)

    if session_memory:
        try:
            session_memory.set_last_search(query=f"weather in {city} {when}", response=msg)
        except Exception:
            pass

    return msg


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"SAM: {message}")
        except Exception:
            pass


weather_report = weather_action

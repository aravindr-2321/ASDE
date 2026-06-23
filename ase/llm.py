"""Unified LLM client — switch between Anthropic or OpenRouter via .env."""
import os


def complete(system: str, user: str, max_tokens: int = 8192) -> str:
    """Call the configured LLM provider and return plain text response."""
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if provider == "openrouter":
        return _openrouter(system, user, max_tokens)
    return _anthropic(system, user, max_tokens)


def _anthropic(system: str, user: str, max_tokens: int) -> str:
    import anthropic
    model = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    kwargs = dict(model=model, max_tokens=max_tokens,
                  messages=[{"role": "user", "content": user}])
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return resp.content[0].text


def _openrouter(system: str, user: str, max_tokens: int) -> str:
    from openai import OpenAI
    model = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    resp = client.chat.completions.create(
        model=model, max_tokens=max_tokens, messages=messages,
    )
    return resp.choices[0].message.content

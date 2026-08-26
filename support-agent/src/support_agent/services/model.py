"""Provider model construction for support-agent."""

from langchain_openai import ChatOpenAI

from support_agent.config import AgentSettings


def create_chat_model(settings: AgentSettings) -> ChatOpenAI:
    """Build a model from injected settings without reading the environment here."""

    model_kwargs: dict[str, object] = {
        "model": settings.model,
        "api_key": settings.api_key.get_secret_value(),
        "timeout": settings.timeout_seconds,
        "max_retries": 0,
    }
    if settings.resolved_base_url is not None:
        model_kwargs["base_url"] = settings.resolved_base_url
    if settings.model.startswith("deepseek-"):
        model_kwargs["extra_body"] = {
            "thinking": {"type": settings.deepseek_thinking_mode},
        }

    return ChatOpenAI(**model_kwargs)

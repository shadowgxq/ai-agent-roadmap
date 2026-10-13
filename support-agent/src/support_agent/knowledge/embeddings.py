"""Provider calls happen only through an explicitly constructed adapter."""

from langchain_openai import OpenAIEmbeddings


def create_embedder(*, model: str, api_key: str, base_url: str | None = None,
                    dimensions: int | None = None) -> OpenAIEmbeddings:
    options = dict(model=model, api_key=api_key, base_url=base_url,
                   request_timeout=30, max_retries=1)
    if dimensions is not None:
        options["dimensions"] = dimensions
    return OpenAIEmbeddings(**options)

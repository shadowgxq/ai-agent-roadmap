"""通过 OpenAI-compatible embeddings API 批量生成向量。"""

from openai import AsyncOpenAI


class OpenAIEmbedder:
    """隐藏 embedding 请求的批处理和响应顺序校验。"""

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        batch_size: int = 64,
    ) -> None:
        if not model.strip():
            raise ValueError("embedding model 不能为空")
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0")
        self.client = client
        self.model = model
        self.batch_size = batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """按批次生成向量，并恢复为与输入一致的顺序。"""
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("不能为无内容文本生成 embedding")

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = await self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise RuntimeError("embedding 响应数量与请求数量不一致")
            vectors.extend([list(item.embedding) for item in ordered])

        dimensions = {len(vector) for vector in vectors}
        if 0 in dimensions or len(dimensions) != 1:
            raise RuntimeError("embedding 响应包含空向量或维度不一致")
        return vectors

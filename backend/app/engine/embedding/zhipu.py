"""智谱 embedding-3 线上实现。¥0.5/M tokens，OpenAI 兼容接口。"""
from typing import Sequence, Dict, Any, List


class ZhipuProvider:
    name = "zhipu"
    model = "embedding-3"
    dim = 2048

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError("阶段 0 占位；B2 阶段实装 HTTP 调用 + 鉴权")

    def health_check(self) -> Dict[str, Any]:
        return {"ok": False, "detail": "stage-0 stub"}

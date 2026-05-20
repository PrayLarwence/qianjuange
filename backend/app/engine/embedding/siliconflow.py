"""硅基流动 BGE 系列云端实现。免费额度大，可作为线上备选。"""
from typing import Sequence, Dict, Any, List


class SiliconFlowProvider:
    name = "siliconflow"
    model = "BAAI/bge-large-zh-v1.5"
    dim = 1024

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError("阶段 0 占位；B2 阶段实装 HTTP 调用 + 鉴权")

    def health_check(self) -> Dict[str, Any]:
        return {"ok": False, "detail": "stage-0 stub"}

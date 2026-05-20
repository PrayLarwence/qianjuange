"""本地 bge-small-zh-v1.5 实现。阶段 0 只占位，B2 阶段实装。

实装时优先用 fastembed（嵌入式 ONNX runtime，~100MB 模型，CPU 友好），
避免抢占 astrbot 的 GPU 显存。
"""
from typing import Sequence, Dict, Any, List


class LocalBGEProvider:
    name = "local_bge"
    model = "BAAI/bge-small-zh-v1.5"
    dim = 512

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError("阶段 0 占位；B2 阶段实装 fastembed 调用")

    def health_check(self) -> Dict[str, Any]:
        return {"ok": False, "detail": "stage-0 stub"}

"""开发者本地真实小说回归脚本.

用法:
    python scripts/dev_ingest_real_novel.py path/to/book.epub --name "哈利波特" [--limit 3]

它做什么:
    1. 从 epub 抽出全部章节, 拼成纯文本
    2. 调 backend 的 ingest_manuscript() 直接跑 V1 切章 + cast 抽取
    3. 打印章节数 / cast / locations / warnings, 以及总耗时
    4. 不写库, 也不调 LLM (manuscript_ingest V1 是纯本地 NLP 流程, 见 manuscript/ingest.py)

意图: 在打包前用一本真实长篇验证 V1 同步流水线在大文件上是否会卡死/超时, 以及切章效果.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import zipfile
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.manuscript_ingest import ingest_manuscript, render_outline_text  # noqa: E402


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_BLANK = re.compile(r"\n\s*\n+")


def _strip_html(raw: str) -> str:
    txt = _TAG.sub("", raw)
    txt = unescape(txt)
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    txt = _WS.sub(" ", txt)
    txt = _BLANK.sub("\n\n", txt)
    return txt.strip()


def epub_to_text(path: Path, *, include_appendix: bool = False) -> str:
    """按文件名字典序拼接所有章节, 跳过封面/版权/目录这种小文件."""
    parts: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = sorted(
            n for n in z.namelist()
            if n.lower().endswith((".html", ".xhtml", ".htm"))
        )
        for n in names:
            base = n.rsplit("/", 1)[-1].lower()
            if not include_appendix and base.startswith("appdx"):
                continue
            if "cover" in base or "title" in base or "copyright" in base or "toc" in base:
                continue
            info = z.getinfo(n)
            if info.file_size < 200:
                continue
            raw = z.read(n).decode("utf-8", errors="replace")
            parts.append(_strip_html(raw))
    return "\n\n".join(p for p in parts if p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path, help="epub 文件路径")
    ap.add_argument("--name", default="测试世界", help="ingest 时世界名")
    ap.add_argument("--limit", type=int, default=0,
                    help="只取前 N 个字符 (0 = 全文). 用来定位 V1 同步流水线的卡死阈值")
    ap.add_argument("--include-appendix", action="store_true")
    ap.add_argument("--dump-text", type=Path, default=None,
                    help="把抽出的纯文本另存一份, 方便复测")
    args = ap.parse_args(argv)

    if not args.source.exists():
        print(f"file not found: {args.source}", file=sys.stderr)
        return 2

    t0 = time.monotonic()
    text = epub_to_text(args.source, include_appendix=args.include_appendix)
    t_extract = time.monotonic() - t0

    if args.limit and args.limit > 0:
        text = text[: args.limit]

    print(f"[extract] {len(text):,} chars in {t_extract:.2f}s "
          f"(source={args.source.name}, appendix={args.include_appendix})")

    if args.dump_text:
        args.dump_text.write_text(text, encoding="utf-8")
        print(f"[dump] wrote plain text to {args.dump_text}")

    t1 = time.monotonic()
    result = ingest_manuscript(world_name=args.name, text=text)
    t_ingest = time.monotonic() - t1

    print(f"[ingest] {t_ingest:.2f}s")
    print(f"  chunks   : {len(result.chunks)}")
    print(f"  outline  : {len(result.outline)} entries")
    print(f"  cast     : {len(result.cast)}")
    print(f"  locations: {len(result.locations)}")
    print(f"  factions : {len(result.factions)}")
    if result.warnings:
        print("  warnings :")
        for w in result.warnings:
            print(f"    - {w}")
    if result.cast[:5]:
        print("  top cast :", ", ".join(c.get("name", "?") for c in result.cast[:5]))
    if result.outline[:3]:
        print("  outline preview:")
        print("    " + render_outline_text(result.outline[:3]).replace("\n", "\n    "))
    return 0


if __name__ == "__main__":
    sys.exit(main())

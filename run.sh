#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "首次运行：创建虚拟环境..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r backend/requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 .env，请填入你的 API Key 后重新运行。"
  exit 0
fi
echo "启动 http://localhost:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend --reload

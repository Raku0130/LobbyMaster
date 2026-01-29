FROM python:3.13-slim

WORKDIR /app

# 依存関係をインストール
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY lobby_master.py ./

# Bot起動
CMD ["python", "lobby_master.py"]

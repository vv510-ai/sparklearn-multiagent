FROM python:3.11-slim
WORKDIR /srv
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV FASTEMBED_CACHE_DIR=/opt/fastembed_cache
ENV FASTEMBED_MODEL_PATH=/opt/bge-small-zh-int8
ENV FASTEMBED_THREADS=1
ENV FASTEMBED_BATCH_SIZE=2
# 生产服务器位于中国内地，构建期经 hf-mirror.com 下载模型
ENV HF_ENDPOINT=https://hf-mirror.com
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
COPY scripts/prepare_fastembed.py /tmp/prepare_fastembed.py
RUN pip install --no-cache-dir "onnx>=1.16,<2" \
    && python /tmp/prepare_fastembed.py \
    && pip uninstall -y onnx \
    && rm -f /tmp/prepare_fastembed.py
COPY app ./app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

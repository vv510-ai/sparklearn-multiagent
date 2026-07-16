FROM python:3.11-slim
WORKDIR /srv
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV FASTEMBED_CACHE_DIR=/opt/fastembed_cache
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding(model_name='BAAI/bge-small-zh-v1.5', cache_dir='/opt/fastembed_cache').embed(['SparkLearn']))"
COPY app ./app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

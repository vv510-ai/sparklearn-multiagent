"""Dedicated generation worker: python -m app.job_worker."""
import asyncio
from .models.db import init_db
from .config import GEN_DIR
from .services.generation_jobs import worker_loop

def main():
    init_db()
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    from .rag.ingest import ingest_corpus
    ingest_corpus()
    asyncio.run(worker_loop())

if __name__ == "__main__":
    main()

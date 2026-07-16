"""Download and INT8-quantize the Chinese BGE model during image build."""
from __future__ import annotations

import gc
import os
import shutil
from pathlib import Path

import onnx
from fastembed import TextEmbedding
from onnxruntime.quantization import QuantType, quantize_dynamic


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
CACHE_DIR = Path(os.getenv("FASTEMBED_CACHE_DIR", "/opt/fastembed_cache"))
MODEL_DIR = Path(os.getenv("FASTEMBED_MODEL_PATH", "/opt/bge-small-zh-int8"))


def main() -> None:
    model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(CACHE_DIR), threads=1)
    probe = list(model.embed(["SparkLearn 中文语义检索"], batch_size=1))
    if not probe or len(probe[0]) != 512:
        raise RuntimeError("unexpected BGE embedding output")
    del model, probe
    gc.collect()

    source = next(CACHE_DIR.rglob("model_optimized.onnx"))
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for item in source.parent.iterdir():
        if item.is_file() and item.suffix != ".onnx":
            shutil.copy2(item, MODEL_DIR / item.name)
    quantized = MODEL_DIR / "model_optimized.onnx"
    original_size = source.stat().st_size
    quantize_dynamic(
        str(source),
        str(quantized),
        weight_type=QuantType.QInt8,
        extra_options={"DefaultTensorType": onnx.TensorProto.FLOAT},
    )

    # A bad quantized artifact must fail the image build instead of crashing production.
    verified = TextEmbedding(
        model_name=MODEL_NAME,
        specific_model_path=str(MODEL_DIR),
        threads=1,
        enable_cpu_mem_arena=False,
    )
    output = list(verified.embed(["数据结构"], batch_size=1))
    if not output or len(output[0]) != 512:
        raise RuntimeError("INT8 BGE verification failed")
    print(
        f"Prepared {MODEL_NAME}: {original_size / 1024 / 1024:.1f}MB -> "
        f"{quantized.stat().st_size / 1024 / 1024:.1f}MB"
    )
    del verified, output
    gc.collect()
    shutil.rmtree(CACHE_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()

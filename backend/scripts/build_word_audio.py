"""Build the complete corrected vocabulary as same-origin MP3 files.

Uses piper-tts==1.4.2, lameenc==1.8.4 and miniaudio==1.71 in an isolated build environment.
Only the generated audio and manifest ship; no synthesis runtime runs online.
Published version directories must never be regenerated in place.
"""
from __future__ import annotations

import argparse
from array import array
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend/app/data"
VOICES = {
    "en-US": {"name": "LJSpeech medium", "model_sha256": "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22", "config_sha256": "01699b1f64aec09d359efd73aed94453d83a3fe6031de1f570bbb1df46d995d2"},
    "en-GB": {"name": "Cori medium", "model_sha256": "1899f98e5fb8310154f3c2973f4b8a929ba7245e722b3d3a85680b833d95f10d", "config_sha256": "4e4e862c06be95e268cb2edeb18eed39b4fc51c515d808ed3c51404f20e96fea"},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(path: Path) -> str:
    # Git may check JSON out with CRLF on Windows and LF on Linux.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def vocabulary():
    corpus = json.loads((DATA / "cet6_vocabulary_v1.json").read_text(encoding="utf-8"))
    fixes = json.loads((DATA / "cet6_vocabulary_corrections_v1.json").read_text(encoding="utf-8"))
    return sorted([
        {"id": e["id"], "word": fixes["spellings"].get(e["word"], e["word"])}
        for e in corpus["entries"] if e["word"] not in fixes["aliases"]
    ], key=lambda e: e["id"])


def build_shard(accent, model, rows, output):
    import lameenc
    import miniaudio
    import onnxruntime
    import piper
    from piper.config import PiperConfig, SynthesisConfig

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    voice = None
    folder = output / accent
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for index, row in enumerate(rows):
        filename = row["id"] + ".mp3"
        target = folder / filename
        if target.exists():
            decoded = miniaudio.mp3_read_s16(target.read_bytes())
            peak = max((abs(s) for s in decoded.samples), default=0)
            duration = decoded.num_frames / decoded.sample_rate
            if decoded.nchannels != 1 or decoded.sample_rate != 22050 or not .15 <= duration <= 15 or peak < 100:
                raise RuntimeError(f"Invalid existing audio: {target}")
            results.append({**row, "file": f"{accent}/{filename}", "sha256": digest(target), "duration": round(duration, 4), "bytes": target.stat().st_size, "peak": peak})
            continue
        if voice is None:
            voice = piper.PiperVoice(
                session=onnxruntime.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"]),
                config=PiperConfig.from_dict(json.loads(Path(str(model) + ".json").read_text(encoding="utf-8"))),
                # The native Windows phonemizer needs an ASCII relative path.
                espeak_data_dir=Path(os.path.relpath(Path(piper.__file__).parent / "espeak-ng-data")),
            )
        # Terminal punctuation gives isolated words a natural phrase boundary.
        chunks = list(voice.synthesize(row["word"] + ".", SynthesisConfig(length_scale=1.05)))
        pcm = b"".join(c.audio_int16_bytes for c in chunks)
        samples = array("h", pcm)
        peak = max((abs(s) for s in samples), default=0)
        duration = len(samples) / voice.config.sample_rate
        if not .15 <= duration <= 15 or peak < 100:
            raise RuntimeError(f"Invalid or silent synthesis: {accent} {row}")
        encoder = lameenc.Encoder()
        encoder.set_in_sample_rate(voice.config.sample_rate)
        encoder.set_out_sample_rate(voice.config.sample_rate)
        encoder.set_channels(1)
        encoder.set_bit_rate(48)
        encoder.set_quality(2)
        encoded = bytes(encoder.encode(pcm)) + bytes(encoder.flush())
        decoded = miniaudio.mp3_read_s16(encoded)
        peak = max((abs(s) for s in decoded.samples), default=0)
        duration = decoded.num_frames / decoded.sample_rate
        if not .15 <= duration <= 15 or peak < 100:
            raise RuntimeError(f"Invalid encoded audio: {accent} {row}")
        target.write_bytes(encoded)
        if target.stat().st_size < 500:
            raise RuntimeError(f"Empty MP3: {target}")
        results.append({**row, "file": f"{accent}/{filename}", "sha256": digest(target), "duration": round(duration, 4), "bytes": target.stat().st_size, "peak": peak})
        if (index + 1) % 250 == 0:
            print(f"{accent}: {index + 1}/{len(rows)}", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--us-model", type=Path, required=True)
    parser.add_argument("--gb-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "frontend/public/word-audio/v1")
    parser.add_argument("--workers", type=int, default=1, choices=[1, 2])
    parser.add_argument("--limit", type=int, help="Smoke build only; use a separate output directory")
    parser.add_argument("--resume", action="store_true", help="Decode and reuse audio from an interrupted, unpublished build")
    args = parser.parse_args()
    if importlib.metadata.version("piper-tts") != "1.4.2":
        parser.error("Use the existing piper-tts==1.4.2 build environment")
    if importlib.metadata.version("lameenc") != "1.8.4":
        parser.error("Use lameenc==1.8.4 for MP3 encoding")
    if importlib.metadata.version("miniaudio") != "1.71":
        parser.error("Use miniaudio==1.71 to validate decoded MP3 samples")
    if (args.output / "manifest.json").exists() or (args.output.exists() and not args.resume):
        parser.error("Use a new empty version directory; published audio is immutable")
    models = {"en-US": args.us_model, "en-GB": args.gb_model}
    for accent, model in models.items():
        for file, expected in [(model, VOICES[accent]["model_sha256"]), (Path(str(model) + ".json"), VOICES[accent]["config_sha256"])]:
            if digest(file) != expected:
                parser.error("Unreviewed model/config: " + str(file))
    rows = vocabulary()
    if args.limit:
        rows = rows[:args.limit]
    started = time.monotonic()
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(build_shard, accent, model, rows, args.output) for accent, model in models.items()]
        for job in as_completed(jobs):
            records.extend(job.result())
    manifest = {
        "version": args.output.name, "word_count": len(rows), "file_count": len(records),
        "engine": "piper-tts 1.4.2 + lameenc 1.8.4 (build only)", "decoder_validation": "miniaudio 1.71, every MP3 decoded and checked for non-silent samples", "encoding": "MP3 48 kbps, 22050 Hz, mono",
        "voices": VOICES, "author": "Bryce Beattie", "model_license": "public domain (author statement)",
        "source_url": "https://brycebeattie.com/files/tts/",
        "notice": "本站离线合成音频；不是词典真人录音，多音词和读音仍需结合词典核对。",
        "source_hash_format": "UTF-8 with LF newlines",
        "corpus_sha256": source_digest(DATA / "cet6_vocabulary_v1.json"),
        "corrections_sha256": source_digest(DATA / "cet6_vocabulary_corrections_v1.json"),
        "files": sorted(records, key=lambda r: r["file"]),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"words": len(rows), "files": len(records), "bytes": sum(r["bytes"] for r in records), "seconds": round(time.monotonic() - started, 2)}), flush=True)


if __name__ == "__main__":
    main()

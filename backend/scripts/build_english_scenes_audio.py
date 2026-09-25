"""Build one unpublished English release using pinned Piper/LJSpeech weights.

Build-only environment: piper-tts==1.4.2. No model or runtime enters the server image.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import piper
from pathlib import Path
import wave
from piper import PiperVoice
from english_scenes_content import make_bundle

MODEL_SHA = "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22"
CONFIG_SHA = "01699b1f64aec09d359efd73aed94453d83a3fe6031de1f570bbb1df46d995d2"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument("--model",type=Path,required=True)
    args=parser.parse_args()
    if importlib.metadata.version("piper-tts") != "1.4.2":
        raise SystemExit("Use the reviewed piper-tts==1.4.2 build environment")
    for file,expected in [(args.model,MODEL_SHA),(Path(str(args.model)+".json"),CONFIG_SHA)]:
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise SystemExit("Unreviewed model/configuration hash: " + file.name)
    bundle=make_bundle()
    destination=ROOT/"app/data/course_library"/(bundle["release_id"]+".json")
    if destination.exists():
        raise SystemExit("Immutable release exists; create a new version")
    media=ROOT/"app/data/course_media"/bundle["release_id"]
    clips=ROOT/".tmp/piper-scenes"; clips.mkdir(parents=True,exist_ok=True)
    media.mkdir(parents=True,exist_ok=True)
    # Relative ASCII path avoids the Windows native phonemizer misreading a Unicode workspace path.
    espeak_data = os.path.relpath(Path(piper.__file__).parent / "espeak-ng-data", Path.cwd())
    voice=PiperVoice.load(str(args.model), espeak_data_dir=espeak_data)
    for lesson in bundle["lessons"]:
        frames=[]; cues=[]; offset=0
        for line in lesson["scene"]["lines"]:
            clip=clips/(line["id"]+".wav")
            with wave.open(str(clip),"wb") as wav:
                voice.synthesize_wav(line["text"],wav)
            with wave.open(str(clip),"rb") as wav:
                assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth()) == (22050,1,2)
                raw=wav.readframes(wav.getnframes())
            start=offset/22050; frames.append(raw); offset+=len(raw)//2
            cues.append(dict(line_id=line["id"],start=start,end=offset/22050))
            gap=6615;frames.append(b"\0"*(gap*2));offset+=gap
        path=media/(lesson["id"]+".wav")
        with wave.open(str(path),"wb") as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(b"".join(frames))
        lesson["scene"]["audio"]=dict(file=f"{bundle['release_id']}/{path.name}",sha256=hashlib.sha256(path.read_bytes()).hexdigest(),transcript_sha256=hashlib.sha256("\n".join(line["text"] for line in lesson["scene"]["lines"]).encode()).hexdigest(),duration=offset/22050,cues=cues,voices=["Piper LJSpeech medium"],notice="单人美式合成朗读；用角色名区分对话，不是真人发音示范。")
        print(lesson["id"],round(offset/22050,2),flush=True)
    bundle["rights"]["audio"]={"engine":"piper-tts 1.4.2 (GPL-3.0)","model":"Bryce Beattie LJSpeech medium", "model_sha256":MODEL_SHA,"config_sha256":CONFIG_SHA,"model_license":"public domain (model author's statement)","license_url":"https://brycebeattie.com/files/tts/","dataset_license_url":"https://keithito.com/LJ-Speech-Dataset/", "distribution":"Only synthesized original-content WAV is shipped; build runtime and weights are not distributed with the website."}
    destination.write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__ == "__main__": main()

"""Transcribe supplied source/clone audio for edit alignment. No voice generation."""
import argparse
import json
import subprocess
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--model',default='small',help='A local model folder, or faster-whisper model name; first use may download weights')
    ap.add_argument('--lang',default='vi');ap.add_argument('--device',default='cpu')
    a=ap.parse_args()
    from faster_whisper import WhisperModel
    import numpy as np
    model=WhisperModel(a.model,device=a.device,compute_type='int8')
    # Decode with the installed ffmpeg rather than PyAV: some environments have
    # faster-whisper and PyAV versions with incompatible av.open keyword support.
    decoded=subprocess.run(['ffmpeg','-v','error','-i',a.input,'-vn','-ar','16000','-ac','1','-f','f32le','pipe:1'],capture_output=True)
    if decoded.returncode:
        raise ValueError('ffmpeg could not decode audio: '+decoded.stderr.decode('utf-8',errors='replace')[:500])
    audio=np.frombuffer(decoded.stdout,dtype=np.float32).copy()
    if not audio.size:raise ValueError('Source contains no decodable audio')
    segments,info=model.transcribe(audio,language=a.lang,word_timestamps=True,vad_filter=True)
    rows=[]
    for seg in segments:
        rows.append({'start':seg.start,'end':seg.end,'text':seg.text,
                     'words':[{'start':w.start,'end':w.end,'word':w.word,'probability':w.probability} for w in seg.words or []]})
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'source':str(Path(a.input).resolve()),'language':info.language,'source_speed':1.0,'segments':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'segments':len(rows),'out':str(out)}))


if __name__=='__main__':main()

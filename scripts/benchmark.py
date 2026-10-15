"""Run after downloading models; prints measured combined process RSS, not a RAM guarantee."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ring_face'))
import psutil
from ringface.settings import Settings
from ringface.engine import Engine
from ringface.images import decode


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--models',type=Path,required=True)
    parser.add_argument('--image',type=Path,required=True)
    args=parser.parse_args()
    engine=Engine(Settings(models=args.models,opencv_threads=1,processing_timeout=30))
    done=threading.Event();peak=[0]
    process=psutil.Process()
    def sample():
        while not done.wait(.02):
            try:
                rss=process.memory_info().rss+sum(c.memory_info().rss for c in process.children(recursive=True))
                peak[0]=max(peak[0],rss)
            except psutil.Error:
                pass
    thread=threading.Thread(target=sample);thread.start()
    try:
        image=decode(args.image.read_bytes())
        runs=[]
        for _ in range(3):
            result=engine.analyze(image);runs.append(result['duration_ms'])
        print(json.dumps({'faces':len(result['features']),'durations_ms':runs,'engine_peak_mib':engine.peak_rss_kib/1024,'combined_sampled_peak_mib':peak[0]/1024**2,'opencv_threads':1},indent=2))
    finally:
        done.set();thread.join();engine.close()


if __name__=='__main__':main()

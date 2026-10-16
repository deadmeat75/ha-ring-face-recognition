"""Create a public-fixture MP4 with an empty first frame and a later face."""
import argparse
import cv2
import numpy as np


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--face',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();cv2.setNumThreads(1)
    face=cv2.imread(args.face)
    if face is None:raise RuntimeError('Cannot read public test face')
    face=cv2.resize(face,(512,512));blank=np.full_like(face,255)
    writer=cv2.VideoWriter(args.output,cv2.VideoWriter_fourcc(*'mp4v'),5,(512,512))
    if not writer.isOpened():raise RuntimeError('MP4 encoder unavailable')
    try:
        for i in range(20):writer.write(blank if i<6 else face)
    finally:writer.release()


if __name__=='__main__':main()

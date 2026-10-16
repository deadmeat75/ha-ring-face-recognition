"""Bounded, local-only event recordings; never accepts URLs or credentials."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile
import time
from .images import CaptureError, ID

MAX_VIDEO_BYTES = 64 * 1024 * 1024


@contextmanager
def private_recording(directory, event_id, attempt, captured_at, data, timeout=10, stop=None):
    if not ID.fullmatch(event_id) or type(attempt) is not int or not 1 <= attempt <= 3:
        raise CaptureError("invalid_identifier", "Invalid recording identifier")
    directory, data = Path(directory), Path(data)
    deadline = time.monotonic() + timeout
    temporary = None
    metadata = None
    while True:
        try:
            if directory.parent.is_symlink():
                raise CaptureError("unsafe_file", "Recording parent is a symlink")
            dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fd = os.open(f"{event_id}_{attempt}.mp4", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=dfd)
            finally:
                os.close(dfd)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise CaptureError("unsafe_file", "Recording must be a regular file")
                if before.st_size == 0:
                    raise CaptureError("empty_recording", "Recording file is empty")
                if before.st_size > MAX_VIDEO_BYTES:
                    raise CaptureError("recording_too_large", "Recording exceeds 64 MiB")
                if not captured_at-5 <= before.st_mtime <= time.time()+5 or time.time()-before.st_mtime > 120:
                    raise CaptureError("stale_recording", "Recording file timestamp is outside the download window")
                data.mkdir(parents=True,exist_ok=True,mode=0o700)
                if data.is_symlink():raise CaptureError("unsafe_file","Private video work directory must not be a symlink")
                data.chmod(0o700)
                with tempfile.NamedTemporaryFile(dir=data,suffix='.mp4',delete=False) as out:
                    temporary = Path(out.name)
                    os.chmod(temporary,0o600)
                    size=0
                    while chunk := os.read(fd,65536):
                        size+=len(chunk)
                        if size > MAX_VIDEO_BYTES:
                            raise CaptureError("recording_too_large", "Recording grew beyond 64 MiB")
                        if time.monotonic()>deadline:
                            raise CaptureError("recording_copy_timeout", "Recording copy exceeded capture timeout")
                        out.write(chunk)
                after=os.fstat(fd)
                if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                    raise CaptureError("recording_writing", "Recording changed during copy")
                with temporary.open('rb') as f:header=f.read(16)
                if len(header)<12 or header[4:8]!=b'ftyp':
                    raise CaptureError("invalid_recording", "Expected an MP4 recording, not an image or playlist")
                metadata={"format":"MP4","bytes":size,"file_mtime":before.st_mtime}
            finally:
                os.close(fd)
            break
        except (OSError,CaptureError) as error:
            if temporary:
                temporary.unlink(missing_ok=True);temporary=None
            if isinstance(error,PermissionError):
                raise CaptureError("permission_denied","Cannot read the shared recording") from error
            if isinstance(error,OSError) and not isinstance(error,FileNotFoundError):
                raise CaptureError("unsafe_or_unreadable_recording","Cannot safely open recording") from error
            if isinstance(error,CaptureError) and error.code not in {'empty_recording','recording_writing'}:
                raise
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise CaptureError("missing_or_incomplete_recording",f"No complete recording after {timeout}s") from error
            if stop is not None:
                if stop.wait(min(.25,remaining)):
                    raise CaptureError("cancelled","App stopped while waiting for recording")
            else:time.sleep(min(.25,remaining))
    try:
        yield temporary,metadata
    finally:
        temporary.unlink(missing_ok=True)


def video_frames(path):
    """At most five seeks in a private MP4 using the wheel's bundled FFmpeg."""
    import cv2
    import math
    # Prevent network-backed demuxer inputs, external playlists and hardware paths.
    os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS']='protocol_whitelist;file,pipe|enable_drefs;0|use_absolute_path;0'
    cap=cv2.VideoCapture(str(path),cv2.CAP_FFMPEG,[cv2.CAP_PROP_N_THREADS,1,
                         cv2.CAP_PROP_HW_ACCELERATION,cv2.VIDEO_ACCELERATION_NONE])
    try:
        if not cap.isOpened():raise CaptureError('invalid_recording','Cannot open MP4 recording')
        fps=cap.get(cv2.CAP_PROP_FPS);count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width=cap.get(cv2.CAP_PROP_FRAME_WIDTH);height=cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not all(math.isfinite(x) for x in (fps,count,width,height)) or not 0<fps<=120 or count<=0:
            raise CaptureError('invalid_recording','Missing or invalid video timing')
        duration=count/fps
        if not 0<duration<=180 or not 0<width*height<=12_000_000:
            raise CaptureError('recording_limits','Recording exceeds 180 seconds or 12 MP per frame')
        offsets=sorted({round(min(t,max(0,duration-1/fps)),3) for t in [1,3,6,duration*.5,duration*.8]})
        decoded=0
        for offset in offsets:
            cap.set(cv2.CAP_PROP_POS_MSEC,offset*1000)
            ok,image=cap.read()
            if not ok:continue
            decoded+=1
            if max(image.shape[:2])>1280:
                ratio=1280/max(image.shape[:2])
                image=cv2.resize(image,(int(image.shape[1]*ratio),int(image.shape[0]*ratio)))
            yield offset,image
        if not decoded:raise CaptureError('invalid_recording','No decodable video frames')
    finally:cap.release()


def select_recording_sample(samples,people,threshold,margin):
    """Never pick one identity from conflicting/multiple sampled faces."""
    from .engine import rank
    import numpy as np
    if not samples:raise CaptureError('invalid_recording','No analyzed recording frames')
    visible=[s for s in samples if s['features']]
    selected=max(visible,key=lambda s:(len(s['features']),s.get('face_area',0))) if visible else samples[-1]
    count=max(len(s['features']) for s in samples)
    warning=None
    if count>1:
        decision=dict(status='ambiguous',person_id=None,score=None,face_count=count)
        warning='Multiple faces appear in sampled recording frames'
    elif not visible:
        decision=rank([],people,threshold,margin)
    else:
        vectors=[s['features'][0] for s in visible]
        valid=[v for v in vectors if v is not None]
        inconsistent=any(float(np.dot(a,b))<.45 for i,a in enumerate(valid) for b in valid[:i])
        decisions=[rank(s['features'],people,threshold,margin) if s['features'][0] is not None else
                   dict(status='unknown',person_id=None,score=None,face_count=1) for s in visible]
        identities={d['person_id'] for d in decisions if d['person_id']}
        if inconsistent or len(identities)>1 or any(d['status']=='ambiguous' for d in decisions) or (len(visible)>1 and len(valid)!=len(visible)):
            decision=dict(status='ambiguous',person_id=None,score=None,face_count=1)
            warning='Inconsistent or uncomparable faces across recording samples; no identity selected'
        else:
            best=max(range(len(visible)),key=lambda i:(decisions[i]['status']=='recognized',decisions[i]['score'] or -1,visible[i].get('face_area',0)))
            selected,decision=visible[best],decisions[best]
    result=dict(features=selected['features'],warnings=list(selected.get('warnings',[])),decision=decision)
    if warning:result['warnings'].append(warning)
    return selected['image'],result,selected['offset']

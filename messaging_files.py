"""Validate conversation media, bound decoded audio and serve only scoped bytes."""
import io,os,shutil,subprocess,tempfile
from werkzeug.utils import secure_filename
from PIL import Image,UnidentifiedImageError

TYPES={'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp','gif':'image/gif','pdf':'application/pdf','mp3':'audio/mpeg','m4a':'audio/mp4','ogg':'audio/ogg','wav':'audio/wav','webm':'audio/webm'}

def audio_seconds(content,ext,limit):
    import imageio_ffmpeg
    demux={'mp3':'mp3','m4a':'mov','ogg':'ogg','wav':'wav','webm':'matroska'}[ext]
    with tempfile.TemporaryDirectory(prefix='schoolflow-audio-') as root:
        source=os.path.join(root,'input.'+ext);target=os.path.join(root,'decoded.pcm')
        with open(source,'wb') as stream:stream.write(content)
        command=[imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-threads','1','-protocol_whitelist','file,pipe','-f',demux,'-i',source,'-map','0:a:0','-vn','-ac','1','-ar','8000','-t',str(limit+1),'-f','s16le',target]
        try:result=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=15,check=False)
        except (OSError,subprocess.TimeoutExpired):raise ValueError('Audio could not be validated. Try a shorter recording.')
        if result.returncode or not os.path.exists(target):raise ValueError('Use a valid playable audio file.')
        duration=os.path.getsize(target)/16000
        if not 0<duration<=limit:raise ValueError('Audio exceeds the allowed duration of '+str(limit)+' seconds.')
        return duration

def uploads(config):
    from flask import request
    result=[];total=0
    for field,voice in [('attachments',False),('voice',True)]:
        files=[f for f in request.files.getlist(field) if f.filename]
        for file in files:
            if not config['files'] or (voice and not config['voice']):raise ValueError('This school has disabled this attachment type.')
            name=secure_filename(file.filename)[:160];ext=name.rsplit('.',1)[-1].lower();mime=TYPES.get(ext)
            group='photos' if mime and mime.startswith('image/') else 'pdf' if ext=='pdf' else 'audio'
            if not mime or not config[group] or (voice and not mime.startswith('audio/')):raise ValueError('Use enabled photo, PDF or audio file types.')
            content=file.read(config['max_mb']*1024*1024+1);total+=len(content)
            if not content or len(content)>config['max_mb']*1024*1024 or total>20*1024*1024:raise ValueError('Files exceed the configured limit or the 20 MB combined limit.')
            seconds=0
            if group=='photos':
                try:
                    with Image.open(io.BytesIO(content)) as image:
                        if image.format!={'jpg':'JPEG','jpeg':'JPEG','png':'PNG','webp':'WEBP','gif':'GIF'}[ext] or image.width*image.height>25000000:raise ValueError()
                        image.verify()
                except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):raise ValueError('Use a valid photo file.')
            elif group=='pdf':
                if not content.startswith(b'%PDF-'):raise ValueError('Use a valid PDF file.')
            else:
                valid={'mp3':content.startswith(b'ID3') or (len(content)>1 and content[0]==255 and content[1]&224==224),'m4a':len(content)>12 and content[4:8]==b'ftyp','ogg':content.startswith(b'OggS'),'wav':content.startswith(b'RIFF') and content[8:12]==b'WAVE','webm':content.startswith(b'\x1aE\xdf\xa3')}[ext]
                if not valid:raise ValueError('Use a valid audio container.')
                seconds=audio_seconds(content,ext,config['voice_seconds'] if voice else 900)
            result.append(dict(name=name,mime=mime,content=content,voice=voice,seconds=seconds))
            if len(result)>5:raise ValueError('Attach at most five files per message.')
    return result

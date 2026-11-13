"""Generate build-time launcher assets from a validated school snapshot."""
import argparse,base64,io,json,re,shutil
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parent

def validate(data):
    if not isinstance(data,dict) or not re.fullmatch(r'[0-9a-f]{32}',str(data.get('school_key',''))):raise ValueError('Invalid immutable school identity')
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,39}',str(data.get('code',''))):raise ValueError('Invalid institute code')
    name=data.get('name','')
    if not isinstance(name,str) or not 1<=len(name)<=80 or any(ord(c)<32 or ord(c) in (*range(0x202a,0x202f),*range(0x2066,0x206a)) for c in name):raise ValueError('Invalid launcher name')
    return data

def prepare(data,logo=b''):
    validate(data);target=ROOT/'generated-school-res'
    if target.exists():shutil.rmtree(target)
    target.mkdir()
    if logo:
        if len(logo)>5*1024*1024:raise ValueError('Logo too large')
        with Image.open(io.BytesIO(logo)) as source:
            if source.width*source.height>16000000:raise ValueError('Logo dimensions too large')
            source.load();image=source.convert('RGBA')
    else:
        image=Image.new('RGBA',(512,512),'#176b4a');draw=ImageDraw.Draw(image)
        initials=''.join(word[0] for word in data['name'].split()[:3]).upper()
        fonts=[Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),Path('/usr/share/fonts/TTF/DejaVuSans-Bold.ttf')]
        font=next((ImageFont.truetype(str(path),160) for path in fonts if path.exists()),ImageFont.load_default(size=160))
        box=draw.textbbox((0,0),initials,font=font);draw.text(((512-(box[2]-box[0]))/2-box[0],(512-(box[3]-box[1]))/2-box[1]),initials,font=font,fill='white')
    # Place the complete logo inside the adaptive icon's safe central region.
    foreground=Image.new('RGBA',(432,432),(255,255,255,0));fitted=ImageOps.contain(image,(248,248),Image.Resampling.LANCZOS);foreground.alpha_composite(fitted,((432-fitted.width)//2,(432-fitted.height)//2))
    (target/'drawable').mkdir();foreground.save(target/'drawable'/'school_icon_foreground.png')
    for density,size in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
        folder=target/('mipmap-'+density);folder.mkdir();canvas=Image.new('RGBA',(size,size),'white');fit=ImageOps.contain(image,(round(size*.72),round(size*.72)),Image.Resampling.LANCZOS);canvas.alpha_composite(fit,((size-fit.width)//2,(size-fit.height)//2));canvas.save(folder/'school_launcher.png')
    folder=target/'mipmap-anydpi-v26';folder.mkdir();(folder/'school_launcher.xml').write_text('<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android"><background android:drawable="@android:color/white"/><foreground android:drawable="@drawable/school_icon_foreground"/></adaptive-icon>')
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('manifest');parser.add_argument('--logo');args=parser.parse_args()
    prepare(json.loads(Path(args.manifest).read_text()),Path(args.logo).read_bytes() if args.logo else b'')

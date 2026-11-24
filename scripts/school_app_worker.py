"""Trusted central builder. Never prints tokens, passwords, keys or school records."""
import argparse,base64,hashlib,importlib.util,io,json,os,re,shutil,subprocess,tempfile,time,urllib.request,urllib.parse,zipfile
from PIL import Image
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CLIENTS=ROOT/'mobile'/'clients'
AUDIENCE='https://schoolflow-phase1.onrender.com/api/app-builder'
ROLES={'parents':'Parents','teacher':'Teacher','owner':'Owner','sms':'SMS','qr':'QR Attendance'}

def oidc_token():
    url=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&audience='+urllib.parse.quote(AUDIENCE,safe='')
    req=urllib.request.Request(url,headers={'Authorization':'bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)['value']

def api(base,action,body,method='POST',token=None):
    req=urllib.request.Request(base+'/api/app-builder/'+action,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+(token or oidc_token()),'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)

def tools():
    sdk=Path(os.environ['ANDROID_HOME']);folders=sorted((sdk/'build-tools').glob('*'))
    folder=next((folder for folder in reversed(folders) if (folder/'aapt').exists() and (folder/'apksigner').exists()),None)
    if folder is None:raise RuntimeError('Android verification tools unavailable')
    return folder/'aapt',folder/'apksigner'

def make_key(path,password):
    env={**os.environ,'SCHOOLFLOW_KEYSTORE_PASSWORD':password}
    subprocess.run(['keytool','-genkeypair','-keystore',str(path),'-storetype','PKCS12','-alias','schoolflow','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=SchoolFlow School Apps','-storepass:env','SCHOOLFLOW_KEYSTORE_PASSWORD','-keypass:env','SCHOOLFLOW_KEYSTORE_PASSWORD'],env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def decode_label(value):
    # aapt quotes punctuation in its text output; preserve non-ASCII school names.
    result=[];index=0
    while index<len(value):
        if ord(value[index])==92 and index+1<len(value) and ord(value[index+1]) in (92,34,39):
            result.append(value[index+1]);index+=2
        else:result.append(value[index]);index+=1
    return ''.join(result)

def verify_school_icon(archive,expected_path):
    # Non-debuggable Android builds may shorten resource filenames. Verify the
    # compiled PNG's visible pixels rather than relying on its source basename.
    def visible(image):
        canvas=Image.new('RGBA',image.size,'white');canvas.alpha_composite(image.convert('RGBA'));return canvas.convert('RGB').tobytes()
    with Image.open(expected_path) as expected:
        size=expected.size;pixels=visible(expected)
    matches=0
    for member in archive.infolist():
        if not member.filename.startswith('res/') or not member.filename.endswith('.png') or member.file_size>5*1024*1024:continue
        with Image.open(io.BytesIO(archive.read(member))) as actual:
            if actual.size==size and visible(actual)==pixels:matches+=1
    if matches!=1:raise RuntimeError('APK icon does not match its school logo')

def inspect_apks(branding,source_sha):
    aapt,signer=tools();artifacts=[]
    for role,title in ROLES.items():
        path=CLIENTS/'app'/'build'/'outputs'/'apk'/role/'debug'/('app-'+role+'-debug.apk')
        badging=subprocess.check_output([str(aapt),'dump','badging',str(path)],text=True)
        package=re.search(r"package: name='([^']+)' versionCode='(\d+)'",badging)
        label=re.search(r"^application-label:'(.*)'$",badging,re.MULTILINE)
        certificate=subprocess.check_output([str(signer),'verify','--print-certs',str(path)],text=True)
        certificates={value.lower() for value in re.findall(r'certificate SHA-256 digest:\s*([0-9a-fA-F]{64})',certificate)}
        fingerprint=next(iter(certificates)) if len(certificates)==1 else ''
        expected='com.schoolflow.schools.s'+branding['school_key']+'.'+role+'.test'
        label_text=decode_label(label[1]) if label else None
        observed=dict(package=package[1] if package else None,version=int(package[2]) if package else None,label=label_text,certificate_found=bool(fingerprint))
        if os.environ.get('SCHOOLFLOW_FIXTURE_BUILD')=='1':print('Fictional APK verification:',observed,flush=True)
        if not package or package[1]!=expected:raise RuntimeError('APK package does not match its school')
        if int(package[2])!=branding['sequence']:raise RuntimeError('APK version does not match its school build')
        if label_text!=branding['name']+' '+title:raise RuntimeError('APK launcher name does not match its school')
        if not fingerprint:raise RuntimeError('APK signing certificate could not be verified')
        with zipfile.ZipFile(path) as archive:
            verify_school_icon(archive,CLIENTS/'generated-school-res'/'drawable'/'school_icon_foreground.png')
        blob=path.read_bytes();artifacts.append(dict(role=role,package=package[1],label=label_text,version_code=int(package[2]),signing_sha256=fingerprint,sha256=hashlib.sha256(blob).hexdigest(),content=base64.b64encode(blob).decode()))
    return dict(source_sha=source_sha,artifacts=artifacts)

def build(branding,logo,keyfile,password):
    module=importlib.util.spec_from_file_location('prepare_branding',CLIENTS/'prepare_branding.py');prepare=importlib.util.module_from_spec(module);module.loader.exec_module(prepare)
    prepare.prepare(branding,logo)
    with tempfile.TemporaryDirectory(prefix='schoolflow-brand-') as tmp:
        manifest=Path(tmp)/'branding.json';manifest.write_text(json.dumps(branding))
        args=['gradle','--no-daemon','--console=plain','-PschoolBrandingFile='+str(manifest),'-PschoolSigningFile='+str(keyfile)]
        for role in ROLES:
            cap=role.capitalize();args.extend([':app:test'+cap+'DebugUnitTest',':app:lint'+cap+'Debug',':app:assemble'+cap+'Debug'])
        # Dependency servers occasionally throttle GitHub runners. Keep the same
        # claimed build and signing key while Gradle retries the download.
        for attempt in range(3):
            rate_limited=False
            with subprocess.Popen(args,cwd=CLIENTS,env={**os.environ,'SCHOOLFLOW_KEYSTORE_PASSWORD':password},
                                  stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace') as process:
                for line in process.stdout:
                    print(line,end='',flush=True)
                    rate_limited |= 'Received status code 429' in line
                status=process.wait()
            if status==0:return
            if not rate_limited or attempt==2:raise subprocess.CalledProcessError(status,args)
            delay=20*(attempt+1)
            print(f'Dependency server is rate limiting Gradle. Retrying in {delay} seconds.',flush=True)
            time.sleep(delay)

def run(base,fixture_token=None):
    claimed=api(base,'claim',{'source_version':13},token=fixture_token);job=claimed.get('job')
    if not job:print('No pending school app builds.');return False
    bid=job['id']
    try:
        branding={**job['branding'],'sequence':job['sequence']};signing=job['signing']
        with tempfile.TemporaryDirectory(prefix='schoolflow-signing-') as tmp:
            key=Path(tmp)/'school.p12'
            if signing['keystore']:key.write_bytes(base64.b64decode(signing['keystore'],validate=True))
            else:make_key(key,signing['password'])
            api(base,bid+'/signing',{'keystore':base64.b64encode(key.read_bytes()).decode()},method='PUT',token=fixture_token)
            build(branding,base64.b64decode(job['logo'],validate=True),key,signing['password'])
            result=inspect_apks(branding,os.environ['GITHUB_SHA'])
            api(base,bid+'/complete',result,token=fixture_token)
        print('Five school-specific APKs verified and returned to the correct school.');return True
    except Exception:
        try:api(base,bid+'/fail',{},token=fixture_token)
        except Exception:pass
        raise
    finally:
        shutil.rmtree(CLIENTS/'generated-school-res',ignore_errors=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='https://schoolflow-phase1.onrender.com');parser.add_argument('--max-jobs',type=int,default=2);args=parser.parse_args()
    if args.base!='https://schoolflow-phase1.onrender.com':raise SystemExit('The central worker is pinned to the original SchoolFlow host')
    for attempt in range(8):
        try:
            for index in range(min(2,max(1,args.max_jobs))):
                if not run(args.base):break
            break
        except urllib.error.HTTPError as error:
            if error.code not in (404,502,503) or attempt==7:raise
            time.sleep(15)

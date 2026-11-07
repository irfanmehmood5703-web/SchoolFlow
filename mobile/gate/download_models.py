"""Build-only download of pinned official OpenCV models; no user data."""
import hashlib,json,pathlib,urllib.request
ROOT=pathlib.Path(__file__).parent
COMMIT="48b10fa505aeb51fbd127fc60a5c660040e823b7"
MODELS=[
 ("face_detection_yunet","face_detection_yunet_2023mar.onnx","8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",232589),
 ("face_recognition_sface","face_recognition_sface_2021dec.onnx","0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",38696353)
]
target=ROOT/"app/src/main/assets"
target.mkdir(parents=True,exist_ok=True)
for folder,name,digest,size in MODELS:
 path=target/name
 if path.exists() and len(path.read_bytes())==size and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
  continue
 url=f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{COMMIT}/models/{folder}/{name}"
 request=urllib.request.Request(url,headers={"User-Agent":"SchoolFlow-Gate-build"})
 with urllib.request.urlopen(request,timeout=120) as response:
  data=response.read(size+1)
 if len(data)!=size or hashlib.sha256(data).hexdigest()!=digest:
  raise SystemExit(f"Integrity check failed for {name}")
 path.write_bytes(data)
 print(f"Verified {name} ({size} bytes)")
(target/"models.json").write_text(json.dumps({"source_commit":COMMIT,"models":[dict(name=n,sha256=d,size=s) for _,n,d,s in MODELS]},indent=2)+"\n")

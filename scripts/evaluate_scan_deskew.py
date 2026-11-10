"""Compare deskew against a known synthetic shear on labeled document photos."""
from pathlib import Path
import argparse, importlib.util,numpy as np,cv2,math,json
from PIL import Image,ImageOps
from markdown_to_handwrite.scanner import _rectify,_straighten_text_rows
parser=argparse.ArgumentParser()
parser.add_argument('dataset',type=Path)
parser.add_argument('--baseline',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
spec=importlib.util.spec_from_file_location('markdown_to_handwrite._benchmark_scanner',args.baseline);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
root=args.dataset;res=[];n=0
for q in sorted((root/'quads').glob('*.txt')):
 ps=list((root/'images').glob(q.stem+'.*'))
 if not ps:continue
 vals=[float(x) for x in q.read_text().split()]
 if len(vals)!=8:continue
 im=ImageOps.exif_transpose(Image.open(ps[0])).convert('RGB');im.thumbnail((1200,1200));page=_rectify(np.asarray(im),np.array(vals).reshape(4,2).tolist());h,w=page.shape[:2]
 if min(h,w)<500:continue
 n+=1;x=np.arange(w,dtype=np.float32);y=np.arange(h,dtype=np.float32);tilt=cv2.remap(page,np.broadcast_to(x,(h,w)).copy(),(y[:,None]-math.tan(math.radians(4))*(x[None,:]-w/2)).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE);a=old._straighten_text_rows(tilt);b=_straighten_text_rows(tilt)
 if np.array_equal(a,b):continue
 sl=(slice(h//10,h*9//10),slice(w//10,w*9//10));target=page[sl].astype(np.float32);ea=float(np.abs(a[sl].astype(np.float32)-target).mean());eb=float(np.abs(b[sl].astype(np.float32)-target).mean());res.append({'image':q.stem,'previous_mae':ea,'new_mae':eb})
print('evaluated',n,'changed',len(res),'improved',sum(x['new_mae']+.2<x['previous_mae'] for x in res),'worse',sum(x['new_mae']>x['previous_mae']+.2 for x in res));print(res)
args.output.write_text(json.dumps({'evaluated':n,'results':res},indent=2))

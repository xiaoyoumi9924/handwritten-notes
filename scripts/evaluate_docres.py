import sys, time, json, os
from pathlib import Path
import cv2,numpy as np,torch
from PIL import Image, ImageOps, ImageDraw
sys.path.insert(0,str(Path(os.environ.get('DOCRES_STUDY_DIR', 'output/docres-study')) / 'code'))
from models.restormer_arch import Restormer
from markdown_to_handwrite.scanner import process_scan_image

torch.set_num_threads(4)
p=Path(os.environ.get('DOCRES_STUDY_DIR', 'output/docres-study'))
max_edge=int(os.environ.get('DOCRES_MAX_EDGE', '768'))
source_dir=Path(os.environ.get('DOCRES_SOURCE_DIR', 'output/scan-challenge/sources'))
device=torch.device(os.environ.get('DOCRES_DEVICE','cpu'))
model=Restormer(inp_channels=6,out_channels=3,dim=48,num_blocks=[2,3,3,4],num_refinement_blocks=4,heads=[1,2,4,8],ffn_expansion_factor=2.66,bias=False,LayerNorm_type='WithBias',dual_pixel_task=True).eval()
s=torch.load(p/'weights/docres-mirror.pkl',map_location='cpu',weights_only=True)
s=s['model_state']; model.load_state_dict({k.removeprefix('module.'):v for k,v in s.items()}); model.to(device)
records=[]
for name in os.environ.get('DOCRES_SAMPLES','user-notes.jpg,math_cheat_sheet.JPG,chart.JPG,receipt.jpg').split(','):
    img=ImageOps.exif_transpose(Image.open(source_dir/name)).convert('RGB'); img.thumbnail((max_edge,max_edge))
    rgb=np.asarray(img); bgr=rgb[:,:,::-1].copy(); h,w=bgr.shape[:2]
    resized=cv2.resize(bgr,(1024,1024)); bg=[]; norm=[]
    for plane in cv2.split(resized):
        b=cv2.medianBlur(cv2.dilate(plane,np.ones((7,7),np.uint8)),21); bg.append(b)
        diff=255-cv2.absdiff(plane,b); norm.append(cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX,dtype=cv2.CV_8UC1))
    variants={'appearance':cv2.resize(cv2.merge(norm),(w,h)), 'deshadowing':cv2.resize(cv2.merge(bg),(w,h))}
    sheet=Image.new('RGB',(1600,650),'white'); draw=ImageDraw.Draw(sheet)
    for i,(mode,prompt) in enumerate(variants.items()):
        inp=np.concatenate((bgr,prompt),axis=2); ph=(-h)%8; pw=(-w)%8; inp=cv2.copyMakeBorder(inp,0,ph,0,pw,cv2.BORDER_REPLICATE)
        t=(torch.from_numpy(inp.transpose(2,0,1).copy()).float().unsqueeze(0)/255).to(device)
        start=time.perf_counter()
        with torch.inference_mode(): result=model(t).clamp(0,1)[0,:,:h,:w].permute(1,2,0).cpu().numpy()
        elapsed=time.perf_counter()-start
        output=Image.fromarray((result[:,:,::-1]*255).astype('uint8'))
        output.save(p/f'{Path(name).stem}-{mode}.png'); records.append({'sample':name,'task':mode,'seconds':round(elapsed,2),'size':[w,h]})
        for j,(label,pic) in enumerate([('original',img),('current '+('smart' if i==0 else 'shadow'),process_scan_image(img,None,'smart' if i==0 else 'shadow')),('DocRes '+mode,output)]):
            thumb=ImageOps.contain(pic,(260,590)); x=(i*3+j)*265; sheet.paste(thumb,(x+(260-thumb.width)//2,35)); draw.text((x+5,10),label,fill='black')
        print(records[-1],flush=True)
    sheet.save(p/f'{Path(name).stem}-comparison.jpg',quality=93)
(p/'metrics.json').write_text(json.dumps(records,indent=2))

"""Compare a DocRes-derived smooth exposure map with existing scan filters.

Uses the 768px outputs of evaluate_docres.py; retains full-resolution source
pixels and applies a capped, blurred luminance gain. Research only.
"""
from pathlib import Path
import time,json
import cv2
import numpy as np
from PIL import Image,ImageOps,ImageDraw
from markdown_to_handwrite.scan_illumination import paper_background
from markdown_to_handwrite.scanner import process_scan_image

root=Path('output/docres-study'); out=Path('output/docres-illumination-study');out.mkdir(parents=True,exist_ok=True)
records=[]
for name in ('user-notes.jpg','math_cheat_sheet.JPG','chart.JPG','receipt.jpg'):
    source=ImageOps.exif_transpose(Image.open('output/scan-challenge/sources/'+name)).convert('RGB')
    source.thumbnail((1600,1600),Image.Resampling.LANCZOS)
    rgb=np.asarray(source); h,w=rgb.shape[:2]
    start=time.perf_counter()
    pred=np.asarray(Image.open(root/f'{Path(name).stem}-appearance.png').convert('RGB'))
    small=np.asarray(ImageOps.contain(source,(pred.shape[1],pred.shape[0]),Image.Resampling.LANCZOS))
    small=cv2.resize(small,(pred.shape[1],pred.shape[0]))
    src_bg=cv2.cvtColor(paper_background(small),cv2.COLOR_RGB2GRAY).astype('float32')
    dst_bg=cv2.cvtColor(paper_background(pred),cv2.COLOR_RGB2GRAY).astype('float32')
    gain=np.clip(dst_bg/np.maximum(src_bg,1),1,2.2)
    gain=cv2.GaussianBlur(gain,(0,0),15)
    gain=cv2.resize(gain,(w,h),interpolation=cv2.INTER_LINEAR)
    result=np.rint(np.clip(rgb.astype('float32')*gain[:,:,None],0,255)).astype('uint8')
    result=Image.fromarray(result);result.save(out/f'{Path(name).stem}-gain.png')
    elapsed=time.perf_counter()-start
    variants=[('Original',source),('Current shadow',process_scan_image(source,None,'shadow')),('DocRes low res',Image.fromarray(pred)),('DocRes light map',result)]
    sheet=Image.new('RGB',(1600,750),'#f2f4f9');draw=ImageDraw.Draw(sheet)
    for i,(label,pic) in enumerate(variants):
        thumb=ImageOps.contain(pic,(390,700),Image.Resampling.LANCZOS);sheet.paste(thumb,(i*400+(400-thumb.width)//2,35));draw.text((i*400+8,10),label,fill='black')
    sheet.save(out/f'{Path(name).stem}-comparison.jpg',quality=94)
    records.append({'sample':name,'source_size':[w,h],'model_size':list(pred.shape[1::-1]),'gain_seconds':round(elapsed,3),'gain_min':round(float(gain.min()),3),'gain_max':round(float(gain.max()),3)})
    print(records[-1],flush=True)
(out/'metrics.json').write_text(json.dumps(records,indent=2))

from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageOps,ImageDraw
from markdown_to_handwrite.scanner import process_scan_image
out=Path('output/docres-color-v2');out.mkdir(exist_ok=True)
for name in ['user-notes','math_cheat_sheet','chart','receipt']:
 root=Path('output/scan-challenge/sources'); src=next(x for x in root.iterdir() if x.stem==name)
 original=ImageOps.exif_transpose(Image.open(src)).convert('RGB');original.thumbnail((1600,1600))
 clean=np.asarray(process_scan_image(original,None,'shadow')); light=np.asarray(Image.open(f'output/docres-illumination-study/{name}-gain.png'))
 pred=np.asarray(Image.open(f'output/docres-study/{name}-appearance.png').convert('RGB'))
 lab=cv2.cvtColor(pred,cv2.COLOR_RGB2LAB); lumin=lab[:,:,0]; ref=np.median(lab[lumin>=np.percentile(lumin,75)],axis=0)
 chroma=np.sqrt(np.sum((lab[:,:,1:].astype('float32')-ref[1:])**2,axis=2))
 m=((chroma>5)&(lumin>130)).astype('uint8'); m=cv2.morphologyEx(m,cv2.MORPH_CLOSE,np.ones((13,13),'uint8'))
 n,labels,stats,_=cv2.connectedComponentsWithStats(m,8);keep=np.zeros(n,dtype='uint8');keep[1:]=(stats[1:,cv2.CC_STAT_AREA]>450)
 mask=keep[labels];mask=cv2.GaussianBlur(mask.astype('float32'),(0,0),1.5);mask=cv2.resize(mask,(clean.shape[1],clean.shape[0]))
 ink_guard=np.clip((cv2.cvtColor(clean,cv2.COLOR_RGB2GRAY).astype(np.float32)-55)/90,0,1);mask*=ink_guard
 merged=np.rint(clean*(1-mask[:,:,None])+light*mask[:,:,None]).clip(0,255).astype('uint8');Image.fromarray(merged).save(out/f'{name}-v2.png')
 sheet=Image.new('RGB',(1200,600),'white');draw=ImageDraw.Draw(sheet)
 for i,(title,img) in enumerate([('original',original),('current',Image.fromarray(clean)),('candidate',Image.fromarray(merged))]):
  thumb=ImageOps.contain(img,(390,550));sheet.paste(thumb,(i*400+(400-thumb.width)//2,30));draw.text((i*400+5,8),title,fill='black')
 sheet.save(out/f'{name}-comparison.jpg',quality=94); print(name,round(float(mask.mean()),4),flush=True)

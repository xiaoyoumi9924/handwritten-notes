from pathlib import Path
import numpy as np, cv2
from PIL import Image,ImageOps,ImageDraw
from markdown_to_handwrite.scanner import process_scan_image
out=Path('output/docres-illumination-study')
for name in ['user-notes','math_cheat_sheet','chart','receipt']:
    root=Path('output/scan-challenge/sources'); src=next(x for x in root.iterdir() if x.stem==name)
    original=ImageOps.exif_transpose(Image.open(src)).convert('RGB');original.thumbnail((1600,1600))
    clean=np.asarray(process_scan_image(original,None,'shadow')).copy(); light=np.asarray(Image.open(out/f'{name}-gain.png'))
    pred=np.asarray(Image.open(f'output/docres-study/{name}-appearance.png').convert('RGB'))
    hsv=cv2.cvtColor(pred,cv2.COLOR_RGB2HSV);sat=hsv[:,:,1]; val=hsv[:,:,2]
    candidate=((sat>32)&(val>80)).astype('uint8')
    n,labels,stats,_=cv2.connectedComponentsWithStats(candidate,8)
    keep=np.zeros(n,dtype='uint8'); keep[1:]=(stats[1:,cv2.CC_STAT_AREA]>250).astype('uint8')
    mask=keep[labels];mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,7),'uint8'))
    mask=cv2.GaussianBlur(mask.astype('float32'),(0,0),2);mask=cv2.resize(mask,(clean.shape[1],clean.shape[0]))
    merged=np.rint(clean*(1-mask[:,:,None])+light*mask[:,:,None]).clip(0,255).astype('uint8');Image.fromarray(merged).save(out/f'{name}-hybrid.png')
    sheet=Image.new('RGB',(1200,600),'white');draw=ImageDraw.Draw(sheet)
    for i,(title,img) in enumerate([('original',original),('current',Image.fromarray(clean)),('hybrid',Image.fromarray(merged))]):
        thumb=ImageOps.contain(img,(390,550));sheet.paste(thumb,(i*400+(400-thumb.width)//2,30));draw.text((i*400+5,8),title,fill='black')
    sheet.save(out/f'{name}-hybrid-comparison.jpg',quality=94)
    print(name,'color fraction',round(float(mask.mean()),4),flush=True)

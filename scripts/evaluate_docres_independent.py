"""Apply experimental guarded color blend to additional real inputs."""
from pathlib import Path
import os
import cv2,numpy as np
from PIL import Image,ImageOps,ImageDraw
from markdown_to_handwrite.scan_illumination import paper_background
from markdown_to_handwrite.scanner import process_scan_image
root=Path(os.environ.get('DOCRES_STUDY_DIR','output/docres-independent'))
for path in sorted((root/'sources').iterdir()):
    original=ImageOps.exif_transpose(Image.open(path)).convert('RGB');original.thumbnail((1600,1600))
    rgb=np.asarray(original);h,w=rgb.shape[:2]; pred=np.asarray(Image.open(root/f'{path.stem}-appearance.png').convert('RGB'))
    small=cv2.resize(rgb,(pred.shape[1],pred.shape[0]),interpolation=cv2.INTER_AREA)
    src=cv2.cvtColor(paper_background(small),cv2.COLOR_RGB2GRAY).astype('float32');dst=cv2.cvtColor(paper_background(pred),cv2.COLOR_RGB2GRAY).astype('float32')
    gain=cv2.GaussianBlur(np.clip(dst/np.maximum(src,1),1,2.2),(0,0),15);gain=cv2.resize(gain,(w,h));light=np.clip(rgb.astype('float32')*gain[:,:,None],0,255)
    lab=cv2.cvtColor(pred,cv2.COLOR_RGB2LAB);lum=lab[:,:,0];ref=np.median(lab[lum>=np.percentile(lum,75)],axis=0)
    delta=np.linalg.norm(lab[:,:,1:].astype('float32')-ref[1:],axis=2);mask=((delta>5)&(lum>130)).astype('uint8')
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((13,13),'uint8'));n,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    keep=np.zeros(n,dtype='uint8');keep[1:]=(stats[1:,cv2.CC_STAT_AREA]>450)
    mask=cv2.resize(cv2.GaussianBlur(keep[labels].astype('float32'),(0,0),1.5),(w,h))
    before=np.asarray(process_scan_image(original,None,'shadow'));guard=np.clip((cv2.cvtColor(before,cv2.COLOR_RGB2GRAY).astype('float32')-55)/90,0,1);mask*=guard
    after=np.rint(before*(1-mask[:,:,None])+light*mask[:,:,None]).clip(0,255).astype('uint8')
    Image.fromarray(after).save(root/f'{path.stem}-hybrid.png')
    sheet=Image.new('RGB',(1500,650),'white');draw=ImageDraw.Draw(sheet)
    for i,(label,pic) in enumerate([('original',original),('current',Image.fromarray(before)),('candidate',Image.fromarray(after))]):
        thumb=ImageOps.contain(pic,(490,610));sheet.paste(thumb,(i*500+(500-thumb.width)//2,30));draw.text((i*500+5,8),label,fill='black')
    sheet.save(root/f'{path.stem}-hybrid-comparison.jpg',quality=94);print(path.name,round(float(mask.mean()),4),flush=True)

"""Measure a candidate against three generated pages; diagnostic, not accuracy."""
from pathlib import Path
import json
import cv2
import numpy as np
from PIL import Image
from markdown_to_handwrite.scan_illumination import paper_background
from markdown_to_handwrite.scanner import process_scan_image

root=Path('output/docres-color-v2'); data=root/'synthetic'; results=[]
for name in ('color','tinted','mono'):
    rgb=np.asarray(Image.open(data/'sources'/f'{name}.png').convert('RGB'))
    truth=np.asarray(Image.open(data/f'{name}-clean.png').convert('RGB'))
    pred=np.asarray(Image.open(root/f'{name}-appearance.png').convert('RGB'))
    h,w=rgb.shape[:2]; low=cv2.resize(rgb,(pred.shape[1],pred.shape[0]),interpolation=cv2.INTER_AREA)
    src=cv2.cvtColor(paper_background(low),cv2.COLOR_RGB2GRAY).astype(np.float32)
    dst=cv2.cvtColor(paper_background(pred),cv2.COLOR_RGB2GRAY).astype(np.float32)
    gain=cv2.GaussianBlur(np.clip(dst/np.maximum(src,1),1,2.2),(0,0),15)
    gain=cv2.resize(gain,(w,h)); light=np.clip(rgb.astype(np.float32)*gain[:,:,None],0,255)
    lab=cv2.cvtColor(pred,cv2.COLOR_RGB2LAB); lum=lab[:,:,0]
    ref=np.median(lab[lum>=np.percentile(lum,75)],axis=0)
    dist=np.linalg.norm(lab[:,:,1:].astype(np.float32)-ref[1:],axis=2)
    mask=((dist>5)&(lum>130)).astype('uint8')
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((13,13),np.uint8))
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    keep=np.zeros(n,dtype='uint8');keep[1:]=(stats[1:,cv2.CC_STAT_AREA]>450)
    mask=cv2.resize(cv2.GaussianBlur(keep[labels].astype(np.float32),(0,0),1.5),(w,h))
    before=np.asarray(process_scan_image(Image.fromarray(rgb),None,'shadow')).astype(np.float32)
    ink_guard=np.clip((cv2.cvtColor(before.astype(np.uint8),cv2.COLOR_RGB2GRAY).astype(np.float32)-55)/90,0,1)
    mask=mask*ink_guard
    after=np.rint(before*(1-mask[:,:,None])+light*mask[:,:,None]).clip(0,255).astype(np.uint8)
    Image.fromarray(after).save(root/f'{name}-hybrid.png')
    fill=np.zeros((h,w),bool)
    for i in range(8): fill[110+i*90:140+i*90, 620:700]=True
    paper=np.zeros((h,w),bool); paper[30:80,100:700]=True
    line=np.zeros((h,w),bool); line[850,60:741]=True
    def mae(array, region): return round(float(np.abs(array.astype(float)-truth.astype(float))[region].mean()),2)
    results.append({'sample':name,'fill_mae_before':mae(before,fill),'fill_mae_after':mae(after,fill),'paper_mae_before':mae(before,paper),'paper_mae_after':mae(after,paper),'faint_line_mae_before':mae(before,line),'faint_line_mae_after':mae(after,line),'mask_mean':round(float(mask.mean()),4)})
print(json.dumps(results,indent=2));(data/'metrics.json').write_text(json.dumps(results,indent=2))

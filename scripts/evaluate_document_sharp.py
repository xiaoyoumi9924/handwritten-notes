"""Render provided reference pairs and real photos; screenshots are not truth."""
from pathlib import Path
import time,json
import numpy as np
from PIL import Image,ImageOps,ImageDraw
from markdown_to_handwrite.scan_enhancement import sharpen_document
from markdown_to_handwrite.scanner import process_scan_image
root=Path('output/document-sharp-study');root.mkdir(parents=True,exist_ok=True)
records=[]
for number,(source,target,box) in enumerate([(4384,4383,(69,386,874,1370)),(4386,4387,(69,553,874,1205)),(4388,4389,(69,302,874,1528))],1):
    images=[]
    for name in (source,target):
        image=Image.open(f'/Users/meiyh9924/Downloads/IMG_{name}.PNG').convert('RGB')
        crop=tuple(round(v*(image.width/943 if i%2==0 else image.height/2048)) for i,v in enumerate(box))
        images.append(image.crop(crop))
    original,reference=images;original.save(root/f'{number}-input.png');reference.save(root/f'{number}-reference.png')
    start=time.perf_counter();result=Image.fromarray(sharpen_document(np.asarray(original)));elapsed=time.perf_counter()-start;result.save(root/f'{number}-sharp.png')
    pictures=[('Input screenshot',original),('Current smart',process_scan_image(original,None,'smart')),('New sharp',result),('Reference screenshot',reference)]
    sheet=Image.new('RGB',(1600,820),'#f0f3f8');draw=ImageDraw.Draw(sheet)
    for i,(label,pic) in enumerate(pictures):
        thumb=ImageOps.contain(pic,(390,770));sheet.paste(thumb,(i*400+(400-thumb.width)//2,35));draw.text((i*400+8,8),label,fill='black')
    sheet.save(root/f'{number}-comparison.jpg',quality=94);records.append({'pair':number,'size':list(original.size),'seconds':round(elapsed,3)});print(records[-1],flush=True)
(root/'metrics.json').write_text(json.dumps(records,indent=2))

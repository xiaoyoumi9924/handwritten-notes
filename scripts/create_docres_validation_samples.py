"""Build synthetic pages with known originals for color and ink experiments."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

root=Path('output/docres-color-v2/synthetic')
(root/'sources').mkdir(parents=True, exist_ok=True)
font=ImageFont.load_default()
for kind in ('color','tinted','mono'):
    image=Image.new('RGB',(800,1000),(240,230,210) if kind=='tinted' else (245,245,245))
    draw=ImageDraw.Draw(image)
    for index in range(8):
        y=100+index*90
        if kind=='color':
            draw.rectangle((60,y,740,y+50),fill=[(135,180,220),(230,180,180),(235,220,120)][index%3])
        draw.rectangle((60,y,740,y+50),outline=(20,20,20),width=2)
        draw.text((90,y+12),'Sample table 0123456789 abcxyz',fill=(20,20,20),font=font)
        draw.line((500,y,500,y+50),fill=(20,20,20),width=2)
    draw.line((60,850,740,850),fill=(100,100,100),width=1)
    clean=np.asarray(image)
    light=np.linspace(.48,1,800,dtype=np.float32)[None,:,None]
    photo=np.rint(clean*light).clip(0,255).astype('uint8')
    Image.fromarray(photo).save(root/'sources'/f'{kind}.png')
    image.save(root/f'{kind}-clean.png')

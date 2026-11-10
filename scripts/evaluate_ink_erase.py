"""Offline candidate evaluation. Dependencies isolated under output/handwriting-next/deps."""
import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path('output/handwriting-next/deps').resolve()))
import torch,numpy as np,cv2
import segmentation_models_pytorch as smp
from safetensors.torch import load_file
from PIL import Image,ImageOps,ImageDraw
from markdown_to_handwrite.scanner import process_scan_image
root=Path('output/handwriting-next');cfg=json.loads((root/'config.json').read_text());torch.set_num_threads(4)
model=smp.UnetPlusPlus(encoder_name=cfg['encoder_name'],encoder_weights=None,in_channels=3,classes=3,decoder_attention_type=cfg['decoder_attention_type'],activation=cfg['activation']).eval()
keys=set(model.state_dict());model.load_state_dict({k:v for k,v in load_file(root/'model.safetensors').items() if k in keys})
for name,path in [('user-exam','output/webui/scans/37c18094d1218765/original.png'),('printed-chart','output/scan-challenge/sources/chart.JPG'),('mixed-exam','output/handwriting-removal/sources/eraser-test2.jpg')]:
 image=ImageOps.exif_transpose(Image.open(path)).convert('RGB'); image.thumbnail((1600,1600)); rgb=np.asarray(image); h,w=rgb.shape[:2]
 results=[('Original',image),('Current + HD',process_scan_image(image,None,'remove_handwriting'))]
 for label,source in [('raw',rgb),('hd',np.asarray(process_scan_image(image,None,'smart')))]:
  small=cv2.resize(source,(512,512),interpolation=cv2.INTER_AREA); t=torch.from_numpy(small.transpose(2,0,1).copy()).float()[None]/255; start=time.perf_counter()
  with torch.inference_mode(): pred=model(t).clamp(0,1)[0].permute(1,2,0).numpy()
  result=Image.fromarray((pred*255).astype('uint8'));result.save(root/f'{name}-ink-{label}.png');results.append(('InkErase '+label,result));print(name,label,round(time.perf_counter()-start,3),flush=True)
 sheet=Image.new('RGB',(1600,750),'white');draw=ImageDraw.Draw(sheet)
 for i,(label,img) in enumerate(results):
  thumb=ImageOps.contain(img,(390,700));sheet.paste(thumb,(i*400+(400-thumb.width)//2,35));draw.text((i*400+8,8),label,fill='black')
 sheet.save(root/f'{name}-ink-comparison.jpg',quality=94)

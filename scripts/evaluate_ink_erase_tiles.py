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
 image=ImageOps.exif_transpose(Image.open(path)).convert('RGB');image.thumbnail((1600,1600));rgb=np.asarray(image);h,w=rgb.shape[:2]
 result=np.zeros((h,w,3),np.float32);weight=np.zeros((h,w,1),np.float32);start=time.perf_counter()
 def starts(n):return sorted(set([*range(0,max(0,n-512),448),max(0,n-512)]))
 for y in starts(h):
  for x in starts(w):
   patch=rgb[y:y+512,x:x+512];ph,pw=patch.shape[:2];padded=cv2.copyMakeBorder(patch,0,512-ph,0,512-pw,cv2.BORDER_REPLICATE)
   t=torch.from_numpy(padded.transpose(2,0,1).copy()).float()[None]/255
   with torch.inference_mode(): pred=model(t).clamp(0,1)[0].permute(1,2,0).numpy()[:ph,:pw]
   wy=np.minimum(np.arange(ph)+1,np.arange(ph,0,-1));wx=np.minimum(np.arange(pw)+1,np.arange(pw,0,-1));blend=np.minimum(wy[:,None],wx[None,:]).clip(1,32)[:,:,None]
   result[y:y+ph,x:x+pw]+=pred*blend;weight[y:y+ph,x:x+pw]+=blend
 output=Image.fromarray(np.rint(result/weight*255).clip(0,255).astype('uint8'));output.save(root/f'{name}-tiled.png')
 hd=process_scan_image(output,None,'smart');hd.save(root/f'{name}-tiled-hd.png')
 sheet=Image.new('RGB',(1600,900),'white');draw=ImageDraw.Draw(sheet)
 for i,(label,img) in enumerate([('Original',image),('Current + HD',process_scan_image(image,None,'remove_handwriting')),('InkErase tiled',output),('InkErase tiled + HD',hd)]):
  thumb=ImageOps.contain(img,(390,850));sheet.paste(thumb,(i*400+(400-thumb.width)//2,35));draw.text((i*400+8,8),label,fill='black')
 sheet.save(root/f'{name}-tiled-comparison.jpg',quality=94);print(name,'tiled seconds',round(time.perf_counter()-start,2),flush=True)

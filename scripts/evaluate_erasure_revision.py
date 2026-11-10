"""Compare frozen low-level erasure and current erasure, separately from HD."""
from pathlib import Path
import importlib.util,time,json
import numpy as np
from PIL import Image,ImageOps,ImageDraw
from markdown_to_handwrite import handwriting_removal as new
from markdown_to_handwrite.scanner import process_scan_image
root=Path('output/handwriting-next')
spec=importlib.util.spec_from_file_location('markdown_to_handwrite.erasure_before',root/'before.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old);old._load_model=new._load_model
records=[]
for label,path in [('user-exam','output/webui/scans/37c18094d1218765/original.png'),('chart','output/scan-challenge/sources/chart.JPG'),('receipt','output/scan-challenge/sources/receipt.jpg'),('mixed','output/handwriting-removal/sources/eraser-test2.jpg')]:
 im=ImageOps.exif_transpose(Image.open(path)).convert('RGB');rgb=np.asarray(im);t=time.perf_counter();before=old.remove_handwriting(rgb);after=new.remove_handwriting(rgb)
 hd=process_scan_image(Image.fromarray(after),None,'smart');hd.save(root/f'{label}-new-hd.png')
 changed=np.any(after!=rgb,axis=2);dark=rgb.min(axis=2)<150
 record={'sample':label,'low_level_unchanged':bool(np.array_equal(after,rgb)),'changed_pixels':int(changed.sum()),'top_180_dark_changed':int((changed[:180]&dark[:180]).sum()),'seconds_both_versions':round(time.perf_counter()-t,2)};records.append(record);print(record,flush=True)
 sheet=Image.new('RGB',(1800,900),'white');draw=ImageDraw.Draw(sheet)
 for i,(name,pic) in enumerate([('Original',im),('Previous erasure',Image.fromarray(before)),('Revised erasure',Image.fromarray(after)),('Revised + smart HD',hd)]):
  thumb=ImageOps.contain(pic,(440,850));sheet.paste(thumb,(i*450+(450-thumb.width)//2,35));draw.text((i*450+8,8),name,fill='black')
 sheet.save(root/f'{label}-revision.jpg',quality=94)
(root/'revision-metrics.json').write_text(json.dumps(records,indent=2))

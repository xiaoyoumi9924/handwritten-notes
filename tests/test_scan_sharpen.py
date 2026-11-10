import io
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from markdown_to_handwrite.scanner import ScanService,process_scan_image


class DocumentSharpenTests(unittest.TestCase):
    def test_whitens_paper_and_keeps_thin_ink_and_color(self):
        image=Image.new('RGB',(600,500),(200,200,200));draw=ImageDraw.Draw(image)
        draw.line((30,100,570,100),fill=(20,20,20),width=1)
        draw.line((30,200,570,200),fill=(160,40,45),width=3)
        draw.line((30,300,570,300),fill=(35,50,160),width=3)
        result=process_scan_image(image,None,'sharp')
        self.assertEqual(result.size,image.size)
        self.assertGreater(min(result.getpixel((400,400))),248)
        self.assertLess(max(result.getpixel((300,100))),50)
        red=result.getpixel((300,200));blue=result.getpixel((300,300))
        self.assertGreater(red[0],red[1]+60)
        self.assertGreater(blue[2],blue[0]+60)

    def test_strengthens_blurred_edge_without_widening_line_excessively(self):
        image=Image.new('RGB',(500,300),(220,220,220))
        ImageDraw.Draw(image).rectangle((200,40,205,260),fill=(55,55,55))
        image=image.filter(ImageFilter.GaussianBlur(.8))
        source=np.asarray(image)[:,:,0].astype(float)[150]
        result=np.asarray(process_scan_image(image,None,'sharp'))[:,:,0].astype(float)[150]
        self.assertGreater(np.max(np.abs(np.diff(result))),np.max(np.abs(np.diff(source))))
        self.assertLessEqual(int((result<128).sum()),int((source<128).sum())+2)

    def test_does_not_amplify_blank_paper_noise(self):
        rng=np.random.default_rng(8)
        gray=np.clip(200+rng.normal(0,1.5,(300,400)),0,255).astype('uint8')
        image=Image.fromarray(np.repeat(gray[:,:,None],3,axis=2))
        result=np.asarray(process_scan_image(image,None,'sharp'))
        self.assertGreater(result.mean(),250)
        self.assertLess(result.std(),2)

    def test_keeps_broad_colored_fill_distinct_from_white_paper(self):
        image=Image.new('RGB',(600,500),(220,220,220))
        ImageDraw.Draw(image).rectangle((100,100,400,300),fill=(100,145,190))
        result=process_scan_image(image,None,'sharp')
        r,g,b=result.getpixel((250,200))
        self.assertGreater(b-r,50)
        self.assertLess(r,230)

    def test_geometry_preview_and_export_share_pipeline(self):
        image=Image.new('RGB',(300,200),(210,210,210));ImageDraw.Draw(image).line((30,100,270,100),fill=(80,80,80),width=2)
        with tempfile.TemporaryDirectory() as folder:
            service=ScanService(Path(folder));data=io.BytesIO();image.save(data,'PNG')
            scan_id=service.upload('notes.png',data.getvalue())['scanId'];options={'mode':'sharp','rotation':90,'crop':[.1,.1,.8,.8]}
            service.process(scan_id,options);preview=service.filter_preview(scan_id,options);export=service.export([scan_id],'png')
            with Image.open(Path(folder)/scan_id/'current.png') as full,Image.open(Path(folder)/scan_id/Path(preview['url']).name) as thumb,Image.open(Path(folder)/'exports'/Path(export['url']).name) as png:
                self.assertTrue(np.array_equal(np.asarray(full),np.asarray(png)))
                self.assertLess(np.abs(np.asarray(full).astype(float)-np.asarray(thumb.convert('RGB')).astype(float)).mean(),3)

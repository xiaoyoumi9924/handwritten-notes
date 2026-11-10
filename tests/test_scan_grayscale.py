import io
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from markdown_to_handwrite.scanner import ScanService, process_scan_image


class GrayscaleScanTests(unittest.TestCase):
    def test_preserves_gray_steps_and_faint_single_pixel_line(self):
        values=np.array([30,90,150,195,210,225,240,255],dtype=np.uint8)
        source=Image.fromarray(np.tile(values[None,:,None],(10,1,3)))
        result=np.asarray(process_scan_image(source,None,'grayscale'))
        self.assertTrue(np.array_equal(result,np.asarray(source)))
        image=Image.new('RGB',(200,140),(210,210,210))
        ImageDraw.Draw(image).line((20,70,180,70),fill=(195,195,195),width=1)
        result=process_scan_image(image,None,'grayscale')
        self.assertEqual(result.getpixel((100,70)),(195,195,195))
        self.assertEqual(result.getpixel((100,69)),(210,210,210))

    def test_color_conversion_shares_original_geometry(self):
        image=Image.new('RGB',(300,200),(210,190,180))
        d=ImageDraw.Draw(image);d.rectangle((40,40,100,100),fill=(170,30,30));d.line((20,140,280,140),fill=(20,35,160),width=3)
        options={'rotation':90,'crop':[.1,.1,.8,.8]}
        original=process_scan_image(image,None,'original',**options)
        result=process_scan_image(image,None,'grayscale',**options)
        self.assertTrue(np.array_equal(np.asarray(result),np.asarray(ImageOps.grayscale(original).convert('RGB'))))

    def test_preview_png_and_original_are_consistent(self):
        image=Image.new('RGB',(300,200),(195,210,220));ImageDraw.Draw(image).line((30,100,270,100),fill=(120,35,45),width=2)
        data=io.BytesIO();image.save(data,'PNG')
        with tempfile.TemporaryDirectory() as folder:
            service=ScanService(Path(folder));scan_id=service.upload('colors.png',data.getvalue())['scanId']
            original=(Path(folder)/scan_id/'original.png').read_bytes()
            service.process(scan_id,{'mode':'grayscale'});preview=service.filter_preview(scan_id,{'mode':'grayscale'});export=service.export([scan_id],'png')
            with Image.open(Path(folder)/scan_id/'current.png') as full,Image.open(Path(folder)/scan_id/Path(preview['url']).name) as thumb,Image.open(Path(folder)/'exports'/Path(export['url']).name) as png:
                pixels=np.asarray(full);self.assertTrue(np.array_equal(pixels[:,:,0],pixels[:,:,1]));self.assertTrue(np.array_equal(pixels[:,:,1],pixels[:,:,2]))
                self.assertTrue(np.array_equal(pixels,np.asarray(png)))
                self.assertLess(np.abs(pixels.astype(float)-np.asarray(thumb.convert('RGB')).astype(float)).mean(),3)
            self.assertEqual((Path(folder)/scan_id/'original.png').read_bytes(),original)

"""Synthetic visa only: fabricated identifiers, no personal data or real document."""
from pathlib import Path
from app.document_engine.models import OCRLine, OCRResult
from app.visa_engine.mrz import check_digit

VALUES=[('Visa number','TEST00001'),('Visa type','STUDENT'),('Entries','MULTIPLE'),
        ('Date of issue','2026-09-15'),('Valid from','2026-09-16'),('Valid until','2026-10-30'),
        ('Nationality','TKM'),('Passport number','DEMO00002')]

def mrz_rows(width=44):
    first=('V<UTO'+'SYNTHETIC<<DEMO<ONLY').ljust(width,'<')
    number='TEST00001';birth='000101';expiry='261030'
    second=number+check_digit(number)+'TKM'+birth+check_digit(birth)+'<'+expiry+check_digit(expiry)
    return first,second.ljust(width,'<')

def layout(include_mrz=True):
    lines=[OCRLine('SYNTHETIC VISA - TEST ONLY',.99,(50,20,1100,65))]
    for i,(label,value) in enumerate(VALUES):
        y=110+i*95
        lines.extend([OCRLine(label,.99,(60,y,430,y+34)),OCRLine(value,.99,(460,y,810,y+34))])
    if include_mrz:
        lines.extend(OCRLine(row,.99,(60,920+i*75,1560,965+i*75)) for i,row in enumerate(mrz_rows()))
    return lines

class SyntheticVisaProvider:
    def extract(self,path,context):
        if path.suffix=='.png': return OCRResult(layout())
        if path.suffix=='.jpg': return OCRResult([OCRLine('SYNTHETIC CERTIFICATE',.99,(0,0,800,40))])
        return OCRResult([],['ocr_images_only'])

def generate():
    from PIL import Image,ImageDraw,ImageFont
    folder=Path(__file__).resolve().parents[1]/'.document-lab/fixtures'
    folder.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(1750,1140),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(r'C:\Windows\Fonts\consola.ttf',34)
    mrz_font=ImageFont.truetype(r'C:\Windows\Fonts\consola.ttf',48)
    draw.text((60,20),'SYNTHETIC VISA - TEST ONLY - NOT A DOCUMENT',font=font,fill='black')
    for i,(label,value) in enumerate(VALUES):
        y=110+i*95
        draw.text((60,y),label,font=font,fill='black');draw.text((460,y),value,font=font,fill='black')
    for i,row in enumerate(mrz_rows()): draw.text((60,920+i*75),row,font=mrz_font,fill='black')
    path=folder/'synthetic-visa.png';image.save(path);return path

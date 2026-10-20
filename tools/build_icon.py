"""Render the shared vector brand into Windows multi-resolution ICO assets."""
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray,QBuffer,QIODevice,QPointF,Qt
from PySide6.QtGui import QImage,QPainter,QPolygonF,QColor

ROOT=Path(__file__).resolve().parents[1]
AMBER='#efae42'
DARK='#1b251e'
SHAPES=[[(42,4),(252,4),(214,252),(4,252)],
        [(99.5,64.5),(127.5,64.5),(108.5,191.5),(80.5,191.5)],
        [(147.5,64.5),(175.5,64.5),(156.5,191.5),(128.5,191.5)]]


def build():
    (ROOT/'dist').mkdir(exist_ok=True)
    svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
    for index,points in enumerate(SHAPES):
        color=AMBER if index==0 else DARK
        svg+=f'<polygon fill="{color}" points="'+ ' '.join(f'{x},{y}' for x,y in points)+'"/>'
    svg+='</svg>\n'
    (ROOT/'website/assets/brand.svg').write_text(svg,encoding='ascii')
    image=QImage(1024,1024,QImage.Format_ARGB32);image.fill(Qt.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(4,4);painter.setPen(Qt.NoPen)
    for index,points in enumerate(SHAPES):
        painter.setBrush(QColor(AMBER if index==0 else DARK))
        painter.drawPolygon(QPolygonF([QPointF(x,y) for x,y in points]))
    painter.end()
    frames=[]
    for size in [16,20,24,32,40,48,64,128,256]:
        pixels=image.scaled(size,size,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        encoded=QByteArray();buffer=QBuffer(encoded);buffer.open(QIODevice.WriteOnly)
        if not pixels.save(buffer,'PNG'):raise RuntimeError('Icon PNG encoding failed')
        frames.append((size,bytes(encoded)))
    offset=6+16*len(frames)
    entries=[]
    for size,data in frames:
        entries.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(data),offset))
        offset+=len(data)
    ico=struct.pack('<HHH',0,1,len(frames))+b''.join(entries)+b''.join(data for _,data in frames)
    for path in [ROOT/'launcher/assets/brand.ico',ROOT/'website/assets/brand.ico']:
        path.write_bytes(ico)
    image.scaled(256,256,Qt.KeepAspectRatio,Qt.SmoothTransformation).save(str(ROOT/'dist/brand-preview.png'))
    print('Shared brand: SVG and ICO with 9 sizes (16 to 256 px).')


if __name__=='__main__':build()

#!/usr/bin/env python3
"""生成 PowerWidget 应用图标:深色圆角背景 + 黄色闪电(SF Symbol bolt.fill)。
   输出 icon.icns 到当前目录。"""
import os
import sys
import subprocess

from AppKit import (
    NSImage, NSBitmapImageRep, NSColor,
    NSBezierPath, NSFont, NSFontAttributeName, NSForegroundColorAttributeName,
)
from Foundation import NSAttributedString, NSMakeRect

# 输出目录
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
ICONSET = os.path.join(OUT_DIR, 'icon.iconset')
ICNS = os.path.join(OUT_DIR, 'icon.icns')

os.makedirs(ICONSET, exist_ok=True)


def draw_icon(size):
    """画一张 size×size 的 PNG 数据。"""
    img = NSImage.alloc().initWithSize_((size, size))
    img.lockFocus()

    # 1. 深色圆角背景
    corner = size * 0.225  # macOS app icon 标准圆角约 22.5%
    bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(0, 0, size, size), corner, corner
    )
    # 渐变深色:左上深蓝紫 → 右下深绿,科技感
    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.14, 0.20, 1.0).set()
    bg_path.fill()

    # 2. 中心闪电 — 用 emoji ⚡(Apple Color Emoji 自带彩色高分辨率)
    bolt_str = '⚡'
    attrs = {
        NSFontAttributeName: NSFont.systemFontOfSize_(size * 0.7),
    }
    attr_str = NSAttributedString.alloc().initWithString_attributes_(bolt_str, attrs)
    ts = attr_str.size()
    x = (size - ts.width) / 2.0
    y = (size - ts.height) / 2.0
    attr_str.drawAtPoint_((x, y))

    img.unlockFocus()

    # 转 PNG
    tiff = img.TIFFRepresentation()
    rep = NSBitmapImageRep.imageRepWithData_(tiff)
    png = rep.representationUsingType_properties_(4, {})  # 4 = NSBitmapImageFileTypePNG
    return png


def save_png(data, path):
    data.writeToFile_atomically_(path, True)


# 各尺寸
SIZES = [
    (16, '16x16'),
    (32, '16x16@2x'),
    (32, '32x32'),
    (64, '32x32@2x'),
    (128, '128x128'),
    (256, '128x128@2x'),
    (256, '256x256'),
    (512, '256x256@2x'),
    (512, '512x512'),
    (1024, '512x512@2x'),
]

print('生成图标...')
for size, name in SIZES:
    data = draw_icon(size)
    path = os.path.join(ICONSET, f'icon_{name}.png')
    save_png(data, path)
    print(f'  {path}  ({size}x{size})')

# 用 iconutil 打成 icns
print('打包 .icns ...')
subprocess.run(['/usr/bin/iconutil', '-c', 'icns', ICONSET, '-o', ICNS], check=True)
print(f'完成: {ICNS}')

# 清理 iconset
import shutil
shutil.rmtree(ICONSET)
print('(已清理 iconset 临时文件)')

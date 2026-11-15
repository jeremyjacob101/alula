#!/usr/bin/env python3
"""Generate alula's macOS app icon assets from logo.png.

Writes the icon into the local Chromium checkout:

  src/chrome/app/theme/chromium/mac/app.icns
  src/chrome/app/theme/chromium/mac/Assets.car
  src/chrome/app/theme/chromium/mac/Assets.xcassets/AppIcon.appiconset/
  src/chrome/app/theme/chromium/mac/AppIcon.icon/

Requires Pillow, Xcode command line tools, and a local src/ checkout.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / 'src/chrome/app/theme/chromium/mac'
DEFAULT_SOURCE = Path(__file__).with_name('logo.png')
CANVAS = 1024
BODY = 824
MARGIN = (CANVAS - BODY) // 2
RADIUS = 185
ICON_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def source_image(path):
    image = Image.open(path).convert('RGBA')
    # The source has a faint light border baked into its outer pixels. Trim it
    # so the rounded icon edge does not pick up a thin outline.
    trim = 12
    image = image.crop((trim, trim, image.width - trim, image.height - trim))
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def full_bleed(image):
    """1024px artwork without rounded corners or margins, for Icon Composer."""
    return image.resize((CANVAS, CANVAS), Image.Resampling.LANCZOS)


def padded(image):
    """Legacy macOS icon: 824px rounded-square body on a 1024px transparent canvas."""
    canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))

    shadow = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.rounded_rectangle(
        (MARGIN, MARGIN + 10, MARGIN + BODY, MARGIN + BODY + 10),
        radius=RADIUS,
        fill=(0, 0, 0, 110),
    )
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))

    body = image.resize((BODY, BODY), Image.Resampling.LANCZOS)
    mask = Image.new('L', (BODY, BODY), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, BODY - 1, BODY - 1), radius=RADIUS, fill=255
    )
    canvas.paste(body, (MARGIN, MARGIN), mask)
    return canvas


def write_appiconset(image, catalog):
    appset = catalog / 'AppIcon.appiconset'
    shutil.rmtree(appset, ignore_errors=True)
    appset.mkdir(parents=True)
    catalog.mkdir(parents=True, exist_ok=True)
    (catalog / 'Contents.json').write_text(
        '{\n  "info" : {\n    "author" : "xcode",\n    "version" : 1\n  }\n}\n'
    )
    for size in ICON_SIZES:
        image.resize((size, size), Image.Resampling.LANCZOS).save(
            appset / f'appicon_{size}.png', optimize=True
        )
    (appset / 'Contents.json').write_text(
        '''{
  "images" : [
    { "filename" : "appicon_16.png", "idiom" : "mac", "scale" : "1x", "size" : "16x16" },
    { "filename" : "appicon_32.png", "idiom" : "mac", "scale" : "2x", "size" : "16x16" },
    { "filename" : "appicon_32.png", "idiom" : "mac", "scale" : "1x", "size" : "32x32" },
    { "filename" : "appicon_64.png", "idiom" : "mac", "scale" : "2x", "size" : "32x32" },
    { "filename" : "appicon_128.png", "idiom" : "mac", "scale" : "1x", "size" : "128x128" },
    { "filename" : "appicon_256.png", "idiom" : "mac", "scale" : "2x", "size" : "128x128" },
    { "filename" : "appicon_256.png", "idiom" : "mac", "scale" : "1x", "size" : "256x256" },
    { "filename" : "appicon_512.png", "idiom" : "mac", "scale" : "2x", "size" : "256x256" },
    { "filename" : "appicon_512.png", "idiom" : "mac", "scale" : "1x", "size" : "512x512" },
    { "filename" : "appicon_1024.png", "idiom" : "mac", "scale" : "2x", "size" : "512x512" }
  ],
  "info" : { "author" : "xcode", "version" : 1 }
}
'''
    )


def write_icon_composer(image):
    icon = THEME / 'AppIcon.icon'
    shutil.rmtree(icon, ignore_errors=True)
    (icon / 'Assets').mkdir(parents=True)
    image.save(icon / 'Assets' / 'logo.png', optimize=True)
    (icon / 'icon.json').write_text(
        '''{
  "fill" : {
    "solid" : "extended-gray:0.03922,1.00000"
  },
  "groups" : [
    {
      "layers" : [
        {
          "image-name" : "logo.png",
          "name" : "logo"
        }
      ]
    }
  ],
  "supported-platforms" : {
    "squares" : "shared"
  }
}
'''
    )


def write_icns(image):
    with tempfile.TemporaryDirectory(prefix='alula-iconset-') as temp:
        iconset = Path(temp) / 'alula.iconset'
        iconset.mkdir()
        names = {
            16: ('icon_16x16.png',),
            32: ('icon_16x16@2x.png', 'icon_32x32.png'),
            64: ('icon_32x32@2x.png',),
            128: ('icon_128x128.png',),
            256: ('icon_128x128@2x.png', 'icon_256x256.png'),
            512: ('icon_256x256@2x.png', 'icon_512x512.png'),
            1024: ('icon_512x512@2x.png',),
        }
        for size, filenames in names.items():
            resized = image.resize((size, size), Image.Resampling.LANCZOS)
            for filename in filenames:
                resized.save(iconset / filename, optimize=True)
        subprocess.run(
            ['iconutil', '-c', 'icns', '-o', str(THEME / 'app.icns'), str(iconset)],
            check=True,
        )


def compile_car():
    catalog = THEME / 'Assets.xcassets'
    subprocess.run(
        [
            sys.executable,
            str(ROOT / 'src/tools/mac/icons/compile_car.py'),
            str(catalog),
        ],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', type=Path, default=DEFAULT_SOURCE,
                        help='square source image (default: alula/icons/logo.png)')
    parser.add_argument('--skip-car', action='store_true',
                        help='write the catalog and .icon without compiling Assets.car')
    args = parser.parse_args()

    if not THEME.is_dir():
        raise SystemExit(f'Chromium theme directory not found: {THEME}')

    image = source_image(args.source)
    legacy = padded(image)
    full = full_bleed(image)

    write_appiconset(legacy, THEME / 'Assets.xcassets')
    write_icon_composer(full)
    if not args.skip_car:
        compile_car()
    write_icns(legacy)
    print(f'Wrote alula macOS icon assets to {THEME}')


if __name__ == '__main__':
    main()

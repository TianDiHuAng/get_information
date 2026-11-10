from PIL import Image

for name in ("01", "03", "10"):
    im = Image.open(f"data/xhs/cards/editorial/{name}.png").convert("RGB")
    w, h = im.size
    print(f"{name}: {w}x{h}  corner={im.getpixel((10, 10))}  center={im.getpixel((w//2, h//2))}  "
          f"midleft={im.getpixel((100, 500))}")

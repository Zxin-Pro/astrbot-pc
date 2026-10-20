from PIL import Image
im = Image.open(r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\light\dashboard.png")
box = (0, 740, 250, 900)
crop = im.crop(box).resize((250*3, 160*3), Image.LANCZOS)
crop.save(r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\crop_sidefoot.png")
print("ok", crop.size)

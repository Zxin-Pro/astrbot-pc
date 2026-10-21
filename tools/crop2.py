from PIL import Image
im = Image.open(r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\shell_window.png")
crop = im.crop((1080, 0, 1344, 46)).resize((264*3, 46*3), Image.LANCZOS)
crop.save(r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\crop_titlebar.png")
print("ok")

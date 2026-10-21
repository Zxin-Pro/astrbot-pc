from PIL import Image
base = r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots"
ims = [Image.open(rf"{base}\light\light\{n}.png") for n in ("instances", "backups")]
s = 0.78
ims = [i.resize((int(i.width*s), int(i.height*s)), Image.LANCZOS) for i in ims]
w = max(i.width for i in ims); h = sum(i.height for i in ims)
c = Image.new("RGB", (w, h), "white"); y = 0
for i in ims:
    c.paste(i, (0, y)); y += i.height
c.save(rf"{base}\m2.png"); print(c.size)

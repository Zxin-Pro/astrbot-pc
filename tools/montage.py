from PIL import Image
base = r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots"
def montage(names, out, scale=0.72):
    ims = [Image.open(rf"{base}\{n}") for n in names]
    ims = [i.resize((int(i.width*scale), int(i.height*scale)), Image.LANCZOS) for i in ims]
    w = max(i.width for i in ims)
    h = sum(i.height for i in ims)
    canvas = Image.new("RGB", (w, h), "white")
    y = 0
    for i in ims:
        canvas.paste(i, (0, y)); y += i.height
    canvas.save(out)
    print(out, canvas.size)
montage([r"light\instances.png", r"light\backups.png"], rf"{base}\m_inst_back.png")

#!/usr/bin/env python
"""正式定妆照(新规范):每角色 3 格独立生成(面部特写胸像/全身正面/全身3/4侧背),
PIL 拼接:左 40% 特写 + 右 60% 双列全身,渐变灰底,细黑分割线。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7601404577615805307"
IM = f"workspace/{PID}/gen/images"
FRAMING = "本图为原创神话题材短剧的角色定妆素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
BASE = ("电影写真风格,超写实,photorealistic,8K超高清画质,电影质感,古装正剧风格;"
        "摄影棚定妆照,整图背景为渐变灰色,柔和均匀影棚柔光,干净光影,立体感强,画面清晰锐利;"
        "固定机位。人物的长相、服装、配饰必须与参考图完全一致,同一人物同一服装同一光影。"
        "画面不带任何文字、水印。")

CHARS = {
    "niumowang": (f"{IM}/cast_niumowang.png",
        "牛魔王:电影级CG特效牛头人身大佬,深棕牛头粗壮弯角,金鼻环,黑色高定西装白衬衫粗金链",
        "威严慑人,不怒自威,眼神像审视猎物"),
    "tangseng": (f"{IM}/cast_tangseng_v2.png",
        "唐僧:清瘦俊朗光头高僧,金丝圆框墨镜,白色立领高定中山装三件套,肩搭金红锦襕披巾,腕缠佛珠",
        "冷峻矜贵,古井无波,谈判桌上从不输的人"),
    "shaseng": (f"{IM}/cast_shaseng_v2.png",
        "沙僧:两米魁梧壮汉,低马尾整齐络腮胡,藏青双排扣高定西装黑领带,胸挂大颗深色念珠,银戒",
        "沉默压场,眼神冷得像刀,生人勿近"),
    "bailongma": (f"{IM}/cast_bailongma_ba.png",
        "白龙马:电影级CG特效马头人身,雪白马脸,额前珍珠白鹿枝龙角,银白长鬃高马尾,白色立领修身长衫劲装银带黑靴,龙珠吊坠",
        "冷傲挺拔,像一柄出鞘的剑"),
}
PANELS = {
    "p1": ("面部大特写胸像(头部与肩部占满画面),微俯visage正对镜头", "3:4"),
    "p2": ("全身正面站姿全景,从头到脚完整入画,站姿挺拔气场全开", "9:16"),
    "p3": ("全身四分之三侧后角度全景,从头到脚完整入画,可见服装侧背剪裁与发型背面", "9:16"),
}

async def gen_all():
    for cid, (ref, ident, mood) in CHARS.items():
        for pk, (shot, ar) in PANELS.items():
            name = f"sheet_{cid}_{pk}"
            if Path(f"{IM}/{name}.png").is_file():
                print("SKIP", name, flush=True)
                continue
            prompt = f"{FRAMING}{shot};{ident};神态:{mood}。{BASE}"
            try:
                await images.generate(prompt, project_id=PID, refs=[ref],
                                      aspect=ar, quality="2k", name=name)
                print("OK", name, flush=True)
            except Exception as e:
                print(f"FAIL {name}: {str(e)[:100]}", flush=True)

def stitch():
    from PIL import Image
    H = 1920
    W = 1620
    wl = int(W * 0.4)
    wr = (W - wl) // 2
    line = 4
    for cid in CHARS:
        cells = []
        for pk, cw in [("p1", wl), ("p2", wr), ("p3", wr)]:
            p = Path(f"{IM}/sheet_{cid}_{pk}.png")
            if not p.is_file():
                print("MISS", p, flush=True)
                break
            im = Image.open(p).convert("RGB")
            s = max(cw / im.width, H / im.height)
            im = im.resize((round(im.width * s), round(im.height * s)))
            x = (im.width - cw) // 2
            y = (im.height - H) // 2
            cells.append(im.crop((x, y, x + cw, y + H)))
        else:
            canvas = Image.new("RGB", (W + line * 2, H), (10, 10, 10))
            canvas.paste(cells[0], (0, 0))
            canvas.paste(cells[1], (wl + line, 0))
            canvas.paste(cells[2], (wl + line + wr + line, 0))
            out = f"{IM}/dingzhuang_{cid}.png"
            canvas.save(out)
            print("STITCHED", out, flush=True)

asyncio.run(gen_all())
stitch()
print("R7-SHEETS-DONE", flush=True)

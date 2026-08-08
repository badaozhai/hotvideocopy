#!/usr/bin/env python
"""remake2 首帧重绘:原首帧构图 + 角色定妆参考 → gpt-image-2,串行可续跑。"""
import asyncio, json, re, sys
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7377380038250958121"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
R2 = f"{WS}/remake2"
SP = "/private/tmp/claude-501/-Users-suifei-works-hotvideocopy/b362c3f4-3764-4d87-a046-feaccc127248/scratchpad"

shots = json.loads(Path(f"{R2}/shots.json").read_text())["shots"]
specs = {r["id"]: r for r in json.loads(Path(f"{SP}/r2_specs.json").read_text())}
# 首帧名册(视觉代理产出) > charmap.json 人工覆盖 > 整镜名册兜底
ffr = {}
fp = Path(f"{R2}/ff_roster.json")
if fp.is_file():
    ffr = {r["id"]: r["ff_roster"] for r in json.loads(fp.read_text())}
charmap = {}
cp = Path(f"{R2}/charmap.json")
if cp.is_file():
    charmap = json.loads(cp.read_text())

FRAMING = "本图为影视同人致敬作品的分镜素材,复刻经典功夫电影《精武门》名场面,仅用于影视美术参考,无任何政治倾向。"
SHEET = {"A": ("hw_heroA.png", "黑衣武者(极短寸头,年轻硬朗)"),
         "B": ("hw_villainB2.png", "墨绿军装军官(极短寸头,方阔脸,约45岁沧桑面容)"),
         "C": ("hw_youngC.png", "紫衫青年(年轻,黑发)")}

def s0_desc(sp):
    """从整镜 action 里抽 s0 子句 = 首帧时刻的字面描述;抽不到退回 scene。"""
    act = sp.get("action", "")
    m = re.split(r"[;；]\s*s1[:：]?\s*", act)
    if m and m[0].strip():
        return re.sub(r"^s0[:：]?\s*", "", m[0].strip())
    return sp.get("scene", "")
LOCK = ("【本图第一优先级要求】画面中大匾上的文字必须与最后一张参考图(匾额道具定妆图)逐字完全一致:"
        "竖排繁体毛笔字「東亞病夫」四个字,字迹为浓黑饱满的毛笔书法,清晰可读。这是原电影剧情里日方送来羞辱中国武馆的匾额,"
        "主角随后将它砸碎以表民族自强——字样必须原样呈现,不得替换、增删。若不是这四字即为废图。")
STYLE = ("好莱坞动作大片质感:真人实拍级写实,变形宽银幕电影感,戏剧性轮廓光,深沉暗金色调,细节丰富。"
         "铁律:第一张参考图(原片)只提供构图/姿态/机位,画面中所有人物的脸和形象必须完全采用"
         "对应角色定妆参考图的原创角色,严禁保留原片演员的长相——原片演员的脸一旦出现即为废片。"
         "画面人物数量必须与描述完全一致,不得增减。")

async def main():
    for sh in shots:
        sid = sh["id"]
        out = Path(IM) / f"r2k_{sid}.png"
        if out.is_file():
            continue
        sp = specs.get(sid)
        if sp is None:
            print(f"SKIP {sid}(无spec)", flush=True)
            continue
        refs = [sh["first_frame"]]
        parts = [FRAMING]
        blob = sp.get("scene", "") + sp.get("action", "") + sp.get("overlay_text", "")
        plaque = "病夫" in blob
        if plaque:
            parts.append(LOCK)
        parts.append("以第一张参考图(原片画面)为构图基准,严格 1:1 复刻同一画面:"
                     "景别、机位、人物的左右位置与朝向都必须与第一张图完全一致,严禁水平镜像翻转。")
        parts.append(f"此帧画面(镜头起始瞬间):{s0_desc(sp)}。只画这一瞬间,不要画镜头后续发生的事。")
        # 名册优先级: charmap 人工覆盖 > 首帧名册 > 整镜名册
        if sid in charmap:
            cast = charmap[sid]
        elif sid in ffr:
            cast = ffr[sid]
        else:
            cast = sp.get("roster", [])
        for cid in cast:
            if cid in SHEET:
                sheet, label = SHEET[cid]
                path = f"{IM}/{sheet}"
                if path not in refs:
                    refs.append(path)
                parts.append(f"{label}(形象=第{refs.index(path)+1}张参考图的原创角色)在画面中,姿态与原片一致。")
        if not cast:
            parts.append("第一张参考图中没有人物,重绘结果中也绝对不能出现任何人物、人影或人形轮廓,保持空场景。")
        else:
            parts.append("角色定妆参考图仅定义人物外观,其画面内容、背景、构图一律不得带入结果。"
                         "人物数量与站位必须与第一张参考图完全一致——第一张图里有几个人,"
                         "结果里就只能有几个人,严禁新增任何人物。")
        if sp.get("overlay_text"):
            parts.append(f"保留画面底部字幕文字:「{sp['overlay_text']}」。")
        if plaque:
            refs.append(f"{IM}/hw_plaque3.png")
            parts.append(f"最后一张(第{len(refs)}张)参考图是匾额道具定妆图,匾面文字以它为唯一标准。")
        parts.append(STYLE)
        try:
            await images.generate("".join(parts), project_id=PID, refs=refs,
                                  aspect="16:9", quality="2k", name=f"r2k_{sid}")
            print(f"OK {sid}", flush=True)
        except Exception as e:
            print(f"FAIL {sid}: {str(e)[:100]}", flush=True)

asyncio.run(main())

#!/usr/bin/env python
"""r4(悟空八戒版)首帧重绘:原片构图 + 角色换皮(寸头男→孙悟空,花衬衫男→猪八戒)。"""
import asyncio, json, re, sys
from pathlib import Path

sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7410349447718161701"
WS = f"workspace/{PID}"
IM = f"{WS}/gen/images"
SP = "/private/tmp/claude-501/-Users-suifei-works-hotvideocopy/b362c3f4-3764-4d87-a046-feaccc127248/scratchpad"

shots = json.loads(Path(f"{WS}/seg/shots.json").read_text())["shots"]
specs = {r["id"]: r for r in json.loads(Path(f"{SP}/r3_specs.json").read_text())}

FRAMING = "本图为原创神话题材搞笑短剧的分镜素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
SHEET = {"M1": ("cast_wukong.png", "孙悟空(金棕猴脸,金紧箍,鹅黄僧衣+虎皮围裙,黑腕表,红色手机)"),
         "M2": ("cast_bajie.png", "猪八戒(粉灰猪头,大耳长吻,藏青僧衣敞怀露肚,大念珠)")}
FF_CAST = {"shot_000": ["M1"], "shot_001": ["M2"], "shot_002": ["M1"], "shot_003": ["M2"],
           "shot_004": ["M1"], "shot_005": ["M2"], "shot_006": ["M1"], "shot_007": ["M2"],
           "shot_008": ["M1"], "shot_009": ["M2"], "shot_010": ["M1"], "shot_011": ["M2"],
           "shot_012": ["M1"]}
OTS = {"shot_001", "shot_003", "shot_005", "shot_007", "shot_009", "shot_011"}

def s0_desc(sp):
    act = sp.get("action", "")
    m = re.split(r"[;；]\s*s1[:：]?\s*", act)
    if m and m[0].strip():
        return re.sub(r"^s0[:：]?\s*", "", m[0].strip())
    return sp.get("scene", "")

STYLE = ("魔幻现实混搭质感:夜市大排档实拍场景,霓虹光斑虚化背景,浅景深;角色是电影级 CG 特效"
         "神话人物,与实拍环境自然融合(如真人电影中的 CG 角色)。"
         "铁律:第一张参考图(原片)只提供构图/姿态/机位/景别;画面中的人物一律替换为对应的"
         "神话角色,严禁保留原片人类演员的长相。画面人物数量必须与描述完全一致,不得增减。"
         "画面不带任何字幕、花字、水印。")

async def main():
    for sh in shots:
        sid = sh["id"]
        out = Path(IM) / f"r4k_{sid}.png"
        if out.is_file():
            continue
        sp = specs.get(sid)
        refs = [sh["first_frame"]]
        parts = [FRAMING,
                 "以第一张参考图(原片画面)为构图基准,严格 1:1 复刻同一画面:"
                 "景别、机位、人物的左右位置/朝向/姿态都与第一张图一致,严禁水平镜像翻转。",
                 f"此帧画面(镜头起始瞬间,人物照此姿态但换成神话角色):{s0_desc(sp)}。"
                 "只画这一瞬间,不要画镜头后续发生的事。"]
        cast = FF_CAST[sid]
        for cid in cast:
            sheet, label = SHEET[cid]
            path = f"{IM}/{sheet}"
            if path not in refs:
                refs.append(path)
            role = "原片中的寸头男" if cid == "M1" else "原片中的花衬衫男"
            parts.append(f"{role}由{label}扮演,形象=第{refs.index(path)+1}张参考图,姿态表情对位原片。")
        if sid == "shot_007":
            parts.append("重要修正:画面中只有一双筷子且握在猪八戒手中,筷子结构完整不穿过身体或念珠;"
                         "不得出现任何悬空的多余筷子或竹签。")
        if sid in OTS:
            parts.append("画面前景一侧是对面孙悟空虚化失焦的肩背(鹅黄色僧衣),只见模糊轮廓不见脸,"
                         "作为过肩镜头的前景遮挡。")
        parts.append("角色定妆参考图仅定义人物外观,其画面内容、背景、构图一律不得带入结果。"
                     "第一张图里有几个人,结果里就只能有几个人,严禁新增任何人物。")
        parts.append(STYLE)
        try:
            await images.generate("".join(parts), project_id=PID, refs=refs,
                                  aspect="4:3", quality="2k", name=f"r4k_{sid}")
            print(f"OK {sid}", flush=True)
        except Exception as e:
            print(f"FAIL {sid}: {str(e)[:100]}", flush=True)

asyncio.run(main())

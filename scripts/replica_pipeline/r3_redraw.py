#!/usr/bin/env python
"""r3(夜市段子)首帧重绘:原首帧构图 + 定妆参考,s0子句法/镜像禁令/人数锁,可续跑。
OTS 反打镜(003/005/009/011)前景是 M1 虚化肩背——不进 refs,只文字描述,防 refs即名单。"""
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

FRAMING = "本图为原创搞笑短剧的分镜素材,实拍风格,仅用于影视美术参考。"
SHEET = {"M1": ("cast_M1.png", "寸头男(极短寸头,圆脸微胖,深墨绿衬衫,黑色腕表,红色手机)"),
         "M2": ("cast_M2.png", "花衬衫男(黑色偏分短发,清瘦脸,黑底白印花开领衫内搭白T)")}
# 首帧名册:OTS 反打镜的 M1 只是前景虚化肩背,不给定妆 ref
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

STYLE = ("写实实拍质感:夜市大排档,霓虹光斑虚化背景,浅景深,自然肤质,抖音实拍段子的画面味道。"
         "铁律:第一张参考图(原片)只提供构图/姿态/机位,画面中人物的脸必须完全采用定妆参考图的"
         "原创角色,严禁保留原片演员的长相——原片演员的脸一旦出现即为废片。"
         "画面人物数量必须与描述完全一致,不得增减。画面不带任何字幕、花字、水印。")

async def main():
    for sh in shots:
        sid = sh["id"]
        out = Path(IM) / f"r3k_{sid}.png"
        if out.is_file():
            continue
        sp = specs.get(sid)
        refs = [sh["first_frame"]]
        parts = [FRAMING,
                 "以第一张参考图(原片画面)为构图基准,严格 1:1 复刻同一画面:"
                 "景别、机位、人物的左右位置与朝向都必须与第一张图完全一致,严禁水平镜像翻转。",
                 f"此帧画面(镜头起始瞬间):{s0_desc(sp)}。只画这一瞬间,不要画镜头后续发生的事。"]
        cast = FF_CAST[sid]
        for cid in cast:
            sheet, label = SHEET[cid]
            path = f"{IM}/{sheet}"
            if path not in refs:
                refs.append(path)
            parts.append(f"{label}=第{refs.index(path)+1}张参考图的原创角色,姿态表情与原片一致。")
        if sid in OTS:
            parts.append("画面前景一侧是对面寸头男虚化失焦的肩背(深墨绿衬衫),只见模糊轮廓不见脸,"
                         "作为过肩镜头的前景遮挡。")
        parts.append("角色定妆参考图仅定义人物外观,其画面内容、背景、构图一律不得带入结果。"
                     "第一张图里有几个人,结果里就只能有几个人,严禁新增任何人物。")
        parts.append(STYLE)
        try:
            await images.generate("".join(parts), project_id=PID, refs=refs,
                                  aspect="4:3", quality="2k", name=f"r3k_{sid}")
            print(f"OK {sid}", flush=True)
        except Exception as e:
            print(f"FAIL {sid}: {str(e)[:100]}", flush=True)

asyncio.run(main())

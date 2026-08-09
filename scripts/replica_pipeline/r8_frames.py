#!/usr/bin/env python
import asyncio, sys
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7548028834538589492"
IM = f"workspace/{PID}/gen/images"
FRAMING = "本图为原创神话题材短剧的分镜素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
POV = ("画面为第一人称视角(徒弟悟空的视角)的手持自拍式构图,轻微仰角,菩提老祖的脸与上半身"
       "占画面主体;背景是斜阳下的山林,金色光斑虚化,远处云雾缭绕。")
CG = ("photorealistic,电影质感,画面清晰锐利。角色定妆参考图仅定义人物外观,其背景构图一律"
      "不得带入。画面不带任何字幕、花字、水印。只画描述的这一瞬间。")
PT = f"{IM}/cast_puti.png"
WD = f"{IM}/cast_wukong_dao_v2.png"

SHOTS = {
    "r8k_s0": dict(refs=[PT], prompt=(
        POV + "菩提老祖(参考图:鹤发道髻,雪白长须,月白道袍)面对镜头正要开口,眼神慈和带笑意,"
        "一手持拂尘搭在臂弯;背景远处天空有一只白鹤展翅掠过(小,虚化)。")),
    "r8k_s1": dict(refs=[PT, WD], prompt=(
        POV + "画面下缘,悟空毛茸茸的金棕色猴手(第2张参考图的手,青灰道袍袖口)从镜头下方入画,"
        "双手抱拳向前拱手行礼;景深处菩提老祖(第1张参考图)含笑颔首看着镜头方向。"
        "注意:只出现两只毛手和袖口,不出现悟空的脸和身体。")),
    "r8k_s2": dict(refs=[PT], prompt=(
        POV + "菩提老祖(参考图)近景略偏四分之三角度,神情转为语重心长,一手抬起竖起手指点拨;"
        "背景林间有一只白鹿低头掠过(小,虚化)。")),
    "r8k_s3": dict(refs=[PT], prompt=(
        POV + "菩提老祖(参考图)大特写,脸占画面大半,目光深邃而温厚,像要把话说进人心里;"
        "白须在风里微动,背景全部虚化成金色光斑。")),
    "r8k_s4": dict(refs=[PT, WD], prompt=(
        POV + "画面下缘,悟空毛茸茸的金棕猴手(第2张参考图的手,青灰道袍袖口)再次从镜头下方入画"
        "深深抱拳;景深处菩提老祖(第1张参考图)抚着白须开怀而笑。只出现毛手,不出现悟空的脸。")),
}

async def main():
    for name, sp in SHOTS.items():
        if Path(f"{IM}/{name}.png").is_file():
            print("SKIP", name, flush=True)
            continue
        try:
            await images.generate(FRAMING + sp["prompt"] + CG, project_id=PID,
                                  refs=sp["refs"], aspect="9:16", quality="2k", name=name)
            print("OK", name, flush=True)
        except Exception as e:
            print(f"FAIL {name}: {str(e)[:100]}", flush=True)
    print("R8-FRAMES-DONE", flush=True)

asyncio.run(main())

#!/usr/bin/env python
import asyncio, sys
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7548028834538589492"
FRAMING = "本图为原创神话题材短剧的角色定妆素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
STYLE = ("与参考图完全相同的定妆照规格:深灰色摄影棚无缝背景,全身站姿,柔和均匀影棚柔光,"
         "干净光影,立体感强,电影级质感,photorealistic。画面不带任何文字、水印。")

async def main():
    await images.generate(
        FRAMING +
        "菩提老祖的定妆:仙风道骨的老年道家宗师(真人演员质感),鹤发童颜,雪白长须垂胸,"
        "白发绾成道髻插木簪,眉长及鬓,目光慈和而深邃;身穿月白色宽袖道袍,袖口衣缘绣浅金云纹,"
        "腰系丝绦,手持白色拂尘,足踏云头履;气质超然温厚,像会笑着点醒你的师父。",
        project_id=PID, refs=["assets/characters/wukong.png"],
        aspect="9:16", quality="2k", name="cast_puti")
    print("OK puti", flush=True)
    await images.generate(
        FRAMING +
        "孙悟空的道教弟子服定妆:与参考图完全相同的金棕猴脸、金色紧箍、毛发与神态(电影级 CG "
        "特效猴脸,身份不变),但服装换成道童弟子装——青灰色交领道袍,白色中衣,腰系青色布绦,"
        "白袜黑面云鞋,背后背一柄小木剑;头顶毛发拢成小道髻但金紧箍仍戴在额前;"
        "神态谦逊求学,眼里有火。",
        project_id=PID, refs=["assets/characters/wukong.png"],
        aspect="9:16", quality="2k", name="cast_wukong_dao")
    print("OK wukong_dao", flush=True)

asyncio.run(main())

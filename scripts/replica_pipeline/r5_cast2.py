#!/usr/bin/env python
import asyncio, sys
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "yt_R5OCCNIVwQ"
FRAMING = "本图为原创神话题材搞笑短剧的角色定妆素材,《西游记》与嫦娥传说为公版古典题材,角色为原创设计,仅用于影视美术参考。"
STYLE = ("与参考图完全相同的定妆照规格:深灰色摄影棚无缝背景,全身站姿,柔和影棚布光,"
         "电影级质感,photorealistic。画面不带任何文字、水印。")

async def main():
    await images.generate(
        FRAMING +
        "嫦娥的华贵定妆:绝美清冷的月宫仙子(真人演员质感,倾国倾城,妆容精致华美),"
        "高耸云鬓戴银月凤冠,额前银色月牙花钿,珍珠流苏步摇;身穿皇家规格的月白鎏银宫装大袖衫,"
        "云肩缀满珍珠,银线绣玉兔与月桂纹样,外罩薄如云雾的广袖纱衣,束高腰珍珠璎珞裙,"
        "裙摆如月华流泻拖地;通身珠光华贵,气质端庄仙气凛然。" + STYLE,
        project_id=PID, refs=["assets/characters/wukong.png"],
        aspect="9:16", quality="2k", name="cast_change_v2")
    print("OK change_v2", flush=True)
    await images.generate(
        FRAMING +
        "白龙马的拟人定妆:电影级 CG 特效马头人身角色。最重要特征:额前鬃发间清晰长着一对"
        "珍珠白色的小龙角(鹿角状分叉,约一掌长,莹润有光泽),这是他龙族身份的标志,必须明显可见。"
        "雪白马脸,清澈黑亮的大眼,银白色长鬃毛顺到肩后;人身高挑健硕,穿白色立领运动夹克配"
        "白色长裤,白色运动鞋,颈间一枚小龙珠吊坠。气质忠厚呆萌。与参考图同一套 CG 生物写实风格。" + STYLE,
        project_id=PID, refs=["assets/characters/wukong.png", "assets/characters/bajie.png"],
        aspect="9:16", quality="2k", name="cast_bailongma_v2")
    print("OK bailongma_v2", flush=True)

asyncio.run(main())

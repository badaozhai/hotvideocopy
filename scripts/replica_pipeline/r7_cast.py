#!/usr/bin/env python
import asyncio, sys
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7601404577615805307"
FRAMING = "本图为原创神话题材短剧的角色定妆素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
STYLE = ("与参考图完全相同的定妆照规格:深灰色摄影棚无缝背景,全身站姿,柔和影棚布光,"
         "电影级质感,photorealistic,电影级 CG 生物写实风格。画面不带任何文字、水印。")
REFS = ["assets/characters/wukong.png", "assets/characters/bajie.png"]

CAST = {
    "cast_niumowang": (
        "牛魔王的霸气大佬定妆:电影级 CG 特效牛头人身角色,体格魁梧如山,深棕色牛头,一对粗壮的"
        "弯曲牛角,鼻环金光,眼神威严慑人;身穿黑色高级定制西装,白衬衫敞开两颗扣,胸前粗金链,"
        "一手拿着墨镜,气场全开的黑道大佬风范,不怒自威。"),
    "cast_tangseng": (
        "唐僧的霸气定妆:眉目俊朗庄严的年轻高僧(真人演员质感),光头戴金色毗卢帽,身披金红锦襕"
        "袈裟(金线繁绣),内衬月白僧袍,手持九环金锡杖,立姿挺拔如松,目光沉静而有压迫感,"
        "宝相庄严中透着不容置疑的威严。"),
    "cast_shaseng": (
        "沙僧的霸气定妆:电影级 CG 质感的魁梧武僧,古铜色皮肤,浓密络腮胡与披肩长发微卷,眉骨"
        "深邃目光凶悍沉稳;身穿藏青色武僧劲装束腰,外披深褐坎肩,胸前挂一串大颗深色念珠,"
        "手持降妖宝杖(月牙铲),肌肉贲张,像一堵墙一样站着,生人勿近。"),
    "cast_bailongma_ba": (
        "白龙马的霸气定妆:电影级 CG 特效马头人身角色,雪白马脸线条冷峻,额前一对珍珠白鹿枝状"
        "龙角,银白长鬃束成高马尾;身穿白色立领修身长衫劲装,银色暗纹,腰束银带,黑色长靴,"
        "颈间龙珠吊坠;身形挺拔颀长,眼神冷傲,像一柄出鞘的剑。"),
}

async def main():
    for name, desc in CAST.items():
        from pathlib import Path
        if Path(f"workspace/{PID}/gen/images/{name}.png").is_file():
            print("SKIP", name, flush=True)
            continue
        try:
            await images.generate(FRAMING + desc + STYLE, project_id=PID,
                                  refs=REFS, aspect="9:16", quality="2k", name=name)
            print("OK", name, flush=True)
        except Exception as e:
            print(f"FAIL {name}: {str(e)[:100]}", flush=True)
    print("R7-CAST-DONE", flush=True)

asyncio.run(main())

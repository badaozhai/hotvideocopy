#!/usr/bin/env python
"""r7(牛魔王三句话)分镜首帧:8 镜,竖屏 9:16。场景锚+方位咒语统一。"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7601404577615805307"
IM = f"workspace/{PID}/gen/images"
FRAMING = "本图为原创神话题材短剧的分镜素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
SET = ("场景方位咒语(每帧一致):豪华中式厅堂,牛魔王坐画面右侧红木太师椅主位,身后金色云纹屏风"
       "与暖色宫灯,左手边红木茶几上一套紫砂茶具,地面深色地毯,暖金色电影布光,港片大佬会客厅氛围。")
CG = ("角色是电影级 CG 特效神话人物与真人演员同框,photorealistic,电影质感,画面清晰锐利。"
      "角色定妆参考图仅定义人物外观,其背景构图一律不得带入。描述里有几个人物,画面里就只能有"
      "几个人物,严禁增减。画面不带任何字幕、花字、水印。只画描述的这一瞬间。")

NW = f"{IM}/cast_niumowang.png"
TS = f"{IM}/cast_tangseng_v2.png"
SS = f"{IM}/cast_shaseng_v2.png"
BL = f"{IM}/cast_bailongma_ba.png"
WK = "assets/characters/wukong.png"
BJ = "assets/characters/bajie.png"

SHOTS = {
    "r7k_shot_000": dict(refs=[NW], prompt=(
        "中景微仰拍:牛魔王(参考图:深棕牛头弯角金鼻环,黑西装白衬衫金链)坐在主位太师椅上,"
        "身体微微前倾,一手搭扶手一手端着紫砂茶杯,目光扫向画面外的听众,正要开口的神态,威严从容。")),
    "r7k_shot_001": dict(refs=[WK, BJ, TS, SS, BL], prompt=(
        "全景正拍沙发区(主位反打机位,画面里没有牛魔王):师徒五人在长沙发一侧听讲——"
        "孙悟空(第1参考图)抱臂坐沙发左端眉头微皱;猪八戒(第2参考图)坐中间捧着一把瓜子;"
        "唐僧(第3参考图:白西装墨镜锦襕披巾)端坐右端双手交叠,古井无波;"
        "沙僧(第4参考图:藏青西装念珠)站在沙发后侧如保镖;白龙马(第5参考图:白劲装龙角)"
        "倚在沙发扶手边站立,神情冷傲。五人都看向画面外的主位方向。")),
    "r7k_shot_002": dict(refs=[NW], prompt=(
        "近景平拍:牛魔王(参考图)坐主位身体前倾,放下茶杯,竖起一根手指,神情郑重开讲,"
        "眼神锐利盯着画面外听众。")),
    "r7k_shot_003": dict(refs=[NW], prompt=(
        "四分之三侧面近景(换机位):牛魔王(参考图)坐主位,竖起两根手指,嘴角带一丝冷笑,"
        "另一只手搭在扶手上,金鼻环反着暖光。")),
    "r7k_shot_004": dict(refs=[NW], prompt=(
        "特写微仰拍:牛魔王(参考图)面部与胸口入画,一只拳头轻轻砸进另一只手掌,眼神燃起狠劲,"
        "讲到激动处的神态。")),
    "r7k_shot_005": dict(refs=[NW], prompt=(
        "近景平拍(正面机位):牛魔王(参考图)坐主位竖起三根手指,神情沉下来,语重心长的开场神态。")),
    "r7k_shot_006": dict(refs=[NW], prompt=(
        "特写:牛魔王(参考图)面部特写,目光柔和了一分但依旧威严,一只手指轻点茶几桌面,"
        "像在把话钉进桌子里。")),
    "r7k_shot_007": dict(refs=[NW], prompt=(
        "中景微仰拍(与第一镜同机位):牛魔王(参考图)讲完最后一个字,身体靠回椅背,"
        "端起紫砂茶杯送到嘴边,眼神深远,尘埃落定的气场。")),
}

async def main():
    for name, sp in SHOTS.items():
        if Path(f"{IM}/{name}.png").is_file():
            print("SKIP", name, flush=True)
            continue
        try:
            await images.generate(FRAMING + SET + sp["prompt"] + CG, project_id=PID,
                                  refs=sp["refs"], aspect="9:16", quality="2k", name=name)
            print("OK", name, flush=True)
        except Exception as e:
            print(f"FAIL {name}: {str(e)[:120]}", flush=True)
    print("R7-FRAMES-DONE", flush=True)

asyncio.run(main())

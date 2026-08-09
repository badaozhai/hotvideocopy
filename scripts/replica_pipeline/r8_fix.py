#!/usr/bin/env python
import asyncio, sys, time
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images, video as V

PID = "dy_7548028834538589492"
FRAMING = "本图为原创神话题材短剧的角色定妆素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"

async def main():
    # 悟空道童 v2:无紧箍,无兵器
    await images.generate(
        FRAMING +
        "孙悟空的道教弟子服定妆:与参考图完全相同的金棕猴脸、毛发与神态(电影级 CG 特效猴脸,"
        "身份不变),但此为他早年拜师求艺时期——额前没有金箍,不佩戴任何头饰,头顶毛发拢成"
        "小道髻插一根素木簪;身上不背不持任何兵器。服装为道童弟子装:青灰色交领道袍,白色中衣,"
        "腰系青色布绦,白袜黑面云鞋;双手自然下垂,神态谦逊求学,眼里有火。"
        "与参考图完全相同的定妆照规格:深灰色摄影棚无缝背景,全身站姿,柔和影棚柔光,"
        "photorealistic,电影级质感。画面不带任何文字、水印。",
        project_id=PID, refs=["assets/characters/wukong.png"],
        aspect="9:16", quality="2k", name="cast_wukong_dao_v2")
    print("OK wukong_dao_v2", flush=True)

    # 重庆话探针
    LINE = "悟空,你练的每一遍,都不白练"
    prompt = "; ".join([
        "最高优先级铁律:画面是第一人称视角(徒弟的视角)的手持自拍式近景特写:菩提老祖"
        "(鹤发童颜,白发道髻木簪,雪白长须,月白道袍,手持拂尘)面对镜头说话,像长辈对着镜头"
        "开导晚辈;他的脸占画面主要位置,轻微手持晃动感;背景是斜阳下的山林,光斑虚化。",
        "声音铁律(最重要):他说的是地道的中国重庆话(重庆方言,西南官话川渝片,重庆口音),"
        "类似重庆老茶馆里七十岁老先生摆龙门阵的腔调,嗓音苍老温厚带劲道,语速从容;"
        "绝对不能是粤语或广东话,绝对不能是标准普通话播音腔,绝不能是年轻人声音。",
        f'他用重庆话对着镜头说 says in Chongqing dialect (重庆话, southwestern Mandarin, '
        f'NOT Cantonese): "{LINE}"',
        f"台词铁律:台词内容必须逐字为「{LINE}」,用重庆话发音,一个字不得增删;除这句外不说其他话。"
        "口型与台词精确同步。",
        "人物形象与首帧完全一致,严禁变脸;严禁其他人入画",
        "photorealistic, cinematic, warm sunset forest light"])
    await V.start(prompt, project_id=PID,
                  image=f"workspace/{PID}/gen/images/cast_puti.png",
                  duration=6, aspect="16:9", resolution="1080p", name="r8_probe_cq0")
    t0 = time.time()
    while time.time() - t0 < 900:
        await asyncio.sleep(25)
        for j in V.jobs(PID):
            if j["name"] == "r8_probe_cq0":
                st = j.get("status")
                if st in ("done", "failed"):
                    print("PROBE", st.upper(), flush=True)
                    return
                try:
                    r = await V.get(j["request_id"])
                    if r.get("status") in ("done", "failed"):
                        print("PROBE", r.get("status").upper(), flush=True)
                        return
                except Exception:
                    pass
                break
    print("PROBE TIMEOUT", flush=True)

asyncio.run(main())

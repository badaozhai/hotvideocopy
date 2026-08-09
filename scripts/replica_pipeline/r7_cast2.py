#!/usr/bin/env python
import asyncio, sys
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

PID = "dy_7601404577615805307"
FRAMING = "本图为原创神话题材短剧的角色定妆素材,《西游记》为公版古典名著,角色为原创设计,仅用于影视美术参考。"
STYLE = ("与参考图完全相同的定妆照规格:深灰色摄影棚无缝背景,全身站姿,柔和影棚布光,"
         "电影级质感,photorealistic。画面不带任何文字、水印。")
REFS = ["workspace/dy_7601404577615805307/gen/images/cast_niumowang.png"]

CAST = {
    "cast_tangseng_v2": (
        "唐僧的社会人大佬定妆:清瘦俊朗的年轻高僧(真人演员质感),光头锃亮,眉目冷峻精致,"
        "戴一副金丝圆框墨镜;身穿白色立领高定中山装三件套,剪裁利落一尘不染,肩上随意搭一条"
        "金红锦襕纹披巾(袈裟化用),腕上缠深色佛珠,黑色亮面皮鞋;单手插兜而立,气场清冷"
        "矜贵,不怒自威,像谈判桌上从不输的人。与参考图同一套大佬风格。"),
    "cast_shaseng_v2": (
        "沙僧的社会人定妆:身高两米的魁梧壮汉(电影级 CG 质感),古铜色皮肤,长发梳成一丝不苟的"
        "低马尾,络腮胡修剪得整齐利落,眉骨深邃眼神冷得像刀;身穿藏青色高定双排扣西装,"
        "白衬衫黑领带,胸前挂标志性的大颗深色念珠,手上两枚银戒,黑色皮鞋;双手交叠站姿"
        "如保镖头子,沉默压场,精致又凶悍。与参考图同一套大佬风格。"),
}

async def main():
    for name, desc in CAST.items():
        try:
            await images.generate(FRAMING + desc + STYLE, project_id=PID,
                                  refs=REFS, aspect="9:16", quality="2k", name=name)
            print("OK", name, flush=True)
        except Exception as e:
            print(f"FAIL {name}: {str(e)[:100]}", flush=True)
    print("R7-CAST2-DONE", flush=True)

asyncio.run(main())

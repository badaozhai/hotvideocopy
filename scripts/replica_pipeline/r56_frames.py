#!/usr/bin/env python
"""r5(悟空救车)+r6(八戒天河泰坦尼克)分镜首帧批量生成。定妆已封版。"""
import asyncio, sys
sys.path.insert(0, "/Users/suifei/works/hotvideocopy/src")
import os
os.chdir("/Users/suifei/works/hotvideocopy")
from hotvideocopy import images

FRAMING = "本图为原创神话题材搞笑短剧的分镜素材,《西游记》与嫦娥传说为公版古典题材,角色为原创设计,仅用于影视美术参考。"
WK = "assets/characters/wukong.png"
BJ = "assets/characters/bajie.png"
CE = "workspace/yt_R5OCCNIVwQ/gen/images/cast_change_v2.png"
BL = "workspace/yt_R5OCCNIVwQ/gen/images/cast_bailongma_v2.png"

CG = ("角色是电影级 CG 特效神话人物,与写实环境自然融合(如真人电影中的 CG 角色),"
      "photorealistic。角色定妆参考图仅定义人物外观,其背景构图一律不得带入。"
      "描述里有几个人物,画面里就只能有几个人物,严禁增减。画面不带任何字幕、花字、水印。"
      "只画描述的这一瞬间,不要画后续发生的事。")

R6_ENV = ("场景:一艘原创设计的复古豪华巨型邮轮的船头甲板,巨轮航行在天河之上——水面是流动的"
          "星光银河,泛着银蓝色波光;天空是绚烂晚霞与璀璨星河交融,一轮皎洁明月高悬。"
          "复古缆绳与白色船艏栏杆。魔幻唯美电影感,晚霞金光洒在人物身上。")

R5_ENV = ("场景:白天阴天,高架高速公路应急车道旁,路边有白色护栏与蓝色路牌,远处群山。"
          "写实手机实拍质感。")
CAR = "一辆白色三厢教练车(车门上有红色'教练车'字样)"

SHOTS = {
    # ---- r6 泰坦尼克天河版 (project dy_7670154130531790757) ----
    "r6k_shot_000": dict(pid="dy_7670154130531790757", refs=[BJ, CE], prompt=(
        "中景仰拍,船头经典相拥姿势:猪八戒(第1张参考图:粉灰猪头,藏青僧衣敞怀,大念珠)站在"
        "嫦娥(第2张参考图:银凤冠月牙花钿,月白鎏银宫装华服)身后,双手扶着她的腰;嫦娥站在船艏"
        "栏杆前,双臂向两侧完全展开,广袖与裙摆迎风飞舞,两人都闭眼微笑陶醉迎风。" + R6_ENV)),
    "r6k_shot_001": dict(pid="dy_7670154130531790757", refs=[BJ, CE], prompt=(
        "中景侧拍船头:猪八戒(第1张参考图)双臂用力将嫦娥(第2张参考图,华服广袖)高高举过头顶,"
        "像举重物一样把她举向船舷外侧,嫦娥双手慌乱挥舞,表情惊愕;八戒表情憨笑用力。"
        "此为抛出前的瞬间。" + R6_ENV)),
    "r6k_shot_002": dict(pid="dy_7670154130531790757", refs=[CE], prompt=(
        "高角度俯拍船舷外:嫦娥(参考图:银凤冠月白华服)在半空中坠向星光河面,但她周身开始泛起"
        "银色月光流光,广袖展开如翼,裙摆拖出一道银色光尾,身体开始转向天上的明月方向。"
        "画面下缘可见白色船舷栏杆边缘。" + R6_ENV)),
    "r6k_shot_003": dict(pid="dy_7670154130531790757", refs=[BJ], prompt=(
        "中景仰拍船头:猪八戒(参考图:粉灰猪头,藏青僧衣,大念珠)独自站在船艏最前端,双臂向两侧"
        "完全张开如展翅,昂头畅快大笑,大耳朵与僧衣衣摆迎风飞舞,豪迈自在。天上明月旁有一道"
        "细细的银色流光划过(远景小元素)。" + R6_ENV)),
    # ---- r5 悟空救车版 (project yt_R5OCCNIVwQ) ----
    "r5k_shot_000": dict(pid="yt_R5OCCNIVwQ", refs=[BJ, BL, CE], prompt=(
        "全景:路边三人站着闲聊——猪八戒(第1张参考图)、白龙马(第2张参考图:马头人身白运动装"
        "珍珠白龙角)、嫦娥(第3张参考图:银凤冠月白华服)面对面站在应急车道上;"
        f"他们身后中远处,{CAR}正沿着下坡道无人驾驶地缓缓向后溜走,车门开着。"
        "三人还没察觉,气氛轻松。" + R5_ENV)),
    "r5k_shot_001": dict(pid="yt_R5OCCNIVwQ", refs=[CE], prompt=(
        "近景:嫦娥(参考图:银凤冠月牙花钿月白华服)猛然回头,瞪大眼睛惊恐尖叫,一手指向画面"
        "深处远方(那里隐约可见白色轿车正在溜走,虚化),广袖因急转甩起。" + R5_ENV)),
    "r5k_shot_002": dict(pid="yt_R5OCCNIVwQ", refs=[WK], prompt=(
        "全景跟拍背影:孙悟空(参考图:金棕猴脸,金紧箍,鹅黄僧衣虎皮围裙)在高速路上朝着远处"
        f"溜走的{CAR}全力狂奔,身体前倾大步冲刺,僧衣衣摆飞起。车在画面深处,车门开着。" + R5_ENV)),
    "r5k_shot_003": dict(pid="yt_R5OCCNIVwQ", refs=[WK], prompt=(
        f"中景侧拍:{CAR}仍在缓慢滑行,孙悟空(参考图)已追到车旁,双手扒住敞开的车窗窗框,"
        "单脚蹬地正要翻身跃入车窗,动作矫健像猴子攀树。" + R5_ENV)),
    "r5k_shot_004": dict(pid="yt_R5OCCNIVwQ", refs=[WK], prompt=(
        f"中景:{CAR}已稳稳停住,孙悟空(参考图)从驾驶座车窗探出头和一只手臂,咧嘴得意笑着"
        "朝画面外挥手报平安。" + R5_ENV)),
}

async def main():
    for name, sp in SHOTS.items():
        from pathlib import Path
        out = Path(f"workspace/{sp['pid']}/gen/images/{name}.png")
        if out.is_file():
            print(f"SKIP {name}", flush=True)
            continue
        try:
            await images.generate(FRAMING + sp["prompt"] + CG, project_id=sp["pid"],
                                  refs=sp["refs"], aspect="9:16", quality="2k", name=name)
            print(f"OK {name}", flush=True)
        except Exception as e:
            print(f"FAIL {name}: {str(e)[:120]}", flush=True)
    print("R56-FRAMES-DONE", flush=True)

asyncio.run(main())

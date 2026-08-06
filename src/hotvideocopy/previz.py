"""previz —— 轻量虚拟制片层:3D 场景做空间真值,AI 做最终渲染。

场景/道具/角色/相机全部存在于一个持续的三维空间(scene3d.json),每个镜头
只是这个空间里的一次取景。previz 渲染布局图(色块人偶+朝向箭头),供:
1. gpt-image 作结构参考 → 写实首帧(方位/站位/道具位置由几何投影保证)
2. 几何自检:视线是否指向对手、人物画面方位、走位瞬移——全部可计算,不靠肉眼

    .venv/bin/python -m hotvideocopy.previz workspace/<pid>/scene3d.json

scene3d.json:
{
  "canvas": [720, 1280],
  "set":   [ {"name":"driver_seat","min":[x,y,z],"max":[x,y,z],"color":[r,g,b],"label":"驾驶座"}, ... ],
  "actors": {"A": {"color":[220,60,60]}, "B": {"color":[60,170,90]}},
  "beats": [ {"id":"b02",
              "actors": {"A": {"pos":[x,y], "facing":[dx,dy], "pose":"stand|sit"}, ...},
              "camera": {"pos":[x,y,z], "look":[x,y,z], "fov": 55},
              "check":  {"eyeline": ["A","B"], "move_ok": ["A"]} }, ... ]
}
坐标:米制,z 向上。painter's algorithm 平涂渲染,previz 不求好看,只求几何准确。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

UP = (0.0, 0.0, 1.0)
LIGHT = (0.35, -0.5, 0.79)


def _v(a, b):  return (b[0]-a[0], b[1]-a[1], b[2]-a[2])
def _dot(a, b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _norm(a):
    l = math.sqrt(_dot(a, a)) or 1.0
    return (a[0]/l, a[1]/l, a[2]/l)


class Camera:
    def __init__(self, pos, look, fov, w, h):
        self.pos, self.w, self.h = pos, w, h
        self.f = 1.0 / math.tan(math.radians(fov) / 2)
        self.fwd = _norm(_v(pos, look))
        self.right = _norm(_cross(self.fwd, UP))
        self.up = _cross(self.right, self.fwd)
        self.aspect = w / h

    def project(self, p):
        d = _v(self.pos, p)
        z = _dot(d, self.fwd)
        if z < 0.15:
            return None
        x = _dot(d, self.right) * self.f / z / self.aspect
        y = _dot(d, self.up) * self.f / z
        return ((x*0.5+0.5)*self.w, (1-(y*0.5+0.5))*self.h, z)


def box_faces(mn, mx):
    x0, y0, z0 = mn; x1, y1, z1 = mx
    c = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    idx = [(0,1,2,3,(0,0,-1)),(4,5,6,7,(0,0,1)),(0,1,5,4,(0,-1,0)),(2,3,7,6,(0,1,0)),(1,2,6,5,(1,0,0)),(0,3,7,4,(-1,0,0))]
    return [([c[a],c[b],c[d],c[e]], n) for a,b,d,e,n in idx]


def actor_boxes(spec):
    x, y = spec["pos"]
    sit = spec.get("pose") == "sit"
    zb = 0.45 if sit else 0.0
    zt = 1.25 if sit else 1.45
    boxes = [((x-0.22, y-0.14, zb), (x+0.22, y+0.14, zt)),          # 躯干
             ((x-0.11, y-0.11, zt), (x+0.11, y+0.11, zt+0.26))]    # 头
    return boxes


def render_beat(scene, beat, out_path):
    W, H = scene.get("canvas", [720, 1280])
    cam = Camera(beat["camera"]["pos"], beat["camera"]["look"], beat["camera"].get("fov", 55), W, H)
    img = Image.new("RGB", (W, H), (24, 26, 30))
    drw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 26)
    except OSError:
        font = ImageFont.load_default()

    # 地面网格
    for gx in range(0, 11):
        seg = [(gx*0.5, gy*0.5, 0.0) for gy in range(0, 41)]
        pts = [cam.project(p) for p in seg]
        pts = [(p[0], p[1]) for p in pts if p]
        if len(pts) > 1:
            drw.line(pts, fill=(45, 48, 55), width=1)

    faces = []   # (depth, poly2d, color, edge)
    labels = []  # (pt2d, text, color)

    for b in scene.get("set", []):
        col = tuple(b.get("color", [110, 115, 125]))
        for poly, n in box_faces(b["min"], b["max"]):
            pts = [cam.project(p) for p in poly]
            if any(p is None for p in pts):
                continue
            depth = sum(p[2] for p in pts) / 4
            sh = 0.55 + 0.45 * max(0.0, _dot(n, LIGHT))
            faces.append((depth, [(p[0], p[1]) for p in pts], tuple(int(c*sh) for c in col), (20, 20, 20)))
        if b.get("label"):
            top = ((b["min"][0]+b["max"][0])/2, (b["min"][1]+b["max"][1])/2, b["max"][2]+0.12)
            pt = cam.project(top)
            if pt:
                labels.append(((pt[0], pt[1]), b["label"], (200, 200, 210)))

    for aid, spec in (beat.get("actors") or {}).items():
        col = tuple(scene["actors"][aid]["color"])
        for mn, mx in actor_boxes(spec):
            for poly, n in box_faces(mn, mx):
                pts = [cam.project(p) for p in poly]
                if any(p is None for p in pts):
                    continue
                depth = sum(p[2] for p in pts) / 4
                sh = 0.6 + 0.4 * max(0.0, _dot(n, LIGHT))
                faces.append((depth, [(p[0], p[1]) for p in pts], tuple(int(c*sh) for c in col), None))
        # 朝向箭头(地面)
        x, y = spec["pos"]
        d = _norm((spec["facing"][0], spec["facing"][1], 0))
        tip = (x + d[0]*0.65, y + d[1]*0.65, 0.02)
        left = (x - d[1]*0.18, y + d[0]*0.18, 0.02)
        right = (x + d[1]*0.18, y - d[0]*0.18, 0.02)
        pts = [cam.project(p) for p in (tip, left, right)]
        if all(pts):
            depth = sum(p[2] for p in pts) / 3
            faces.append((depth, [(p[0], p[1]) for p in pts], col, (250, 250, 120)))
        hp = cam.project((x, y, (1.25 if spec.get("pose") == "sit" else 1.45) + 0.4))
        if hp:
            labels.append(((hp[0], hp[1]), aid, col))

    for depth, poly, col, edge in sorted(faces, key=lambda f: -f[0]):
        drw.polygon(poly, fill=col, outline=edge)
    for (px, py), text, col in labels:
        drw.text((px-10, py-16), text, font=font, fill=col)
    drw.text((14, 10), beat["id"], font=font, fill=(255, 230, 120))
    img.save(out_path, quality=90)


def check_beat(scene, beat, prev_actors):
    """几何自检:视线夹角 / 画面方位 / 瞬移。返回告警列表。"""
    warns = []
    W, H = scene.get("canvas", [720, 1280])
    cam = Camera(beat["camera"]["pos"], beat["camera"]["look"], beat["camera"].get("fov", 55), W, H)
    acts = beat.get("actors") or {}
    chk = beat.get("check") or {}

    for pair in chk.get("eyeline", []) if isinstance(chk.get("eyeline", [[]])[0], list) else [chk["eyeline"]] if chk.get("eyeline") else []:
        a, b = pair
        if a in acts and b in acts:
            fa = _norm((acts[a]["facing"][0], acts[a]["facing"][1], 0))
            to = _norm((acts[b]["pos"][0]-acts[a]["pos"][0], acts[b]["pos"][1]-acts[a]["pos"][1], 0))
            ang = math.degrees(math.acos(max(-1, min(1, _dot(fa, to)))))
            if ang > 45:
                warns.append(f"{beat['id']}: {a} 视线偏离 {b} {ang:.0f}°(>45°)")

    for aid, spec in acts.items():
        p = cam.project((spec["pos"][0], spec["pos"][1], 1.2))
        if p:
            third = "左" if p[0] < W/3 else ("右" if p[0] > 2*W/3 else "中")
            spec["_screen"] = third
        prev = prev_actors.get(aid)
        if prev:
            dist = math.dist(spec["pos"], prev["pos"])
            if dist > 0.6 and not spec.get("move") and not prev.get("move"):
                warns.append(f"{beat['id']}: {aid} 瞬移 {dist:.1f}m(前镜 {prev['pos']}→{spec['pos']},无 move 标记)")
        prev_actors[aid] = spec
    return warns


def main(path: str) -> int:
    scene = json.loads(Path(path).read_text(encoding="utf-8"))
    out_dir = Path(path).parent / "gen" / "previz"
    out_dir.mkdir(parents=True, exist_ok=True)
    prev_actors: dict = {}
    all_warns = []
    for beat in scene["beats"]:
        out = out_dir / f"{beat['id']}.png"
        render_beat(scene, beat, out)
        all_warns += check_beat(scene, beat, prev_actors)
        screens = {a: s.get("_screen", "?") for a, s in (beat.get("actors") or {}).items()}
        print(f"{beat['id']}: 渲染 → {out.name}  画面方位 {screens}")
    if all_warns:
        print(f"⚠️ 几何自检 {len(all_warns)} 条:")
        for w in all_warns:
            print("  -", w)
        return 1
    print("✅ 几何自检全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

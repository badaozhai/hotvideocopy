#!/usr/bin/env python
"""Submit and recover frame-aligned dance segments through the configured video edit API."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import mimetypes
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hotvideocopy import video as video_api  # noqa: E402
from hotvideocopy.config import CONFIG, auth_headers  # noqa: E402


PROJECT_ID = "dy_7671559890300685604"
PROJECT = ROOT / "workspace" / PROJECT_ID
WUKONG = ROOT / "assets" / "characters" / "wukong.png"
CHANGE = ROOT / "assets" / "characters" / "change.png"
WUKONG_BOARD = PROJECT / "references" / "wukong_identity_board.png"
CHANGE_BOARD = PROJECT / "references" / "change_identity_board.png"
SEGMENTS = [
    PROJECT / "motion_segments" / "pose_overlay_s00_f000_166.mp4",
    PROJECT / "motion_segments" / "pose_overlay_s01_f167_399.mp4",
    PROJECT / "motion_segments" / "pose_overlay_s02_f400_477.mp4",
]
HEADLESS_SEGMENTS = [
    PROJECT / "motion_segments" / "pose_headless_s00_f000_166.mp4",
    PROJECT / "motion_segments" / "pose_overlay_s01_f167_399.mp4",
    PROJECT / "motion_segments" / "pose_headless_s02_f400_477.mp4",
]
GREEN_HEADLESS_SEGMENTS = [
    PROJECT / "motion_segments" / "pose_green_assetcolor_s00_f000_166.mp4",
    PROJECT / "motion_segments" / "pose_green_assetcolor_s01_f167_399.mp4",
    PROJECT / "motion_segments" / "pose_green_assetcolor_s02_f400_477.mp4",
]
CLOSEUP_SEGMENT = (
    PROJECT
    / "motion_segments"
    / "pose_green_assetcolor_closeup_s01b_f362_399.mp4"
)
EXPECTED_FRAMES = (167, 233, 78)

IDENTITY_LOCK = (
    "两张身份参考板是角色外观的唯一标准，板内全身、脸部和服装特写均是同一个角色，绝不能理解成"
    "多个角色。男角色必须逐段保持同一位孙悟空：完整金棕色猴脸和猴耳、浅色口鼻、卷云形金箍、"
    "姜黄色交领衣、黄裤、棕金虎纹毛皮围裙、棕色腰带、毛茸前臂和小腿、赤脚；不得真人化，不得"
    "改成黑发人脸、黑斗篷或棕色长袍，不带手机、手表或其他现代物品。女角色必须逐段保持同一位"
    "嫦娥：参考板中的同一张脸、黑色盘发、巨大银色凤凰冠及两侧珍珠流苏、额心银色月牙、银白花饰"
    "肩甲、珍珠璎珞与腰饰、银白刺绣长裙、裙摆双白兔纹样和宽大水袖；不得变成牛角、鹿角、月牙双角"
    "或简化头冠；凤凰冠必须是银色金属与珍珠，不得生成黑色羽翼。嫦娥的脸、颈部、双手和手指都必须"
    "是参考图中的自然白皙肤色，绝不能被控制色染成红色、粉色，也不戴红手套。服装保持明亮月白与银色，"
    "不得变成深灰或黑色。裙摆两只白兔只是贴在布料上的小型平面刺绣纹样，不是活兔、立体兔头、玩偶或"
    "独立道具。不得换脸、换妆、换衣、改色。三段中脸、头饰、服装纹样、材质和身体比例完全一致。整体"
    "必须是写实真人电影画面，保留真实皮肤、毛发和织物纹理，不得变成游戏角色、三维动画或塑料模型。"
)
MOTION_LOCK = (
    "这是逐帧姿态驱动的视频编辑，不是重新编舞。输入视频中的红色素体是女角色嫦娥的动作控制轨，"
    "白色素体是男角色孙悟空的动作控制轨；素体覆盖标记只用于控制，成片中必须完全移除。逐帧严格"
    "贴合每个素体的头、肩、肘、腕、手指方向、髋、膝、踝、步法、重心和倒地姿态；人物出现时间、"
    "遮挡关系、景别、镜头运动、构图、背景、光线、原有剪辑和全部动作节拍保持输入不变。不得增删"
    "动作，不得改变速度，不得补动作，不得慢动作，不得改机位。"
)
GREEN_MOTION_LOCK = (
    "这是纯绿幕逐帧姿态驱动，不是重新编舞。绿色只代表待替换背景；银白色无头素体唯一对应女角色嫦娥，"
    "金黄色无头素体唯一对应男角色孙悟空。素体颜色只用于角色识别，不能作为裸露皮肤或控制标记保留。"
    "素体肩部上沿是颈部位置，模型需要补出自然头部，但不能改变"
    "身体姿态。逐帧严格贴合每个素体的肩、肘、腕、手臂方向、髋、膝、踝、步法、重心、人物尺度和倒地"
    "姿态；人物出现时间、遮挡关系、景别变化、原有切镜和全部动作节拍保持输入不变。不得增删动作，不得"
    "改变速度，不得补动作，不得慢动作，不得改机位。绿色、银白色和金黄色控制图形在成片中必须全部消失。"
)
SCENE_LOCK = (
    "把全部绿色背景替换为同一座广寒宫月桂庭院：银白玉石平台与月宫飞檐，远处巨大圆月，庭院一侧有"
    "月桂树，冷银蓝月光、少量暖色宫灯、轻薄月雾，写实电影质感。三段建筑布局、月亮位置、地面纹样、"
    "光线方向和色彩必须一致。不得出现原片的日落云海、山峰露台或现代场景。"
)
NEGATIVE_LOCK = (
    "画面中不得出现任何文字：不出现中文、英文、数字、字幕、歌词、角色名、片头、片尾、花字、标签、"
    "标志、平台图标或水印；也不得生成类似文字的笔画和符号。不保留绿幕、红白素体、关节点或骨架线；"
    "不增加人物或道具；角色不得变脸、变装、融合、换位或忽隐忽现。输出无新增对白和音乐，音轨将在"
    "本地使用原始 BGM 装配。"
)


def data_url(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-count_frames",
        "-show_entries", "stream=codec_type,width,height,r_frame_rate,nb_read_frames,duration",
        "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def preflight(
    index: int,
    segment: Path | None = None,
    references: list[Path] | None = None,
    expected_frames: int | None = None,
) -> dict:
    segment = segment or SEGMENTS[index]
    references = references or [WUKONG, CHANGE]
    if not segment.is_file() or any(not reference.is_file() for reference in references):
        raise FileNotFoundError("姿态控制片或角色参考图缺失")
    info = probe(segment)
    streams = info.get("streams") or []
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(video_streams) != 1 or audio_streams:
        raise RuntimeError(f"控制片流结构错误: {segment.name}")
    stream = video_streams[0]
    actual_frames = int(stream.get("nb_read_frames") or 0)
    expected_frames = expected_frames or EXPECTED_FRAMES[index]
    if actual_frames != expected_frames:
        raise RuntimeError(f"控制片帧数错误: {segment.name} {actual_frames} != {expected_frames}")
    if (stream.get("width"), stream.get("height"), stream.get("r_frame_rate")) != (1254, 720, "30/1"):
        raise RuntimeError(f"控制片规格错误: {segment.name} {stream}")
    return {
        "index": index,
        "path": str(segment),
        "frames": actual_frames,
        "fps": stream["r_frame_rate"],
        "width": stream["width"],
        "height": stream["height"],
        "duration": float(stream["duration"]),
        "audio": False,
        "sha256": sha256(segment),
    }


def write_preflight_manifest() -> Path:
    rows = [preflight(index) for index in range(len(SEGMENTS))]
    manifest = {
        "project_id": PROJECT_ID,
        "input_kind": "source frames with red female and white male pose overlays",
        "segments": rows,
        "total_frames": sum(row["frames"] for row in rows),
        "references": [
            {"role": "male", "target": "孙悟空", "path": str(WUKONG), "sha256": sha256(WUKONG)},
            {"role": "female", "target": "嫦娥", "path": str(CHANGE), "sha256": sha256(CHANGE)},
        ],
    }
    output = PROJECT / "qc" / "pose_submission_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def prompt_for(
    index: int,
    green_headless: bool = False,
    continuity: bool = False,
    closeup: bool = False,
) -> str:
    segment_note = {
        0: "本段女角色全程为嫦娥；后段从画面左侧出现的男角色必须是孙悟空。",
        1: "本段男角色为孙悟空，女角色为嫦娥；保留双人靠近、对望、手势碰拍及原片近景切换。",
        2: "本段男角色为孙悟空，女角色为嫦娥；保留嫦娥下探倒地和孙悟空站立收尾的完整动作。",
    }[index]
    if closeup:
        segment_note = (
            "本段严格对应原片第362至399帧的硬切近景，共38帧。金黄色大头肩轮廓是画面左侧前景的"
            "孙悟空，银白色小头肩轮廓是画面右后方的嫦娥；两人始终保留在当前近景位置，不得下沉、"
            "出画、互换、融合或改变远近遮挡。只复现输入里的轻微低头、抬眼、探身和嘴部运动，不新增"
            "肢体舞蹈。镜头、裁切、人物尺度和运动方向逐帧服从输入控制片。"
        )
    continuity_note = (
        "附加连续性参考帧来自上一段成片，只用于锁定同一组演员、服装、广寒宫布局和光线；当前动作与构图"
        "仍只服从输入控制视频。"
        if continuity else ""
    )
    motion = GREEN_MOTION_LOCK if green_headless else MOTION_LOCK
    return "\n".join(filter(None, (
        "最高优先级：", motion, IDENTITY_LOCK, SCENE_LOCK, continuity_note,
        segment_note, NEGATIVE_LOCK,
    )))


async def submit(
    index: int,
    include_references: bool,
    headless: bool = False,
    green_headless: bool = False,
    continuity_ref: Path | None = None,
    closeup: bool = False,
) -> dict:
    if closeup:
        if index != 1:
            raise ValueError("近景控制只适用于第1段")
        segment = CLOSEUP_SEGMENT
        references = [WUKONG_BOARD, CHANGE_BOARD]
        expected_frames = 38
    elif green_headless:
        segment = GREEN_HEADLESS_SEGMENTS[index]
        references = [WUKONG_BOARD, CHANGE_BOARD]
        expected_frames = EXPECTED_FRAMES[index]
    else:
        segment = HEADLESS_SEGMENTS[index] if headless else SEGMENTS[index]
        references = [WUKONG, CHANGE]
        expected_frames = EXPECTED_FRAMES[index]
    if continuity_ref:
        references.append(continuity_ref.resolve())
    segment_check = preflight(index, segment, references, expected_frames)
    variant = (
        "dance_green_guanghan_s01b_closeup" if closeup else
        "dance_green_guanghan" if green_headless else
        "dance_pose_headless" if headless else
        "dance_pose_edit"
    )
    version = "v7" if closeup else "v6" if green_headless else "v3" if headless else "v2"
    if closeup:
        name = f"{variant}_{version}" + ("_refs" if include_references else "_text")
    else:
        name = f"{variant}_s{index:02d}_{version}" + ("_refs" if include_references else "_text")
    body: dict = {
        "model": "grok-imagine-video",
        "prompt": prompt_for(index, green_headless or closeup, bool(continuity_ref), closeup),
        "video": {"url": data_url(segment)},
    }
    if include_references:
        body["reference_images"] = [
            {"image_url": data_url(reference)} for reference in references[:3]
        ]

    endpoint = video_api._endpoint("edits")
    key = video_api._key()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(180.0, read=300.0), proxy=CONFIG.proxy or None
    ) as client:
        response = await client.post(endpoint, headers=auth_headers(key), json=body)

    if response.status_code != 200:
        detail = response.text[:800].replace("\n", " ")
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    payload = response.json() or {}
    request_id = video_api.pick_request_id(payload)
    if not request_id:
        raise RuntimeError(f"编辑响应没有任务编号: {str(payload)[:300]}")

    job = video_api._upsert({
        "request_id": request_id,
        "project_id": PROJECT_ID,
        "kind": "edits",
        "name": name,
        "prompt": prompt_for(index, green_headless or closeup, bool(continuity_ref), closeup)[:200],
        "source_file": str(segment),
        "source_sha256": segment_check["sha256"],
        "source_frames": segment_check["frames"],
        "reference_images": [str(reference) for reference in references[:3]] if include_references else [],
        "status": "running",
        "ts": time.time(),
    })
    return {"request_id": request_id, "status": "running", "job": job}


async def poll(request_id: str) -> dict:
    return await video_api.get(request_id)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segment", type=int, choices=range(len(SEGMENTS)))
    parser.add_argument("--without-references", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--green-headless", action="store_true")
    parser.add_argument("--closeup", action="store_true")
    parser.add_argument("--continuity-ref", type=Path)
    parser.add_argument("--poll", metavar="REQUEST_ID")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()

    if args.preflight:
        result = {"status": "ready", "manifest": str(write_preflight_manifest())}
    elif args.poll:
        result = await poll(args.poll)
    elif args.segment is not None:
        if sum((args.headless, args.green_headless, args.closeup)) > 1:
            parser.error("--headless、--green-headless 与 --closeup 不能同时使用")
        result = await submit(
            args.segment,
            not args.without_references,
            args.headless,
            args.green_headless,
            args.continuity_ref,
            args.closeup,
        )
    else:
        parser.error("需要 --segment 或 --poll")
        return
    print({key: value for key, value in result.items() if key != "job"})


if __name__ == "__main__":
    asyncio.run(main())

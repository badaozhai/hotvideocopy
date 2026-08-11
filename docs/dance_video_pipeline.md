# 舞蹈视频制作管线

这组脚本用于把源片动作轨、角色资产和外部视频生成结果装配成最终视频。项目工作区固定为
`workspace/dy_7671559890300685604`，由仓库的 `.gitignore` 排除，不会把源片、角色上传材料、生成视频或本地模型提交进 Git。

## 当前成片

当前成片使用三个外部生成片段，按原视频帧钟装配为：

- `s00`: 167 帧
- `s01`: 233 帧
- `s02`: 78 帧
- 总计：478 帧，30fps，1254x720

输出文件为 `workspace/dy_7671559890300685604/final_wukong_change_dance_guanghan.mp4`，音频由本地重新铺回原始 BGM。

## 重新制作

先准备 `.env` 中的 Grok 网关 Key 和代理，然后按需要执行：

```bash
# 生成或修复两角色动作轨，并输出控制视频
.venv/bin/python scripts/dance_pose_extract.py

# 生成孙悟空、嫦娥身份参考板
.venv/bin/python scripts/dance_identity_boards.py

# 检查三个控制片的规格，不提交任务
.venv/bin/python scripts/dance_external_edit.py --preflight

# 按段提交绿幕控制片；返回的 request_id 用于轮询回收
.venv/bin/python scripts/dance_external_edit.py --segment 0 --green-headless
.venv/bin/python scripts/dance_external_edit.py --poll REQUEST_ID

# 三段结果下载到 gen/clips/ 后，装配原 BGM
.venv/bin/python scripts/dance_assemble.py

# 检查帧数、规格、文字/绿幕残留和音频一致性
.venv/bin/python scripts/dance_final_qc.py
```

`dance_external_edit.py` 会上传控制视频和角色参考图到已配置的外部视频服务。`--closeup` 是旧版近景补片的可选工具；当前成片不依赖它，默认装配使用完整的 `s01` 片段。

## 本地路线

本机模型不常驻硬盘。需要本地试验时运行：

```bash
.venv/bin/python scripts/dance_local_models.py --dry-run
.venv/bin/python scripts/dance_local_models.py
```

完成后可用 `dance_local_repaint.py`、`dance_local_face_refine.py` 和 `dance_local_face_swap.py` 做单帧验证；验证结束后可删除 `workspace/dy_7671559890300685604/local_models/`，下次再按安装脚本临时下载。

// hotvideocopy 工作区查看器——只读,不做任何编辑。
// 与 Python 版 webui 语义对齐:抽帧缓存文件名一致,两边共用 frames/ 缓存。
#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::UNIX_EPOCH;

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

const WEB_PORT: u16 = 8765;

/// 本地服务(hotvideocopy-web)子进程句柄
struct WebService(Mutex<Option<Child>>);

const JSON_FILES: [&str; 10] = [
    "meta", "shots", "transcript", "ocr", "dna",
    "script", "timeline", "storyboard", "scene3d", "motion",
];

// ─────────────────────────── 工作区定位与记忆 ───────────────────────────

fn config_file(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().app_config_dir().ok()?;
    fs::create_dir_all(&dir).ok()?;
    Some(dir.join("config.json"))
}

fn load_workspace(app: &AppHandle) -> Option<PathBuf> {
    let from_cfg = config_file(app)
        .and_then(|f| fs::read_to_string(f).ok())
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v["workspace"].as_str().map(PathBuf::from));
    let ws = from_cfg.or_else(|| std::env::var("HVC_WORKSPACE").ok().map(PathBuf::from))?;
    ws.is_dir().then_some(ws)
}

fn allow_media(app: &AppHandle, dir: &Path) {
    // asset 协议按需放行工作区目录,<video>/<img> 才能直接引用本地文件(带 Range,可拖进度条)
    let _ = app.asset_protocol_scope().allow_directory(dir, true);
}

fn workspace(app: &AppHandle) -> Result<PathBuf, String> {
    load_workspace(app).ok_or_else(|| "还没选择工作区".into())
}

/// pid → 项目目录,防路径穿越(canonicalize 后必须是工作区的直接子目录)
fn project_dir(app: &AppHandle, pid: &str) -> Result<PathBuf, String> {
    let ws = workspace(app)?.canonicalize().map_err(|e| e.to_string())?;
    let d = ws.join(pid).canonicalize().map_err(|_| format!("项目不存在:{pid}"))?;
    if !d.is_dir() || d.parent() != Some(ws.as_path()) {
        return Err(format!("项目不存在:{pid}"));
    }
    Ok(d)
}

fn read_json_value(path: &Path) -> Value {
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| json!({}))
}

fn list_files(dir: &Path, exts: &[&str]) -> Vec<String> {
    let Ok(rd) = fs::read_dir(dir) else { return vec![] };
    let mut out: Vec<String> = rd
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.is_file()
                && p.extension()
                    .and_then(|x| x.to_str())
                    .map(|x| exts.contains(&x.to_lowercase().as_str()))
                    .unwrap_or(false)
        })
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    out.sort();
    out
}

// ─────────────────────────── 命令 ───────────────────────────

#[tauri::command]
fn get_workspace(app: AppHandle) -> Option<String> {
    let ws = load_workspace(&app)?;
    allow_media(&app, &ws);
    Some(ws.to_string_lossy().into_owned())
}

#[tauri::command]
fn set_workspace(app: AppHandle, path: String) -> Result<String, String> {
    let dir = PathBuf::from(&path);
    if !dir.is_dir() {
        return Err(format!("不是目录:{path}"));
    }
    let f = config_file(&app).ok_or("无法定位配置目录")?;
    fs::write(&f, json!({ "workspace": path }).to_string()).map_err(|e| e.to_string())?;
    allow_media(&app, &dir);
    Ok(path)
}

#[tauri::command]
fn list_projects(app: AppHandle) -> Result<Vec<Value>, String> {
    let ws = workspace(&app)?;
    let mut items: Vec<Value> = vec![];
    for entry in fs::read_dir(&ws).map_err(|e| e.to_string())?.flatten() {
        let p = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        if !p.is_dir() || name.starts_with('.') {
            continue;
        }
        let meta = read_json_value(&p.join("meta.json"));
        let shots = read_json_value(&p.join("shots.json"));
        let mtime = entry
            .metadata()
            .ok()
            .and_then(|m| m.modified().ok())
            .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        items.push(json!({
            "id": name,
            "mtime": mtime,
            "title": meta["title"].as_str().or(meta["desc"].as_str()).unwrap_or(""),
            "duration": meta["duration"].as_f64().or(shots["duration"].as_f64()).unwrap_or(0.0),
            "shot_count": shots["shot_count"].as_u64().unwrap_or(0),
            "has_source": p.join("source.mp4").is_file(),
            "has_output": p.join("output.mp4").is_file(),
        }));
    }
    items.sort_by(|a, b| b["mtime"].as_f64().partial_cmp(&a["mtime"].as_f64()).unwrap());
    Ok(items)
}

#[tauri::command]
fn project_detail(app: AppHandle, pid: String) -> Result<Value, String> {
    let d = project_dir(&app, &pid)?;
    let json_files: Value = JSON_FILES
        .iter()
        .map(|n| ((*n).to_string(), Value::Bool(d.join(format!("{n}.json")).is_file())))
        .collect::<serde_json::Map<_, _>>()
        .into();
    let abs = |name: &str| -> Value {
        let f = d.join(name);
        if f.is_file() { json!(f.to_string_lossy()) } else { Value::Null }
    };
    Ok(json!({
        "id": pid,
        "dir": d.to_string_lossy(),
        "meta": read_json_value(&d.join("meta.json")),
        "shots": read_json_value(&d.join("shots.json")),
        "transcript": read_json_value(&d.join("transcript.json")),
        "ocr": read_json_value(&d.join("ocr.json")),
        "json_files": json_files,
        "source": abs("source.mp4"),
        "output": abs("output.mp4"),
        "gen_images": list_files(&d.join("gen").join("images"), &["png", "jpg", "jpeg", "webp"]),
        "gen_clips": list_files(&d.join("gen").join("clips"), &["mp4", "mov", "webm"]),
        "gen_tts": list_files(&d.join("gen").join("tts"), &["mp3", "wav", "m4a"]),
    }))
}

#[tauri::command]
fn read_project_json(app: AppHandle, pid: String, name: String) -> Result<String, String> {
    if !JSON_FILES.contains(&name.as_str()) {
        return Err("not allowed".into());
    }
    let f = project_dir(&app, &pid)?.join(format!("{name}.json"));
    fs::read_to_string(f).map_err(|e| e.to_string())
}

// ─────────────────────────── .env 配置(端点/Key/模型) ───────────────────────────
// MCP server 从仓库根的 .env 读配置;按默认布局 workspace 的父目录就是仓库根。

fn env_file(app: &AppHandle) -> Result<PathBuf, String> {
    let ws = workspace(app)?;
    Ok(ws.parent().map(Path::to_path_buf).unwrap_or(ws).join(".env"))
}

fn parse_env_line(line: &str) -> Option<(String, String)> {
    let t = line.trim();
    if t.starts_with('#') || !t.contains('=') {
        return None;
    }
    let (k, v) = t.split_once('=')?;
    Some((k.trim().to_string(), v.trim().trim_matches('"').trim_matches('\'').to_string()))
}

#[tauri::command]
fn read_env(app: AppHandle) -> Result<Value, String> {
    let f = env_file(&app)?;
    let mut vars = serde_json::Map::new();
    if let Ok(text) = fs::read_to_string(&f) {
        for line in text.lines() {
            if let Some((k, v)) = parse_env_line(line) {
                vars.insert(k, Value::String(v));
            }
        }
    }
    Ok(json!({ "path": f.to_string_lossy(), "vars": vars }))
}

#[tauri::command]
fn write_env(app: AppHandle, vars: std::collections::HashMap<String, String>) -> Result<String, String> {
    let f = env_file(&app)?;
    let mut lines: Vec<String> = fs::read_to_string(&f)
        .map(|t| t.lines().map(String::from).collect())
        .unwrap_or_default();
    let mut remaining = vars;
    // 原地更新已有键,保留注释与顺序;新键追加到末尾
    for line in lines.iter_mut() {
        if let Some((k, _)) = parse_env_line(line) {
            if let Some(v) = remaining.remove(&k) {
                *line = format!("{k}={v}");
            }
        }
    }
    let mut extra: Vec<_> = remaining.into_iter().filter(|(_, v)| !v.is_empty()).collect();
    extra.sort();
    for (k, v) in extra {
        lines.push(format!("{k}={v}"));
    }
    fs::write(&f, lines.join("\n") + "\n").map_err(|e| e.to_string())?;
    Ok(f.to_string_lossy().into_owned())
}

#[tauri::command]
fn test_gateway(base: String, key: String) -> Value {
    let b = base.trim().trim_end_matches('/');
    if b.is_empty() {
        return json!({ "ok": false, "error": "地址为空" });
    }
    let url = if b.ends_with("/v1") { format!("{b}/models") } else { format!("{b}/v1/models") };
    let agent = ureq::AgentBuilder::new()
        .timeout(std::time::Duration::from_secs(8))
        .build();
    match agent.get(&url).set("Authorization", &format!("Bearer {key}")).call() {
        Ok(resp) => {
            let body: Value = resp.into_json().unwrap_or_else(|_| json!({}));
            let n = body["data"].as_array().map(|a| a.len()).unwrap_or(0);
            json!({ "ok": true, "models": n })
        }
        Err(ureq::Error::Status(code, _)) => {
            let hint = match code {
                401 | 403 => "Key 无效或无权限(视频通道要用独立的 HVC_GROK_KEY)",
                404 => "地址不对:填网关根地址即可,不用带 /v1",
                _ => "网关返回异常",
            };
            json!({ "ok": false, "status": code, "error": hint })
        }
        Err(e) => json!({ "ok": false, "error": format!("连不上:{e}") }),
    }
}

// ─────────────────────────── 本地服务(配音台/模型管理后端) ───────────────────────────
// hotvideocopy-web 是 Python 侧的本地 HTTP 服务(配音/模型安装/媒体)。
// GUI 负责它的生命周期;前端一律走 web_get/web_post 代理,不直连(免 CORS/混合内容)。

fn repo_root(app: &AppHandle) -> Result<PathBuf, String> {
    // 默认布局:workspace 在仓库根下
    let ws = workspace(app)?;
    Ok(ws.parent().map(Path::to_path_buf).unwrap_or(ws))
}

fn web_bin(app: &AppHandle) -> Result<PathBuf, String> {
    let root = repo_root(app)?;
    let bin = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("hotvideocopy-web.exe")
    } else {
        root.join(".venv").join("bin").join("hotvideocopy-web")
    };
    bin.is_file().then_some(bin).ok_or("找不到 hotvideocopy-web——先在仓库里 `uv pip install -e .`".into())
}

fn web_healthy() -> bool {
    ureq::AgentBuilder::new()
        .timeout(std::time::Duration::from_millis(1200))
        .build()
        .get(&format!("http://127.0.0.1:{WEB_PORT}/api/health"))
        .call()
        .is_ok()
}

#[tauri::command]
fn svc_status(app: AppHandle, svc: tauri::State<WebService>) -> Value {
    let mut guard = svc.0.lock().unwrap();
    // 回收已退出的子进程
    if let Some(child) = guard.as_mut() {
        if matches!(child.try_wait(), Ok(Some(_))) {
            *guard = None;
        }
    }
    json!({
        "managed": guard.is_some(),
        "healthy": web_healthy(),
        "port": WEB_PORT,
        "bin_ok": web_bin(&app).is_ok(),
    })
}

#[tauri::command]
fn svc_start(app: AppHandle, svc: tauri::State<WebService>) -> Result<Value, String> {
    if web_healthy() {
        return Ok(json!({ "healthy": true, "port": WEB_PORT, "note": "服务已在运行" }));
    }
    let bin = web_bin(&app)?;
    let ws = workspace(&app)?;
    let child = Command::new(&bin)
        .args(["--no-open", "--port", &WEB_PORT.to_string()])
        .env("HVC_WORKSPACE", &ws)
        .current_dir(repo_root(&app)?)
        .spawn()
        .map_err(|e| format!("启动本地服务失败:{e}"))?;
    *svc.0.lock().unwrap() = Some(child);
    for _ in 0..25 {
        if web_healthy() {
            return Ok(json!({ "healthy": true, "port": WEB_PORT }));
        }
        std::thread::sleep(std::time::Duration::from_millis(400));
    }
    Err("本地服务启动后 10 秒内未通过健康检查".into())
}

#[tauri::command]
fn svc_stop(svc: tauri::State<WebService>) -> Value {
    if let Some(mut child) = svc.0.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    json!({ "stopped": true })
}

#[tauri::command]
fn web_get(path: String) -> Result<Value, String> {
    let url = format!("http://127.0.0.1:{WEB_PORT}{path}");
    let resp = ureq::AgentBuilder::new()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .get(&url)
        .call()
        .map_err(|e| match e {
            ureq::Error::Status(code, r) => format!("HTTP {code}: {}", r.into_string().unwrap_or_default()),
            other => format!("本地服务不可达:{other}"),
        })?;
    resp.into_json().map_err(|e| e.to_string())
}

#[tauri::command]
fn web_post(path: String, body: Value) -> Result<Value, String> {
    let url = format!("http://127.0.0.1:{WEB_PORT}{path}");
    ureq::AgentBuilder::new()
        .timeout(std::time::Duration::from_secs(600))  // TTS 合成/模型动作可能久
        .build()
        .post(&url)
        .send_json(body)
        .map_err(|e| match e {
            ureq::Error::Status(code, r) => format!("HTTP {code}: {}", r.into_string().unwrap_or_default()),
            other => format!("本地服务不可达:{other}"),
        })?
        .into_json()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn open_voice_window(app: AppHandle) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{WEB_PORT}/voice.html")
        .parse()
        .map_err(|e| format!("{e}"))?;
    if let Some(w) = app.get_webview_window("voice") {
        let _ = w.set_focus();
        return Ok(());
    }
    tauri::WebviewWindowBuilder::new(&app, "voice", tauri::WebviewUrl::External(url))
        .title("配音工作台 · 写轮眼")
        .inner_size(1180.0, 820.0)
        .build()
        .map_err(|e| format!("打开配音窗口失败:{e}"))?;
    Ok(())
}

// ─────────────────────────── 抽帧(捆绑 ffmpeg,系统回退) ───────────────────────────

fn ffmpeg_bin() -> PathBuf {
    // externalBin 的 sidecar 落在可执行文件同目录;没有就交给 PATH
    let name = if cfg!(windows) { "ffmpeg.exe" } else { "ffmpeg" };
    std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|p| p.join(name)))
        .filter(|p| p.is_file())
        .unwrap_or_else(|| PathBuf::from(name))
}

#[tauri::command]
fn extract_frame(app: AppHandle, pid: String, t: f64, w: u32) -> Result<String, String> {
    let d = project_dir(&app, &pid)?;
    let video = d.join("source.mp4");
    if !video.is_file() {
        return Err("没有 source.mp4".into());
    }
    let w = w.clamp(120, 1080);
    let cache = d.join("frames");
    fs::create_dir_all(&cache).map_err(|e| e.to_string())?;
    // 命名与 Python 侧 shots.frame_files 完全一致 → 共用缓存
    let out = cache.join(format!("t{:09.3}_w{}.jpg", t.max(0.0), w));
    if !out.is_file() {
        let status = Command::new(ffmpeg_bin())
            .args(["-y", "-ss", &format!("{:.3}", t.max(0.0)), "-i"])
            .arg(&video)
            .args(["-frames:v", "1", "-q:v", "3", "-vf", &format!("scale={w}:-2")])
            .arg(&out)
            .output()
            .map_err(|e| format!("ffmpeg 启动失败:{e}(捆绑与系统均不可用)"))?;
        if !status.status.success() || !out.is_file() {
            return Err("抽帧失败(时间点可能超出时长)".into());
        }
    }
    Ok(out.to_string_lossy().into_owned())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(WebService(Mutex::new(None)))
        .setup(|app| {
            if let Some(ws) = load_workspace(&app.handle().clone()) {
                allow_media(app.handle(), &ws);
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_workspace,
            set_workspace,
            list_projects,
            project_detail,
            read_project_json,
            extract_frame,
            read_env,
            write_env,
            test_gateway,
            svc_status,
            svc_start,
            svc_stop,
            web_get,
            web_post,
            open_voice_window,
        ])
        .build(tauri::generate_context!())
        .expect("启动失败")
        .run(|app, event| {
            // 退出时带走本地服务子进程,不留孤儿
            if let tauri::RunEvent::Exit = event {
                if let Some(svc) = app.try_state::<WebService>() {
                    if let Some(mut child) = svc.0.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}

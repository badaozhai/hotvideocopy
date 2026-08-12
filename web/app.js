(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var FPS = 30;
  var DEFAULT_PROJECT = {
    project_id: "dy_7671559890300685604",
    title: "云霄往事 · 魔性舞步",
    duration: 15.933333,
    frame_count: 478,
    fps: 30,
    width: 1254,
    height: 720,
    source_file: "dy_7671559890300685604/source.mp4",
    bgm_file: "dy_7671559890300685604/bgm_original.m4a",
    source_title: "云霄往事之魔性舞步 镇压全场",
    beats: [
      { index: 1, start: 0.000000, end: 0.833333, label: "起势抬袖", cast: "female", role: "嫦娥", visual: "start" },
      { index: 2, start: 0.833333, end: 1.733333, label: "左右摆袖", cast: "female", role: "嫦娥", visual: "female" },
      { index: 3, start: 1.733333, end: 2.633333, label: "回身落步", cast: "female", role: "嫦娥", visual: "female" },
      { index: 4, start: 2.633333, end: 3.566667, label: "袖摆卡点", cast: "female", role: "嫦娥", visual: "female" },
      { index: 5, start: 3.566667, end: 4.566667, label: "转身定格", cast: "female", role: "嫦娥", visual: "female" },
      { index: 6, start: 4.566667, end: 5.566667, label: "侧身舒展", cast: "female", role: "嫦娥", visual: "female" },
      { index: 7, start: 5.566667, end: 6.533333, label: "孙悟空入画", cast: "male", role: "孙悟空", visual: "approach" },
      { index: 8, start: 6.533333, end: 7.466667, label: "双人靠近", cast: "duo", role: "孙悟空 × 嫦娥", visual: "approach" },
      { index: 9, start: 7.466667, end: 8.466667, label: "对望抬手", cast: "duo", role: "孙悟空 × 嫦娥", visual: "interaction" },
      { index: 10, start: 8.466667, end: 9.466667, label: "正面互动", cast: "duo", role: "孙悟空 × 嫦娥", visual: "interaction" },
      { index: 11, start: 9.466667, end: 10.533333, label: "手势对拍", cast: "duo", role: "孙悟空 × 嫦娥", visual: "interaction" },
      { index: 12, start: 10.533333, end: 11.533333, label: "近景碰拍", cast: "duo", role: "孙悟空 × 嫦娥", visual: "interaction" },
      { index: 13, start: 11.533333, end: 12.566667, label: "交错转身", cast: "duo", role: "孙悟空 × 嫦娥", visual: "interaction" },
      { index: 14, start: 12.566667, end: 13.566667, label: "嫦娥下探", cast: "duo", role: "孙悟空 × 嫦娥", visual: "exit" },
      { index: 15, start: 13.566667, end: 14.533333, label: "嫦娥退场", cast: "female", role: "嫦娥", visual: "exit" },
      { index: 16, start: 14.533333, end: 15.933333, label: "悟空收尾", cast: "male", role: "孙悟空", visual: "finish" }
    ]
  };
  var project = DEFAULT_PROJECT;
  var video = $("targetVideo");
  var sourceVideo = $("sourceVideo");
  var rafId = 0;
  var toastTimer = 0;
  var waveformValues = [34, 58, 42, 74, 63, 30, 48, 85, 55, 40, 68, 91, 45, 34, 58, 78, 48, 70, 38, 57, 87, 62, 37, 48, 71, 56, 33, 66, 84, 49, 39, 72, 52, 88, 42, 61, 35, 57, 80, 46, 67, 31, 53, 76, 43, 86, 59, 36, 65, 49, 72, 40, 60, 83, 45, 66, 32, 54, 78, 51, 69, 38, 58];

  function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }

  function formatTime(value, precise) {
    var seconds = Math.max(0, Number(value) || 0);
    var minutes = Math.floor(seconds / 60);
    var rest = seconds - minutes * 60;
    return String(minutes).padStart(2, "0") + ":" + (precise ? rest.toFixed(3).padStart(6, "0") : String(Math.floor(rest)).padStart(2, "0"));
  }

  function formatRange(start, end) {
    return formatTime(start, true) + " – " + formatTime(end, true);
  }

  function showToast(message, isError) {
    var toast = $("toast");
    toast.textContent = message;
    toast.classList.toggle("is-error", Boolean(isError));
    toast.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { toast.classList.remove("is-visible"); }, 3200);
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (char) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char];
    });
  }

  function renderWaveform() {
    var waveform = $("waveform");
    waveform.innerHTML = "";
    waveformValues.forEach(function (value) {
      var bar = document.createElement("i");
      bar.style.height = Math.max(16, value) + "%";
      waveform.appendChild(bar);
    });
  }

  function renderRuler() {
    var ruler = $("ruler");
    ruler.innerHTML = "";
    var seconds = [0, 2, 4, 6, 8, 10, 12, 14, project.duration];
    seconds.forEach(function (second, index) {
      var mark = document.createElement("span");
      mark.className = "ruler-mark";
      mark.style.left = (second / project.duration * 100) + "%";
      var label = document.createElement("span");
      label.textContent = index === seconds.length - 1 ? project.duration.toFixed(3) : formatTime(second, true).slice(3);
      mark.appendChild(label);
      ruler.appendChild(mark);
    });
  }

  function addBeatBlock(lane, beat) {
    var block = document.createElement("button");
    block.className = "beat-block";
    block.type = "button";
    block.dataset.index = String(beat.index);
    block.style.left = (beat.start / project.duration * 100) + "%";
    block.style.width = ((beat.end - beat.start) / project.duration * 100) + "%";
    block.innerHTML = '<span class="beat-number">' + String(beat.index).padStart(2, "0") + '</span><span class="beat-name">' + escapeHtml(beat.label) + '</span>';
    block.addEventListener("click", function () { seekTo(beat.start, true); });
    lane.appendChild(block);
  }

  function renderTimeline() {
    var beatLane = $("beatLane");
    var castLane = $("castLane");
    beatLane.innerHTML = "";
    castLane.innerHTML = "";
    project.beats.forEach(function (beat) { addBeatBlock(beatLane, beat); });
    [
      { start: 0, end: 5.566667, label: "嫦娥", type: "female" },
      { start: 5.566667, end: 6.533333, label: "孙悟空", type: "male" },
      { start: 6.533333, end: 13.566667, label: "孙悟空 × 嫦娥", type: "duo" },
      { start: 13.566667, end: 14.533333, label: "嫦娥", type: "female" },
      { start: 14.533333, end: project.duration, label: "孙悟空", type: "male" }
    ].forEach(function (item) {
      var block = document.createElement("span");
      block.className = "cast-block " + item.type;
      block.style.left = (item.start / project.duration * 100) + "%";
      block.style.width = ((item.end - item.start) / project.duration * 100) + "%";
      block.textContent = item.label;
      castLane.appendChild(block);
    });
    var table = $("beatTable");
    table.innerHTML = "";
    project.beats.forEach(function (beat) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "beat-row";
      row.dataset.index = String(beat.index);
      var roleClass = beat.cast === "duo" ? " duo" : "";
      row.innerHTML = '<span class="row-number">' + String(beat.index).padStart(2, "0") + '</span>' +
        '<span class="row-time">' + escapeHtml(formatRange(beat.start, beat.end)) + '</span>' +
        '<span>' + escapeHtml(beat.label) + '</span>' +
        '<span><span class="role-pill' + roleClass + '">' + escapeHtml(beat.role) + '</span></span>' +
        '<span class="row-status">LOCKED</span>';
      row.addEventListener("click", function () { seekTo(beat.start, true); });
      table.appendChild(row);
    });
  }

  function updateMetrics() {
    $("durationMetric").textContent = project.duration.toFixed(3) + " s";
    $("fpsMetric").textContent = project.fps + " fps";
    $("aspectMetric").textContent = project.width + " × " + project.height;
    $("totalTime").textContent = formatTime(project.duration, true);
    $("audioDuration").textContent = project.duration.toFixed(3) + " s";
    $("frameCount").textContent = String(project.frame_count);
    $("beatCount").textContent = String(project.beats.length);
  }

  function currentBeatAt(time) {
    var last = project.beats[project.beats.length - 1];
    return project.beats.find(function (beat) { return time >= beat.start && time < beat.end; }) || last;
  }

  function syncReference(force) {
    if (!sourceVideo || sourceVideo.readyState < 1) return;
    var time = clamp(Number(video.currentTime) || 0, 0, project.duration);
    if (force || Math.abs((Number(sourceVideo.currentTime) || 0) - time) > 0.5 / FPS) {
      sourceVideo.currentTime = time;
    }
  }

  function movePlayhead(time) {
    var lane = $("ruler");
    var playhead = $("playhead");
    if (!lane) return;
    playhead.style.left = (lane.offsetLeft + lane.offsetWidth * clamp(time / project.duration, 0, 1)) + "px";
  }

  function syncUi() {
    var time = Number(video.currentTime) || 0;
    var beat = currentBeatAt(time);
    var frame = clamp(Math.floor(time * project.fps + 1e-4), 0, project.frame_count - 1);
    $("currentTime").textContent = formatTime(time, true);
    $("frameTag").textContent = "F" + String(frame).padStart(4, "0");
    $("targetFrameTag").textContent = "LOCKED / F" + String(frame).padStart(4, "0");
    $("audioProgress").style.width = clamp(time / project.duration * 100, 0, 100) + "%";
    document.querySelectorAll(".beat-block, .beat-row").forEach(function (item) {
      item.classList.toggle("is-active", item.dataset.index === String(beat.index));
    });
    movePlayhead(time);
    var bars = $("waveform").children;
    var progress = clamp(time / project.duration, 0, 1);
    Array.prototype.forEach.call(bars, function (bar, index) { bar.classList.toggle("is-past", index / bars.length < progress); });
    if (!video.paused) {
      syncReference(false);
      rafId = window.requestAnimationFrame(syncUi);
    }
  }

  function seekTo(time, pauseAfter) {
    video.currentTime = clamp(time, 0, project.duration);
    sourceVideo.currentTime = video.currentTime;
    if (pauseAfter) video.pause();
    syncUi();
  }

  function togglePlayback() {
    if (video.paused) {
      video.play().catch(function () { showToast("浏览器阻止了自动播放，请点击视频控件播放", true); });
    } else {
      video.pause();
    }
  }

  function updatePlayButton() {
    var playing = !video.paused;
    $("playButton").textContent = playing ? "Ⅱ" : "▶";
    $("audioPlayButton").textContent = playing ? "Ⅱ" : "▶";
    $("sourceStatus").textContent = playing ? "SYNC" : "READY";
    $("targetStatus").textContent = playing ? "PLAYING" : "FINAL";
  }

  function stepFrame(amount) {
    video.pause();
    seekTo((Math.floor((Number(video.currentTime) || 0) * project.fps + 1e-4) + amount) / project.fps, true);
  }

  function setupPreview() {
    $("playButton").addEventListener("click", togglePlayback);
    $("audioPlayButton").addEventListener("click", function (event) { event.stopPropagation(); togglePlayback(); });
    $("audioTrack").addEventListener("click", function () { togglePlayback(); });
    $("audioTrack").addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); togglePlayback(); }
    });
    $("frameBackButton").addEventListener("click", function () { stepFrame(-1); });
    $("frameForwardButton").addEventListener("click", function () { stepFrame(1); });
    video.addEventListener("play", function () {
      syncReference(true);
      sourceVideo.play().catch(function () {});
      updatePlayButton();
      syncUi();
    });
    video.addEventListener("pause", function () {
      sourceVideo.pause();
      syncReference(true);
      updatePlayButton();
      window.cancelAnimationFrame(rafId);
      syncUi();
    });
    video.addEventListener("timeupdate", function () { syncReference(false); syncUi(); });
    video.addEventListener("seeking", function () { syncReference(true); syncUi(); });
    video.addEventListener("seeked", function () { syncReference(true); syncUi(); });
    video.addEventListener("loadedmetadata", function () {
      if (Number.isFinite(video.duration) && video.duration > 0) {
        project.duration = Math.min(project.duration, video.duration);
        updateMetrics();
        renderRuler();
        renderTimeline();
      }
      $("targetStatus").textContent = "FINAL";
      syncReference(true);
      syncUi();
    });
    video.addEventListener("error", function () {
      $("targetStatus").textContent = "ERROR";
      showToast("成片读取失败，请确认本地服务正在运行", true);
    });
    sourceVideo.addEventListener("loadedmetadata", function () {
      $("sourceStatus").textContent = "READY";
      syncReference(true);
    });
    sourceVideo.addEventListener("playing", function () { syncReference(true); });
    sourceVideo.addEventListener("error", function () {
      $("sourceStatus").textContent = "ERROR";
      showToast("原片读取失败，请确认本地服务正在运行", true);
    });
  }

  function setupAssets() {
    document.querySelectorAll(".asset-card").forEach(function (card) {
      card.addEventListener("click", function () {
        card.classList.add("is-selected");
        card.setAttribute("aria-pressed", "true");
        showToast((card.dataset.role === "male" ? "男角色" : "女角色") + "已锁定为" + (card.dataset.role === "male" ? "孙悟空" : "嫦娥"));
      });
    });
    ["frameLock", "beatLock", "audioLock"].forEach(function (id) {
      $(id).addEventListener("change", function () {
        if (!$(id).checked) showToast("对齐门禁未全部通过，导出前请重新勾选", true);
      });
    });
  }

  async function loadProject() {
    try {
      var response = await fetch("/api/replica");
      var data = await response.json();
      if (response.ok && data.ok) {
        project = Object.assign({}, DEFAULT_PROJECT, data);
        if (Array.isArray(data.beats) && data.beats.length) project.beats = data.beats;
        updateMetrics();
        renderRuler();
        renderTimeline();
      }
    } catch (error) {
      $("syncLabel").textContent = "本地预览";
    }
  }

  $("downloadButton").addEventListener("click", function () { showToast("成片下载已开始"); });
  $("alignButton").addEventListener("click", function () {
    seekTo(0, true);
    showToast("已回到源片首帧，动作目标重新对齐");
  });
  $("refreshButton").addEventListener("click", function () { window.location.reload(); });
  window.addEventListener("resize", function () { movePlayhead(Number(video.currentTime) || 0); });
  setupPreview();
  setupAssets();
  renderWaveform();
  updateMetrics();
  renderRuler();
  renderTimeline();
  syncUi();
  loadProject();
}());

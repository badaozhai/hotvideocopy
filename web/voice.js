(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var state = { mode: "preset", reference: null, models: null, history: [] };
  var bars = [32, 48, 70, 42, 82, 54, 36, 66, 88, 48, 73, 38, 58, 94, 44, 68, 51, 84, 39, 62, 77, 46, 91, 56, 35, 72, 49, 86, 61, 40, 69, 52, 80, 43, 64, 90, 47, 75, 55, 83, 37, 67, 50, 87, 59, 41, 74, 53, 81, 45, 65, 92, 48, 71, 57, 85, 39, 63, 76, 46];

  function toast(message, error) {
    var node = $("toast");
    node.textContent = message;
    node.classList.toggle("is-error", Boolean(error));
    node.classList.add("is-visible");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { node.classList.remove("is-visible"); }, 3600);
  }

  async function request(url, options) {
    var response = await fetch(url, options);
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败");
    return data;
  }

  function bytes(value) {
    var size = Number(value) || 0;
    if (size >= 1073741824) return (size / 1073741824).toFixed(1) + " GB";
    if (size >= 1048576) return (size / 1048576).toFixed(0) + " MB";
    return (size / 1024).toFixed(0) + " KB";
  }

  function activeModel() {
    if (!state.models) return null;
    var id = state.mode === "clone" ? "qwen3-tts-clone-8bit" : "qwen3-tts-custom-8bit";
    return state.models.find(function (model) { return model.id === id; }) || null;
  }

  function renderModel() {
    var model = activeModel();
    var ready = Boolean(model && model.installed);
    $("modelState").textContent = ready ? "本地模型就绪" : "本地模型未安装";
    $("modelState").parentElement.classList.toggle("is-ready", ready);
    $("modelState").parentElement.classList.toggle("is-error", !ready);
    $("activeModelSize").textContent = model ? model.params : "--";
    $("modelActionTitle").textContent = state.mode === "clone" ? "克隆模型" : "预设模型";
    $("modelDisk").textContent = model ? (ready ? "已占用 " + bytes(model.cache_bytes) : model.title) : "读取中";
    $("installButton").textContent = ready ? "已安装 · 永久保留" : "安装模型";
    $("installButton").dataset.action = "install";
    $("installButton").disabled = ready;
    $("generateButton").disabled = !ready;
  }

  async function loadModels() {
    try {
      var data = await request("/api/local-models");
      state.models = data.models || [];
      renderModel();
    } catch (error) {
      $("modelState").textContent = "模型状态读取失败";
      $("modelState").parentElement.classList.add("is-error");
      toast(error.message, true);
    }
  }

  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll(".mode-button").forEach(function (button) {
      button.classList.toggle("is-active", button.dataset.mode === mode);
    });
    $("presetControls").hidden = mode !== "preset";
    $("cloneControls").hidden = mode !== "clone";
    renderModel();
  }

  function readFile(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(new Error("参考音频读取失败")); };
      reader.readAsDataURL(file);
    });
  }

  async function uploadReference(file) {
    if (!file) return;
    $("uploadTitle").textContent = "上传中…";
    try {
      var data = await request("/api/voice-reference", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: $("projectInput").value, filename: file.name, data: await readFile(file) })
      });
      state.reference = data;
      $("uploadZone").classList.add("is-uploaded");
      $("uploadTitle").textContent = file.name;
      $("uploadMeta").textContent = bytes(data.bytes) + " · 已保存";
      $("referencePreview").src = data.audio_url;
      $("referencePreview").hidden = false;
      toast("参考音频已载入");
    } catch (error) {
      $("uploadTitle").textContent = "选择 3–15 秒人声";
      toast(error.message, true);
    }
  }

  function renderWaveform() {
    var waveform = $("waveform");
    waveform.innerHTML = "";
    bars.forEach(function (height) {
      var bar = document.createElement("i");
      bar.style.setProperty("--h", height + "%");
      waveform.appendChild(bar);
    });
  }

  function duration(value) {
    var seconds = Math.max(0, Math.round(Number(value) || 0));
    return String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  }

  function loadHistory() {
    try { state.history = JSON.parse(localStorage.getItem("hvc_voice_history") || "[]"); }
    catch (error) { state.history = []; }
    renderHistory();
  }

  function saveHistory(item) {
    state.history.unshift(item);
    state.history = state.history.slice(0, 20);
    localStorage.setItem("hvc_voice_history", JSON.stringify(state.history));
    renderHistory();
  }

  function showResult(item) {
    var audio = $("resultAudio");
    audio.src = item.audio_url;
    audio.load();
    $("audioDuration").textContent = duration(item.duration);
    $("resultMeta").textContent = item.voice + " · " + (item.cloned ? "克隆" : item.language) + " · " + item.duration.toFixed(2) + "s";
    $("downloadButton").href = item.download_url || item.audio_url;
    $("downloadButton").download = (item.file || "voice.wav").split("/").pop();
    $("downloadButton").classList.remove("is-disabled");
    $("downloadButton").setAttribute("aria-disabled", "false");
    $("playButton").disabled = false;
    $("waveform").classList.add("is-ready");
  }

  function renderHistory() {
    var list = $("historyList");
    list.innerHTML = "";
    if (!state.history.length) {
      var empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "暂无记录";
      list.appendChild(empty);
      return;
    }
    state.history.forEach(function (item) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "history-row";
      var when = document.createElement("time");
      when.textContent = item.created_at ? item.created_at.slice(11, 16) : "--:--";
      var text = document.createElement("strong");
      text.textContent = item.text;
      var detail = document.createElement("small");
      detail.textContent = item.voice + " · " + item.language;
      var length = document.createElement("span");
      length.textContent = duration(item.duration);
      row.append(when, text, detail, length);
      row.addEventListener("click", function () { showResult(item); });
      list.appendChild(row);
    });
  }

  async function generate() {
    var text = $("scriptInput").value.trim();
    if (!text) return toast("请输入台词", true);
    if (state.mode === "clone" && !state.reference) return toast("请先上传参考音频", true);
    if (state.mode === "clone" && !$("referenceText").value.trim()) return toast("请填写参考音频文字", true);
    if (state.mode === "clone" && !$("cloneConsent").checked) return toast("请确认已获得音色授权", true);
    var button = $("generateButton");
    button.disabled = true;
    button.querySelector("span").textContent = "生成中…";
    try {
      var payload = {
        text: text,
        project_id: $("projectInput").value,
        engine: "local",
        model: state.mode === "clone" ? "qwen3-tts-clone-8bit" : "qwen3-tts-custom-8bit",
        voice: state.mode === "clone" ? "" : $("voiceSelect").value,
        language: $("languageSelect").value,
        instruction: $("instructionInput").value.trim(),
        speed: Number($("speedRange").value),
        reference_audio: state.reference ? state.reference.file : "",
        reference_text: $("referenceText").value.trim(),
        consent: state.mode === "clone" && $("cloneConsent").checked
      };
      var item = await request("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      item.text = text;
      showResult(item);
      saveHistory(item);
      toast("配音已生成，模型内存已释放");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.querySelector("span").textContent = "生成配音";
      renderModel();
    }
  }

  async function pollModelJob(id) {
    while (true) {
      await new Promise(function (resolve) { window.setTimeout(resolve, 1500); });
      var data = await request("/api/local-model-job?id=" + encodeURIComponent(id));
      if (data.job.status === "running") continue;
      if (data.job.status === "failed") throw new Error(data.job.error || "模型操作失败");
      return data.job;
    }
  }

  async function modelAction() {
    var variant = state.mode === "clone" ? "clone" : "custom";
    $("installButton").disabled = true;
    $("installButton").textContent = "安装中…";
    try {
      var data = await request("/api/local-models/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "install", component: "voice", variant: variant })
      });
      await pollModelJob(data.job.id);
      await loadModels();
      toast("模型安装完成，文件会永久保留");
    } catch (error) {
      toast(error.message, true);
    } finally {
      $("installButton").disabled = false;
      renderModel();
    }
  }

  document.querySelectorAll(".mode-button").forEach(function (button) {
    button.addEventListener("click", function () { setMode(button.dataset.mode); });
  });
  document.querySelectorAll("[data-tone]").forEach(function (button) {
    button.addEventListener("click", function () { $("instructionInput").value = button.dataset.tone; });
  });
  $("referenceFile").addEventListener("change", function (event) { uploadReference(event.target.files[0]); });
  $("speedRange").addEventListener("input", function () { $("speedValue").textContent = Number(this.value).toFixed(2) + "×"; });
  $("scriptInput").addEventListener("input", function () { $("charCount").textContent = this.value.length + " 字"; });
  $("generateButton").addEventListener("click", generate);
  $("installButton").addEventListener("click", modelAction);
  $("refreshModels").addEventListener("click", loadModels);
  $("playButton").addEventListener("click", function () {
    var audio = $("resultAudio");
    if (audio.paused) audio.play(); else audio.pause();
  });
  $("resultAudio").addEventListener("play", function () { $("playButton").textContent = "Ⅱ"; });
  $("resultAudio").addEventListener("pause", function () { $("playButton").textContent = "▶"; });
  $("resultAudio").addEventListener("ended", function () { $("playButton").textContent = "▶"; });
  $("clearHistory").addEventListener("click", function () { state.history = []; localStorage.removeItem("hvc_voice_history"); renderHistory(); });
  document.addEventListener("keydown", function (event) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); generate(); }
  });

  renderWaveform();
  loadHistory();
  loadModels();
}());

"use strict";
const $ = id => document.getElementById(id);
let token = "", job = null, result = null, selected = null, busy = false, listenEnd = null, retry = 0;
let lyricsDirty = false, draftJob = null, playingId = null;
const audio = $("audio-player");
const waveform = new MuzhunWaveform($("waveform"),audio,(start,end)=>api(`/api/lyrics/${job}/waveform?start=${start}&end=${end}`),time=>{listenEnd=null;audio.currentTime=time;});
function error(message = "") { $("lyrics-error").textContent = message; $("lyrics-error").classList.toggle("hidden", !message); }
async function api(url, options = {}) {
  const response = await fetch(url, {...options, headers: {"X-Muzhun-Token": token, ...options.headers}});
  let data;
  try { data = await response.json(); } catch { throw new Error("服务暂时无法读取，请稍后重试"); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请求失败，请检查输入");
  return data;
}
function numberValue(id) { return $(id).value.trim() === "" ? null : Number($(id).value); }
function current() { return result?.lines.find(row => row.id === selected); }
function displayedTime(value) { return value === null ? null : Number(value.toFixed(3)); }
function savedTime(id, value) { const input = numberValue(id); return input === displayedTime(value) ? value : input; }
function dirty() { const row = current(); return row && ($("lyric-edit").value !== row.text || numberValue("lyric-start") !== displayedTime(row.start) || numberValue("lyric-end") !== displayedTime(row.end)); }
function leaveDraft() { return !dirty() || window.confirm("这句修改还未保存。放弃本次输入并继续？"); }
function leaveAllDrafts() { return !(dirty() || lyricsDirty) || window.confirm("有尚未保存或应用的修改。放弃本次输入并继续？"); }
function timeLabel(value) { if (value === null) return "未定位"; const ticks = Math.round(value * 100), minutes = Math.floor(ticks / 6000); return `${String(minutes).padStart(2,"0")}:${((ticks % 6000) / 100).toFixed(2).padStart(5,"0")}`; }
function renderList() {
  const query = $("lyrics-search").value.toLocaleLowerCase(), filter = $("lyrics-filter").value;
  const rows = result.lines.filter(row => row.text.toLocaleLowerCase().includes(query) && (filter === "all" || (filter === "untimed" && row.start === null) || (filter === "unreviewed" && !row.reviewed) || (filter === "issues" && row.issues.length && !row.reviewed)));
  $("lyrics-list").replaceChildren();
  const positions=new Map(result.lines.map((row,index)=>[row.id,index+1]));
  for (const row of rows) {
    const button = document.createElement("button"); button.dataset.id = row.id; button.className = "lyric-row" + (row.id === selected ? " selected" : "") + (row.id === playingId ? " playing" : "");
    const index = document.createElement("span"); index.textContent = String(positions.get(row.id)).padStart(2,"0"); index.className = "badge";
    const body = document.createElement("span"); body.className = "lyric-body";
    const text = document.createElement("strong"); text.textContent = row.text;
    const times = document.createElement("small"); times.textContent = row.start === null ? "需要手动定位" : `${timeLabel(row.start)} — ${timeLabel(row.end)}`;
    const tag = document.createElement("span"); tag.className = "lyric-tag" + (row.start === null ? " warn" : ""); tag.textContent = row.reviewed ? "已复核" : row.start === null ? "未定位" : "待试听";
    body.append(text, times); button.append(index, body, tag);
    button.addEventListener("click", () => { if (!busy && leaveDraft()) choose(row.id, true); });
    $("lyrics-list").append(button);
  }
  if (!rows.length) $("lyrics-list").textContent = "没有符合筛选的歌词";
}
function choose(id, seek = false) {
  listenEnd = null; selected = id;
  const row = current(); if (!row) return;
  $("lyric-number").textContent = String(result.lines.findIndex(line=>line.id===id)+1).padStart(2,"0"); $("lyric-edit").value = row.text;
  $("lyric-original").textContent = "原文：" + row.original;
  $("lyric-anchor").textContent = row.anchor_text ? `识别锚点：${row.anchor_text} · 文字匹配 ${Math.round(row.coverage * 100)}%` : "";
  $("lyric-start").value = displayedTime(row.start) ?? ""; $("lyric-end").value = displayedTime(row.end) ?? "";
  $("lyric-issues").textContent = row.reviewed ? "本句已人工复核" : row.issues.join("；") || (result.text_source === "asr-transcript" ? "文字与时间来自自动识别，请试听核对。" : "文字匹配不代表时间正确，请试听确认。");
  $("lyric-review").textContent = row.reviewed ? "取消复核标记" : "标记已复核";
  $("lyric-listen").disabled = row.start === null; $("lyric-review").disabled = row.start === null;
  if (seek && row.start !== null) { audio.pause(); audio.currentTime = row.start; }
  $("range-start").value = Math.max(0,(row.start ?? audio.currentTime)-3).toFixed(1);
  $("range-end").value = Math.min(result.metadata.duration,(row.end ?? audio.currentTime+10)+3).toFixed(1);
  waveform.focus(row.start,row.end,result.metadata.duration);
  renderList();
}
function render() {
  $("lyrics-welcome").classList.add("hidden"); $("lyrics-progress").classList.add("hidden"); $("lyrics-workspace").classList.remove("hidden");
  $("lyrics-summary").textContent = `${result.summary.total} 行 · 已定位 ${result.summary.timed} · 已复核 ${result.summary.reviewed}`;
  $("lines-heading").textContent = result.content === "speech" ? "字幕" : "歌词";
  $("lyrics-undo").disabled = !result.history.undo.length; $("lyrics-redo").disabled = !result.history.redo.length;
  for (const [id, name] of [["lyrics-lrc","lyrics.lrc"],["lyrics-srt","lyrics.srt"],["lyrics-report","lyrics-result.json"]]) {
    const link = $(id); const available = name.endsWith(".json") || result.summary.exportable;
    if (available) link.href = `/api/lyrics/${job}/files/${name}?revision=${result.revision}`;
    else link.removeAttribute("href");
    link.tabIndex = available ? 0 : -1; link.setAttribute("aria-disabled", String(!available));
  }
  $("lyrics-export-note").textContent = result.summary.exportable ? `修订 ${result.revision}。LRC 为逐行滚动歌词；SRT 可用于剪辑。请先试听复核。` : `还有 ${result.summary.total - result.summary.timed} 行未定位，补齐后可下载完整字幕。`;
  $("lyrics-source").textContent = result.text_source === "asr-transcript" ? `正文：自动识别${result.script_output === "simplified" ? " · 简体" : ""}` : "正文：提供的歌词";
  $("lyrics-realign-note").textContent = result.summary.can_realign ? "复用已保存的音频锚点，不重跑识别。更新所有歌词行，旧结果可撤销。已有 LRC/SRT 使用自己的时间。" : "旧记录没有逐词锚点；纯文本重对齐请重新上传音频。导入已有 LRC/SRT 可以直接使用。";
  if (draftJob !== job) { $("lyrics-realign-text").value = result.text_source === "asr-transcript" ? "" : result.lines.map(row => row.text).join("\n"); lyricsDirty = false; draftJob = job; }
  choose(result.lines.some(row => row.id === selected) ? selected : result.lines[0].id);
  showLive(); refreshRecentAudio();
}
async function update(payload) {
  if (busy) return;
  busy = true; error();
  const controls = [...$("lyrics-workspace").querySelectorAll("button,input,textarea,select")].map(element => [element, element.disabled]);
  for (const [element] of controls) element.disabled = true;
  let changed = false;
  try { result = await api(`/api/lyrics/${job}/revise`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:result.revision,...payload})}); changed = true; if (payload.action === "realign") lyricsDirty = false; }
  catch (failure) { error(failure.message); }
  finally { for (const [element, disabled] of controls) element.disabled = disabled; busy = false; if (changed) render(); }
}
async function poll() {
  try {
    const state = await api(`/api/lyrics/${job}`); retry = 0;
    $("lyrics-message").textContent = state.message; $("lyrics-meter").value = state.progress;
    if (state.status === "error") { $("lyrics-welcome").classList.remove("hidden"); $("lyrics-retry").classList.toggle("hidden",!state.request); error(state.message); return; }
    $("lyrics-retry").classList.add("hidden");
    if (state.status === "ready") {
      result = state.result; $("lyrics-title").textContent = state.name; audio.src = state.audio_url; render(); return;
    }
    setTimeout(poll, 1000);
  } catch (failure) {
    error(failure.message);
    if (!$("lyrics-progress").classList.contains("hidden") && ++retry <= 3) setTimeout(poll, 1500);
  }
}
$("audio-input").addEventListener("change", () => { $("audio-label").textContent = $("audio-input").files[0]?.name || "选择音频"; });
async function importText(input, target) {
  const file = $(input).files[0]; if (!file) return;
  if (file.size > 2 * 1024 * 1024) return error("歌词文件最大 2 MB");
  const buffer = await file.arrayBuffer();
  try { $(target).value = new TextDecoder("utf-8", {fatal:true}).decode(buffer); }
  catch { $(target).value = new TextDecoder("gb18030").decode(buffer); }
  if (target === "lyrics-realign-text") lyricsDirty = true;
}
$("lyrics-file").addEventListener("change", () => importText("lyrics-file", "lyrics-text"));
$("lyrics-realign-file").addEventListener("change", () => importText("lyrics-realign-file", "lyrics-realign-text"));
$("lyrics-realign-text").addEventListener("input", () => { lyricsDirty = true; });
$("lyrics-realign-apply").addEventListener("click", () => {
  if (dirty()) return error("先保存本句修改，再按完整歌词重新对齐");
  update({action:"realign",lyrics:$("lyrics-realign-text").value});
});
$("lyrics-simplify").addEventListener("click", () => { if (leaveDraft()) update({action:"simplify"}); });
$("lyrics-form").addEventListener("submit", async event => {
  event.preventDefault(); error(); $("lyrics-start").disabled = true;
  try {
    const file=$("audio-input").files[0];if(file?.size>512*1024**2)throw new Error("音频最大 512 MB");
    $("lyrics-progress").classList.remove("hidden");$("lyrics-retry").classList.add("hidden");
    const response = await MuzhunUI.upload("/api/lyrics",new FormData(event.target),token,value=>{$("lyrics-meter").value=value;$("lyrics-message").textContent=`正在导入音频 ${Math.round(value*100)}%`;});
    job = response.id; selected = null; result = null; history.replaceState(null,"",`/lyrics?job=${job}`);
    $("lyrics-welcome").classList.add("hidden"); $("lyrics-progress").classList.remove("hidden"); poll();
  } catch (failure) { error(failure.message); }
  finally { $("lyrics-start").disabled = false; }
});
$("lyric-save").addEventListener("click", () => update({edits:[{id:selected,text:$("lyric-edit").value,start:savedTime("lyric-start",current().start),end:savedTime("lyric-end",current().end)}]}));
$("lyric-review").addEventListener("click", () => { if (dirty()) return error("先保存修改，再试听和标记复核"); update({edits:[{id:selected,reviewed:!current().reviewed}]}); });
$("lyric-set-start").addEventListener("click", () => { $("lyric-start").value = audio.currentTime.toFixed(3); });
$("lyric-set-end").addEventListener("click", () => { $("lyric-end").value = audio.currentTime.toFixed(3); });
$("lyric-listen").addEventListener("click", async () => {
  if (dirty()) return error("先保存时间，再试听本句");
  const row = current(); if (row?.start === null) return;
  audio.currentTime = row.start; listenEnd = row.end;
  try { await audio.play(); } catch { error("浏览器无法播放此音频，请换用 MP3 或 WAV"); }
});
function showLive() {
  const row = result?.lines.find(row => row.start !== null && row.start <= audio.currentTime && audio.currentTime < row.end);
  $("live-lyric").textContent = row?.text || "—";
  const id = row?.id ?? null;
  if (id !== playingId) { playingId = id; for (const button of $("lyrics-list").querySelectorAll(".lyric-row")) button.classList.toggle("playing", Number(button.dataset.id) === id); }
}
function playback() {
  if (listenEnd !== null && audio.currentTime >= listenEnd) { audio.pause(); audio.currentTime = listenEnd; listenEnd = null; }
  showLive();
  if (!audio.paused) requestAnimationFrame(playback);
}
audio.addEventListener("play", playback); audio.addEventListener("timeupdate", () => { if (audio.paused) playback(); });
audio.addEventListener("error", () => { if (audio.src) error("音频无法播放，请换用 MP3 或 WAV"); });
$("lyrics-search").addEventListener("input", renderList); $("lyrics-filter").addEventListener("change", renderList);
$("lyrics-undo").addEventListener("click", () => { if (leaveDraft()) update({action:"undo"}); });
$("lyrics-redo").addEventListener("click", () => { if (leaveDraft()) update({action:"redo"}); });
$("lyrics-shift").addEventListener("click", () => { if (leaveDraft()) update({offset:numberValue("lyrics-offset")}); });
$("lyrics-new").addEventListener("click", () => { if (!busy && leaveAllDrafts()) { audio.pause(); location.href = "/lyrics"; } });
$("lyric-next").addEventListener("click", () => {
  if (busy || !leaveDraft()) return;
  const at=result.lines.findIndex(row=>row.id===selected), rows=[...result.lines.slice(at+1),...result.lines.slice(0,at+1)], next=rows.find(row=>!row.reviewed);
  if (!next) return error("全部歌词都已复核");
  $("lyrics-search").value = ""; $("lyrics-filter").value = "all"; choose(next.id, true);
});
for (const id of ["lyrics-lrc","lyrics-srt","lyrics-report"]) $(id).addEventListener("click", event => { if (dirty() || lyricsDirty || busy) { event.preventDefault(); error("先保存本句或应用补充歌词，再下载当前版本"); } });
window.addEventListener("beforeunload", event => { if (dirty() || lyricsDirty) { event.preventDefault(); event.returnValue = ""; } });
api("/api/status").then(state => {
  token = state.token; refreshRecentAudio();
  const requested = new URLSearchParams(location.search).get("job");
  if (requested && /^[a-f0-9]{16}$/.test(requested)) { job = requested; $("lyrics-welcome").classList.add("hidden"); $("lyrics-progress").classList.remove("hidden"); poll(); }
}).catch(failure => error(failure.message));

$("wave-span").addEventListener("change",()=>{waveform.span=Number($("wave-span").value);const row=current();if(row)waveform.focus(row.start,row.end,result.metadata.duration);});
$("lyric-split").addEventListener("click",()=>{if(dirty())return error("先保存修改，再拆分本句");const at=[...$("lyric-edit").value.slice(0,$("lyric-edit").selectionStart)].length;update({action:"split",id:selected,at,time:audio.currentTime});});
$("lyric-merge").addEventListener("click",()=>{if(leaveDraft())update({action:"merge",id:selected});});
$("lyric-delete").addEventListener("click",()=>{if(!busy&&leaveDraft()&&window.confirm("删除这句字幕？保存后仍可撤销恢复。"))update({action:"delete",id:selected});});
$("lyric-range").addEventListener("click",()=>{if(dirty())return error("先保存文字修改，再重新对齐本句");update({action:"align-range",id:selected,start:numberValue("range-start"),end:numberValue("range-end")});});
$("lyrics-retry").addEventListener("click",async()=>{try{$("lyrics-retry").disabled=true;await api(`/api/lyrics/${job}/retry`,{method:"POST"});$("lyrics-welcome").classList.add("hidden");poll();}catch(failure){error(failure.message);}finally{$("lyrics-retry").disabled=false;}});
async function refreshRecentAudio(){
  try{const rows=await api("/api/lyrics");$("lyrics-history").replaceChildren();for(const row of rows){const a=document.createElement("a");a.href=`/lyrics?job=${row.id}`;a.className="history-item";const name=document.createElement("span");name.textContent=row.name;const state=document.createElement("small");state.textContent=({ready:"继续编辑",error:"处理未完成",running:"识别中",queued:"等待中"})[row.status]||row.status;a.append(name,state);a.addEventListener("click",event=>{if(!leaveAllDrafts())event.preventDefault();});$("lyrics-history").append(a);}if(!rows.length)$("lyrics-history").textContent="暂无音频记录";}catch(_){$("lyrics-history").textContent="暂时无法读取最近音频";}
}

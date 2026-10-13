"use strict";
const $ = id => document.getElementById(id);
const escapeHTML = text => String(text ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
let token="",jobId="",result=null,selectedId=1,mode="C",pollTimer=null,busy=false,jobWorking=false,drawMode=false,drag=null,demoAvailable=false,movingDemoAvailable=false;
let pendingNavigation=null,cueStop=null,replacePreview=null,pollFailures=0;
const video=$("video"),stage=$("stage"),caption=$("caption");
const descriptions={A:"原始文字 · 下方固定",B:"词表纠错 + 常规避让",C:"同时间画面纠词 + 避让"};
function toast(message,error=false){$("toast").textContent=message;$("toast").classList.toggle("error",error);$("toast").classList.remove("hidden");clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("toast").classList.add("hidden"),5500);}
async function api(url,options={}){const response=await fetch(url,{...options,headers:{"X-Muzhun-Token":token,...options.headers}});let data;try{data=JSON.parse(await response.text());}catch(_){const error=new Error("服务暂时无法响应，请稍后重试或刷新页面");error.status=response.status;throw error;}if(!response.ok){const error=new Error(typeof data.detail==="string"?data.detail:"操作失败，请检查输入");error.status=response.status;throw error;}return data;}
function post(url,data){return api(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});}
function fileURL(name){return "/api/jobs/"+jobId+"/files/"+name;}
function clock(seconds){seconds=Math.max(0,Math.floor(seconds||0));return String(Math.floor(seconds/60)).padStart(2,"0")+":"+String(seconds%60).padStart(2,"0");}
function currentCue(){return result?.cues.find(c=>c.id===selectedId);}
function activeCue(){return result?.cues.find(c=>c.start<=video.currentTime&&c.end>video.currentTime);}
function activePlacement(cue,variant=mode){return cue&&result.plans[variant].find(p=>p.id===cue.id&&p.start<=video.currentTime&&p.end>video.currentTime);}
function rectStyle(rect){return "left:"+rect[0]*100+"%;top:"+rect[1]*100+"%;width:"+(rect[2]-rect[0])*100+"%;height:"+(rect[3]-rect[1])*100+"%";}
function lockEditor(){const locked=busy||jobWorking;document.querySelectorAll(".inspector button,.inspector input,.inspector textarea,.inspector select,.edit-tools button,.workspace-actions button,#history-list button,#cue-list button,#replace-open,#next-review,#cue-search,#cue-filter,#replace-dialog button,#replace-dialog input,#replace-dialog select").forEach(el=>el.disabled=locked);$("start-button").disabled=locked;$("demo-button").disabled=locked||!demoAvailable;$("moving-demo-button").disabled=locked||!movingDemoAvailable;$("undo-button").disabled=locked||!result?.history?.undo;$("redo-button").disabled=locked||!result?.history?.redo;$("next-review").disabled=locked||!result?.cues.some(c=>!c.reviewed);$("replace-apply").disabled=locked||!replacePreview||!$("replace-list").querySelector("input:checked");syncDraft();}
function hasDraft(){const cue=currentCue();return Boolean(cue&&($("edited-text").value!==cue.text||!$("edit-start").value||!$("edit-end").value||Number($("edit-start").value)!==cue.start||Number($("edit-end").value)!==cue.end));}
function syncDraft(){const cue=currentCue(),dirty=hasDraft();$("draft-status").textContent=dirty?"未保存":"已保存";$("draft-status").classList.toggle("dirty",dirty);$("save-cue-button").disabled=busy||jobWorking||!dirty;$("mark-reviewed").textContent=cue?.reviewed?"取消已复核":"标记已复核";$("mark-reviewed").disabled=busy||jobWorking||!cue||dirty||mode!=="C"||Boolean(cue.pending&&!cue.reviewed);$("mark-reviewed").title=mode!=="C"?"请切到画面联动模式复核":cue?.pending?"先采用纠词建议或保留原词":"听音并检查画面后，标记这条字幕";}
async function guardDraft(action){if(hasDraft()){pendingNavigation=action;if(!$("draft-dialog").open)$("draft-dialog").showModal();return;}try{await action();}catch(error){toast(error.message,true);}}
async function saveCue(){
  const cue=currentCue();if(!cue)return false;
  if(!$("edit-start").value||!$("edit-end").value){toast("请填写开始和结束时间",true);return false;}
  const edit={...(result.edits?.[String(cue.id)]||{}),text:$("edited-text").value,start:Number($("edit-start").value),end:Number($("edit-end").value)};
  return revise({edits:{[String(cue.id)]:edit}});
}
function clearExportLinks(){["video-download","blind-key","review-link"].forEach(id=>$(id).classList.add("hidden"));}
function updateLinks(){
  $("ass-link").href=fileURL("subtitles-"+mode+".ass");$("srt-link").href=fileURL("subtitles-"+mode+".srt");
  $("report-link").href=fileURL("result.json");$("annotation-link").href=fileURL("annotations-template.json");$("blind-key").href=fileURL("blind-key.json");
  $("mode-description").textContent=descriptions[mode];
  const estimate=result?.estimates[mode];$("mode-estimate").textContent=estimate?"遮挡估算 "+estimate.focus_overlap_seconds+" 秒 · 换位 "+(estimate.within_cue_changes||0)+" 次":"";
}
function renderLayout(){
  const cue=currentCue();if(!cue)return;
  const segments=result.plans[mode].filter(p=>p.id===cue.id);
  $("layout-note").textContent=segments.length>1?"共 "+segments.length+" 段位置，点击预览。":segments[0]?.label==="手动锁定"?"位置已锁定。":segments[0]?.needs_review?"请检查本句遮挡。":"本句保持一个位置。";
  $("layout-timeline").innerHTML=segments.map((p,i)=>'<button class="layout-step" data-segment="'+i+'"><span>'+p.start.toFixed(2)+'–'+p.end.toFixed(2)+' 秒 · '+escapeHTML(p.label)+'</span>'+(p.needs_review?'<small>需复核</small>':'')+'</button>').join("");
  $("layout-timeline").querySelectorAll("[data-segment]").forEach(button=>button.addEventListener("click",()=>{const p=segments[Number(button.dataset.segment)];video.pause();video.currentTime=p.start+Math.min(.03,(p.end-p.start)/2);paint();}));
}
function filteredCues(){const search=$("cue-search").value.trim().toLocaleLowerCase(),filter=$("cue-filter").value;return result?.cues.filter(c=>(!search||(c.text+" "+c.original).toLocaleLowerCase().includes(search))&&(filter==="all"||filter==="unreviewed"&&!c.reviewed||filter==="reviewed"&&c.reviewed||filter==="issues"&&(c.pending||c.layout_review||c.recognition_review&&!c.reviewed)))||[];}
function renderCueList(){
  if(!result)return;
  const cues=filteredCues();
  $("cue-total").textContent=cues.length===result.cues.length?cues.length+" 条":cues.length+" / "+result.cues.length+" 条";
  $("review-progress").textContent="已复核 "+result.cues.filter(c=>c.reviewed).length+" / "+result.cues.length+" 条";
  $("cue-list").innerHTML=cues.length?cues.map(c=>'<button class="cue-row '+(c.id===selectedId?"active":"")+'" data-cue="'+c.id+'"><span class="cue-index">'+String(c.id).padStart(2,"0")+'</span><span class="cue-copy"><strong class="'+(c.text!==c.original?"changed":"")+'">'+escapeHTML(c.text)+'</strong>'+(c.text!==c.original?'<small>原文：'+escapeHTML(c.original)+'</small>':"")+'<span class="cue-time">'+clock(c.start)+" — "+clock(c.end)+'</span></span><span class="cue-status '+(c.pending||c.layout_review&&!c.reviewed?"pending":c.reviewed?"reviewed":"")+'">'+(c.pending?"纠词待确认":c.reviewed?"已复核":c.layout_review?"检查遮挡":c.recognition_review?"识别待试听":"未复核")+"</span></button>").join(""):'<div class="empty-history" style="padding:20px">没有符合条件的字幕。</div>';
  $("cue-list").querySelectorAll("[data-cue]").forEach(button=>button.addEventListener("click",()=>guardDraft(()=>selectCue(Number(button.dataset.cue),true))));
}
function renderInspector(){
  const cue=currentCue();if(!cue)return;
  $("selected-number").textContent="第 "+cue.id+" 条";$("original-text").textContent=cue.original;$("recognition-note").classList.toggle("hidden",!cue.recognition_review||cue.reviewed);
  $("edited-text").value=cue.text;$("edit-start").value=cue.start;$("edit-end").value=cue.end;
  const decisions=result.edits?.[String(cue.id)]?.decisions||{};
  $("proposal-list").innerHTML=cue.proposals.map((p,i)=>{
    const key=p.key||String(i),decision=decisions[key]||decisions[String(i)]||p.decision;
    return '<div class="proposal"><div><del>'+escapeHTML(p.from)+'</del><span>→</span><strong>'+escapeHTML(p.to)+'</strong><span class="proposal-state">'+({accepted:"已采用",pending:"待确认",rejected:"已拒绝"}[decision]||"待确认")+'</span></div><small>'+escapeHTML(p.reason)+'</small><div class="proposal-actions"><button data-decision="accepted" data-proposal="'+key+'">采用</button><button data-decision="rejected" data-proposal="'+key+'">保留原词</button></div></div>';
  }).join("");
  $("proposal-list").querySelectorAll("[data-decision]").forEach(button=>button.addEventListener("click",async()=>{
    await guardDraft(()=>{
      const edit={...(result.edits?.[String(cue.id)]||{})},proposal=cue.proposals.find(p=>(p.key||String(cue.proposals.indexOf(p)))===button.dataset.proposal);
      if(typeof edit.text==="string"&&proposal){
        const from=button.dataset.decision==="accepted"?proposal.from:proposal.to,to=button.dataset.decision==="accepted"?proposal.to:proposal.from;
        let pattern=from.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
        if(/^[A-Za-z0-9_]/.test(from))pattern="(?<![A-Za-z0-9_])"+pattern;if(/[A-Za-z0-9_]$/.test(from))pattern+="(?![A-Za-z0-9_])";
        edit.text=edit.text.replace(new RegExp(pattern,"g"),()=>to);
      }
      edit.decisions={...(edit.decisions||{}),[button.dataset.proposal]:button.dataset.decision};return revise({edits:{[String(cue.id)]:edit}});
    });
  }));
  let evidence=cue.proposals.flatMap(p=>p.evidence).concat(cue.bindings);
  const unique=new Map();evidence.forEach(item=>unique.set(item.term+"|"+item.image,item));evidence=[...unique.values()].slice(0,3);
  $("evidence-panel").innerHTML=evidence.length?evidence.map(item=>'<div class="evidence-heading"><span>'+escapeHTML(item.screen_text)+'</span><span>'+clock(item.time)+'</span></div><div class="evidence-frame"><img src="'+fileURL(item.image)+'" alt="'+escapeHTML(item.screen_text)+'"><div class="evidence-box" style="'+rectStyle(item.rect)+'"></div></div>').join(""):'<p class="evidence-caption" style="margin-top:12px">未找到画面文字，请听音确认。</p>';
  renderLayout();syncDraft();
}
function selectCue(id,seek=false){cueStop=null;selectedId=id;if(seek){video.pause();video.currentTime=currentCue().start+Math.min(.03,(currentCue().end-currentCue().start)/2);}renderCueList();renderInspector();paint();lockEditor();}
function loadResult(data,name){
  result=data;$("welcome").classList.add("hidden");$("workspace").classList.remove("hidden");
  $("job-title").textContent=name||"字幕工作台";$("demo-warning").classList.toggle("hidden",!result.demo);
  const source=fileURL(result.metadata.filename);
  if(video.dataset.source!==source){video.src=source;video.dataset.source=source;video.load();}
  stage.style.aspectRatio=result.metadata.width+"/"+result.metadata.height;
  $("duration").textContent=clock(result.metadata.duration);$("seek").max=result.metadata.duration;
  $("profile-label").textContent=result.profile.label;
  $("profile-evidence").textContent=result.profile.source==="user"?"你指定的题材":result.profile.evidence.map(h=>h.text).slice(0,3).join(" · ")||"依据不足，可手动指定";
  $("source-note").textContent="记录 v"+result.version+" · 修订 "+(result.revision||0)+" · "+(result.asr.engine==="provided-srt"?"文字与时间来自导入 SRT":(result.asr.model||"未知")+" 语音识别");
  $("correction-count").textContent=result.summary.corrections;$("binding-count").textContent=result.summary.bindings;$("pending-count").textContent=result.summary.pending;
  $("style-select").value=result.settings.style;$("font-select").value=result.settings.font;$("profile-select").value=result.settings.profile;
  $("position-policy").value=result.settings.position_policy||"adaptive";
  $("font-scale").value=result.settings.font_scale;$("font-scale-label").textContent=Number(result.settings.font_scale).toFixed(2)+"×";
  if(!result.cues.some(c=>c.id===selectedId))selectedId=result.cues[0].id;
  renderCueList();renderInspector();updateLinks();paint();lockEditor();
}
function paint(){
  if(!result||drag)return;
  $("current-time").textContent=clock(video.currentTime);$("seek").value=video.currentTime;
  const cue=activeCue(),placement=activePlacement(cue);
  if(!placement){caption.classList.add("hidden");$("region-layer").innerHTML="";return;}
  caption.classList.remove("hidden");caption.textContent=placement.text;
  $("layout-timeline").querySelectorAll("[data-segment]").forEach(b=>b.classList.toggle("active",cue.id===selectedId&&Number(b.dataset.segment)+1===placement.segment_index));
  caption.style.cssText=rectStyle(placement.rect);
  const scale=stage.clientWidth/result.metadata.width;
  caption.style.fontSize=placement.font_size*scale+"px";
  caption.style.fontFamily=placement.font==="mono"?'"DengXian","Microsoft YaHei",sans-serif':'"Microsoft YaHei","Noto Sans CJK SC",sans-serif';
  caption.style.fontWeight=placement.font==="bold"?"700":"400";
  caption.style.background=placement.background?"rgba(0,0,0,.56)":"transparent";
  caption.style.borderRadius=placement.background?"4px":"0";
  const stroke=Math.max(1,placement.outline*scale);
  caption.style.textShadow=[[-1,-1],[1,-1],[-1,1],[1,1]].map(([x,y])=>x*stroke+"px "+y*stroke+"px 1px #0c0c0c").join(",");
  if(!$("show-regions").checked){$("region-layer").innerHTML="";return;}
  const sample=placement.samples?.find(s=>s.start<=video.currentTime&&s.end>video.currentTime);
  const bindings=cue.bindings.filter(b=>sample?.image?b.image===sample.image&&b.time===sample.frame_time:Math.abs(b.time-video.currentTime)<=1.05);
  let regions=bindings.map(b=>({...b,class:"focus"}));
  regions=regions.concat((result.settings.regions||[]).filter(r=>(r.start??0)<=video.currentTime&&(r.end??Infinity)>=video.currentTime).map(r=>({...r,class:"custom"})));
  const seen=new Set();regions=regions.filter(r=>{const key=r.rect.map(v=>v.toFixed(2)).join(",")+"|"+r.label;if(seen.has(key))return false;seen.add(key);return true;});
  const labels=new Set();
  $("region-layer").innerHTML=regions.map(r=>{const label=r.label||r.term||"保护区域",show=!labels.has(label);labels.add(label);return '<div class="region '+r.class+'" style="'+rectStyle(r.rect)+'">'+(show?'<span>'+escapeHTML(label)+"</span>":"")+"</div>";}).join("");
}
async function revise(payload){
  return mutate("revise",payload,"已保存并更新布局");
}
async function mutate(action,payload,message){
  if(busy||jobWorking){toast("请等待当前操作完成");return;}
  video.pause();cueStop=null;busy=true;lockEditor();
  try{const data=await post("/api/jobs/"+jobId+"/"+action,{...payload,revision:result?.revision||0});loadResult(data,$("job-title").textContent);clearExportLinks();toast(message);return true;}
  catch(error){toast(error.message,true);return false;}finally{busy=false;lockEditor();}
}
async function refreshHistory(){
  try{const jobs=await api("/api/jobs");$("history-list").innerHTML=jobs.length?jobs.map(job=>'<button class="history-item" data-job="'+job.id+'"><span>'+escapeHTML(job.name)+'</span><small>'+({ready:"可打开",error:"处理失败",running:"处理中",queued:"等待中",exporting:"导出中"}[job.status]||"可查看")+"</small></button>").join(""):'<span class="empty-history">还没有处理过视频。</span>';$("history-list").querySelectorAll("[data-job]").forEach(button=>button.addEventListener("click",()=>guardDraft(()=>openJob(button.dataset.job))));}
  catch(error){toast(error.message,true);}
}
async function openJob(id){
  video.pause();cueStop=null;pollFailures=0;clearTimeout(pollTimer);result=null;jobId=id;selectedId=1;$("cue-search").value="";$("cue-filter").value="all";history.replaceState(null,"","/?job="+id);clearExportLinks();await pollJob(true);
}
async function pollJob(first=false){
  try{
    const state=await api("/api/jobs/"+jobId);
    pollFailures=0;
    const running=["queued","running","exporting"].includes(state.status);
    jobWorking=running;
    $("progress-panel").classList.toggle("hidden",!running && state.status!=="error");
    $("retry-job").classList.toggle("hidden",state.status!=="error" || !state.request);
    $("progress-title").textContent=state.status==="exporting"?"正在导出":"正在核对与排版";
    $("progress-message").textContent=state.message;$("progress-percent").textContent=Math.round(state.progress*100)+"%";$("progress-bar").style.width=Math.round(state.progress*100)+"%";
    lockEditor();
    if(state.result&&(!result||first||result.version!==state.result.version||state.status==="ready"&&!$("workspace").classList.contains("hidden")&&result.metadata.filename!==state.result.metadata.filename)){
      loadResult(state.result,state.name);if(first){video.currentTime=result.cues[0].start+0.03;}
    }else if(state.result&&$("workspace").classList.contains("hidden")){loadResult(state.result,state.name);video.currentTime=result.cues[0].start+0.03;}
    if(running){pollTimer=setTimeout(()=>pollJob(),1200);return;}
    if(state.error)toast(state.message,true);
    if(state.export_url){const kind=state.export_kind||(state.export_url.endsWith("blind-test.zip")?"blind":"video");$("video-download").href=state.export_url;$("video-download").textContent=kind==="blind"?"↓ 下载朋友盲测包":kind==="delivery"?"↓ 下载完整交付包":"↓ 下载导出视频";$("video-download").classList.remove("hidden");$("blind-key").classList.toggle("hidden",kind!=="blind");if(state.review_url){$("review-link").href=state.review_url;$("review-link").textContent=kind==="blind"?"预览朋友测试页 ↗":"打开交付复核页 ↗";$("review-link").classList.remove("hidden");}}
    await refreshHistory();
    lockEditor();
  }catch(error){if(jobWorking&&(error.status>=500||!error.status)&&++pollFailures<=3){$("progress-message").textContent="暂时无法读取进度，正在重连…";pollTimer=setTimeout(()=>pollJob(first),1800);return;}jobWorking=false;lockEditor();$("progress-panel").classList.add("hidden");toast(error.message,true);}
}
$("upload-form").addEventListener("submit",async event=>{
  event.preventDefault();const file=$("video-input").files[0];if(!file)return;if(file.size>2*1024**3){toast("视频最大 2 GB，请压缩文件后重试",true);return;}
  $("start-button").disabled=true;
  try{result=null;$("workspace").classList.add("hidden");$("welcome").classList.add("hidden");$("progress-panel").classList.remove("hidden");$("retry-job").classList.add("hidden");$("progress-title").textContent="正在导入视频";
    const data=await MuzhunUI.upload("/api/jobs",new FormData(event.currentTarget),token,value=>{$("progress-percent").textContent=Math.round(value*100)+"%";$("progress-bar").style.width=value*100+"%";$("progress-message").textContent="文件导入本机处理环境，完成后开始识别";});await openJob(data.id);}catch(error){toast(error.message,true);$("start-button").disabled=false;$("welcome").classList.remove("hidden");$("progress-panel").classList.add("hidden");}
});
async function openDemo(kind){
  if(busy||jobWorking)return;busy=true;lockEditor();
  try{result=null;$("workspace").classList.add("hidden");const data=await post("/api/demo",{kind});await openJob(data.id);}catch(error){toast(error.message,true);}finally{busy=false;lockEditor();}
}
$("demo-button").addEventListener("click",()=>openDemo("standard"));
$("moving-demo-button").addEventListener("click",()=>openDemo("moving"));
$("video-input").addEventListener("change",()=>{$("file-label").textContent=$("video-input").files[0]?.name||"选择视频，或拖到这里";});
$("dropzone").addEventListener("dragover",()=>{$("dropzone").classList.add("dragover");});
["dragleave","drop"].forEach(event=>$("dropzone").addEventListener(event,()=>$("dropzone").classList.remove("dragover")));
$("new-button").addEventListener("click",()=>guardDraft(()=>{video.pause();cueStop=null;clearTimeout(pollTimer);result=null;jobId="";history.replaceState(null,"","/");$("workspace").classList.add("hidden");$("progress-panel").classList.add("hidden");$("welcome").classList.remove("hidden");lockEditor();window.scrollTo({top:0,behavior:"smooth"});}));
document.querySelectorAll("[data-mode]").forEach(button=>button.addEventListener("click",()=>{mode=button.dataset.mode;document.querySelectorAll("[data-mode]").forEach(b=>b.classList.toggle("selected",b===button));updateLinks();renderLayout();paint();syncDraft();}));
$("show-regions").addEventListener("change",paint);
$("cue-search").addEventListener("input",()=>{renderCueList();lockEditor();});$("cue-filter").addEventListener("change",()=>{renderCueList();lockEditor();});
$("play-button").addEventListener("click",async()=>{cueStop=null;if(video.paused){try{await video.play();}catch(error){toast("视频无法预览，请先检查格式或导出 MP4",true);}}else video.pause();});
$("play-cue-button").addEventListener("click",async()=>{const cue=currentCue();if(!cue)return;video.pause();cueStop=cue.end;video.currentTime=cue.start;try{await video.play();}catch(error){cueStop=null;toast("无法试听，请检查视频格式",true);}});
function stopAtCueEnd(){if(cueStop!==null){if(video.currentTime>=cueStop){const end=cueStop;cueStop=null;video.pause();video.currentTime=end;paint();}else if(!video.paused)requestAnimationFrame(stopAtCueEnd);}}
video.addEventListener("play",()=>{if(cueStop!==null)requestAnimationFrame(stopAtCueEnd);});
$("next-review").addEventListener("click",()=>guardDraft(()=>{const start=result.cues.findIndex(c=>c.id===selectedId),ordered=[...result.cues.slice(start+1),...result.cues.slice(0,start+1)],cue=ordered.find(c=>!c.reviewed);if(cue){$("cue-search").value="";if(!["all","unreviewed"].includes($("cue-filter").value))$("cue-filter").value="unreviewed";selectCue(cue.id,true);}}));
$("mark-reviewed").addEventListener("click",()=>{const cue=currentCue();if(cue&&!hasDraft())mutate("review",{ids:[cue.id],reviewed:!cue.reviewed},cue.reviewed?"已取消复核记录":"已记录本句人工复核");});
$("undo-button").addEventListener("click",()=>guardDraft(()=>mutate("history",{action:"undo"},"已撤销；可点击重做恢复")));
$("redo-button").addEventListener("click",()=>guardDraft(()=>mutate("history",{action:"redo"},"已重做")));
video.addEventListener("play",()=>{$("play-button").textContent="Ⅱ";});video.addEventListener("pause",()=>{$("play-button").textContent="▶";});
video.addEventListener("loadedmetadata",()=>{document.querySelector(".stage-empty").classList.add("hidden");paint();});video.addEventListener("error",()=>toast("浏览器无法播放该格式，仍可导出带字幕的 MP4",true));
video.addEventListener("timeupdate",()=>{if(cueStop!==null&&video.currentTime>=cueStop)stopAtCueEnd();paint();});video.addEventListener("seeked",paint);new ResizeObserver(paint).observe(stage);
$("seek").addEventListener("input",()=>{cueStop=null;video.currentTime=Number($("seek").value);paint();});
$("mute-button").addEventListener("click",()=>{video.muted=!video.muted;$("mute-button").textContent=video.muted?"静音":"声音";});
$("save-cue-button").addEventListener("click",saveCue);
function guardedRevise(payload){return guardDraft(()=>revise(payload));}
$("style-select").addEventListener("change",()=>guardedRevise({settings:{style:$("style-select").value,font:$("style-select").value==="gaming"?"bold":"sans"}}));
$("font-select").addEventListener("change",()=>guardedRevise({settings:{font:$("font-select").value}}));
$("profile-select").addEventListener("change",()=>guardedRevise({settings:{profile:$("profile-select").value}}));
$("position-policy").addEventListener("change",()=>guardedRevise({settings:{position_policy:$("position-policy").value}}));
$("font-scale").addEventListener("input",()=>{$("font-scale-label").textContent=Number($("font-scale").value).toFixed(2)+"×";});
$("font-scale").addEventListener("change",()=>guardedRevise({settings:{font_scale:Number($("font-scale").value)}}));
$("protect-button").addEventListener("click",()=>{drawMode=!drawMode;stage.classList.toggle("drawing",drawMode);$("protect-button").textContent=drawMode?"取消框选":"框选保护区";if(drawMode){video.pause();toast("在画面拖出保护区");}});
$("clear-regions-button").addEventListener("click",()=>guardedRevise({settings:{regions:[]}}));
$("unpin-button").addEventListener("click",()=>{const pins={...result.settings.pins};delete pins[String(currentCue()?.id)];guardedRevise({settings:{pins}});});
function point(event){const box=stage.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))];}
stage.addEventListener("pointerdown",event=>{
  if(!result||busy||jobWorking)return;
  if(hasDraft()){toast("请先保存字幕，再调整画面位置",true);return;}
  if(drawMode){drag={type:"region",start:point(event)};stage.setPointerCapture(event.pointerId);event.preventDefault();}
  else if(event.target===caption&&mode==="C"){const cue=activeCue();if(!cue)return;video.pause();selectCue(cue.id);const placement=activePlacement(cue,"C");drag={type:"caption",start:point(event),rect:[...placement.rect],id:cue.id};stage.setPointerCapture(event.pointerId);event.preventDefault();}
});
stage.addEventListener("pointermove",event=>{
  if(!drag)return;const [x,y]=point(event);
  if(drag.type==="region"){const rect=[Math.min(x,drag.start[0]),Math.min(y,drag.start[1]),Math.max(x,drag.start[0]),Math.max(y,drag.start[1])];$("draw-box").classList.remove("hidden");$("draw-box").style.cssText=rectStyle(rect);drag.final=rect;}
  else{const dx=x-drag.start[0],dy=y-drag.start[1],w=drag.rect[2]-drag.rect[0],h=drag.rect[3]-drag.rect[1];const left=Math.max(.01,Math.min(.99-w,drag.rect[0]+dx)),top=Math.max(.01,Math.min(.99-h,drag.rect[1]+dy));drag.final=[left+w/2,top+h/2];caption.style.left=left*100+"%";caption.style.top=top*100+"%";}
});
stage.addEventListener("pointerup",async()=>{
  if(!drag)return;const finished=drag;drag=null;
  if(finished.type==="region"){drawMode=false;stage.classList.remove("drawing");$("draw-box").classList.add("hidden");$("protect-button").textContent="框选保护区";if(!finished.final||finished.final[2]-finished.final[0]<.01||finished.final[3]-finished.final[1]<.01){paint();return;}const cue=activeCue()||currentCue();await revise({settings:{regions:[...(result.settings.regions||[]),{rect:finished.final,label:"手动保护区",start:cue.start,end:cue.end}]}});}
  else if(finished.final)await revise({settings:{pins:{...result.settings.pins,[String(finished.id)]:finished.final}}});
  paint();
});
stage.addEventListener("pointercancel",()=>{drag=null;$("draw-box").classList.add("hidden");paint();});
async function exportMode(selected){if(!result||busy||jobWorking)return;video.pause();cueStop=null;busy=true;lockEditor();clearExportLinks();try{await post("/api/jobs/"+jobId+"/export",{mode:selected,variant:mode,revision:result.revision||0});await pollJob();}catch(error){toast(error.message,true);}finally{busy=false;lockEditor();}}
$("export-button").addEventListener("click",()=>guardDraft(()=>exportMode(mode)));$("blind-button").addEventListener("click",()=>guardDraft(()=>exportMode("blind")));
$("delivery-button").addEventListener("click",()=>guardDraft(()=>exportMode("delivery")));$("replan-button").addEventListener("click",()=>guardedRevise({}));
for(const id of ["edited-text","edit-start","edit-end"])$(id).addEventListener("input",syncDraft);
window.addEventListener("beforeunload",event=>{if(hasDraft()){event.preventDefault();event.returnValue="";}});
$("edited-text").addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key==="Enter"){event.preventDefault();saveCue();}});
$("draft-stay").addEventListener("click",()=>{pendingNavigation=null;$("draft-dialog").close();});
$("draft-dialog").addEventListener("cancel",()=>{pendingNavigation=null;});
$("draft-discard").addEventListener("click",()=>{const action=pendingNavigation;pendingNavigation=null;$("draft-dialog").close();renderInspector();if(action)guardDraft(action);});
$("draft-save").addEventListener("click",async()=>{if(busy)return;$("draft-save").disabled=true;const saved=await saveCue();$("draft-save").disabled=false;if(saved){const action=pendingNavigation;pendingNavigation=null;$("draft-dialog").close();if(action)guardDraft(action);}});
for(const id of ["srt-link","ass-link","report-link"])$(id).addEventListener("click",event=>{if(!hasDraft())return;event.preventDefault();const href=event.currentTarget.href;guardDraft(()=>{const link=document.createElement("a");link.href=href;link.download="";link.click();});});
$("video-download").addEventListener("click",event=>{if(hasDraft()){event.preventDefault();guardDraft(()=>exportMode(mode));}});
function invalidateReplace(){replacePreview=null;$("replace-list").replaceChildren();$("replace-summary").textContent="只修改字幕正文，保留原文。";$("replace-apply").textContent="应用替换并重新排版";lockEditor();}
$("replace-open").addEventListener("click",()=>guardDraft(()=>{invalidateReplace();$("replace-dialog").showModal();$("replace-find").focus();}));
for(const id of ["replace-find","replace-with","replace-case","replace-whole","replace-scope"])$(id).addEventListener("input",invalidateReplace);
$("replace-preview").addEventListener("click",async()=>{
  if(busy||jobWorking)return;busy=true;lockEditor();
  const payload={find:$("replace-find").value,replace:$("replace-with").value,case_sensitive:$("replace-case").checked,whole_word:$("replace-whole").checked,revision:result.revision||0};
  if($("replace-scope").value!=="all")payload.ids=$("replace-scope").value==="current"?[selectedId]:filteredCues().map(c=>c.id);
  try{const preview=await post("/api/jobs/"+jobId+"/replace-preview",payload);replacePreview={payload,preview};$("replace-summary").textContent=preview.cues?"命中 "+preview.cues+" 条、"+preview.occurrences+" 处。"+(preview.omitted?"显示前 100 条，仅应用勾选条目。":"勾选要修改的字幕。"):"没有命中，请调整查找内容或范围。";$("replace-list").innerHTML=preview.matches.map(m=>'<label class="replace-item"><input type="checkbox" checked data-replace-id="'+m.id+'"><span><strong>第 '+m.id+' 条 · '+m.count+' 处</strong><del>'+escapeHTML(m.before)+'</del><ins>'+escapeHTML(m.after)+'</ins></span></label>').join("");$("replace-list").querySelectorAll("input").forEach(input=>input.addEventListener("change",lockEditor));$("replace-apply").textContent="应用勾选替换并重新排版";}
  catch(error){replacePreview=null;$("replace-list").replaceChildren();$("replace-summary").textContent=error.message;toast(error.message,true);}finally{busy=false;lockEditor();}
});
$("replace-apply").addEventListener("click",async()=>{if(!replacePreview)return;const ids=[...$("replace-list").querySelectorAll("input:checked")].map(input=>Number(input.dataset.replaceId));if(!ids.length)return;const payload={...replacePreview.payload,ids};if(payload.revision!==(result.revision||0)){invalidateReplace();toast("字幕已更新，请重新预览",true);return;}if(await mutate("replace",payload,"已替换 "+ids.length+" 条字幕并更新避让布局")){$("replace-dialog").close();invalidateReplace();}});
$("annotation-input").addEventListener("change",async event=>{const file=event.target.files[0];if(!file)return;try{const data=await post("/api/jobs/"+jobId+"/evaluate",JSON.parse(await file.text()));$("evaluation-result").textContent=Object.entries(data.scores).map(([key,value])=>key+"：术语 "+value.terms_correct+"/"+value.terms_total+"；遮挡 "+value.blocked_seconds+" 秒").join("\n");$("evaluation-result").classList.remove("hidden");toast("人工标注评测已完成");}catch(error){toast(error.message,true);}});
$("help-button").addEventListener("click",()=>$("help-dialog").showModal());$("skill-button").addEventListener("click",()=>$("skill-dialog").showModal());document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>button.closest("dialog").close()));
async function checkEnvironment(){
  $("doctor-summary").textContent="正在检查本机环境…";$("doctor-checks").replaceChildren();$("doctor-models").textContent="";$("doctor-retry").disabled=true;
  try{
    const report=await api("/api/doctor");
    $("doctor-summary").textContent=report.ready?"环境正常。":"请修复以下问题。";
    for(const item of report.checks){const row=document.createElement("div");row.className="doctor-check "+(item.ok?"ok":"failed");const title=document.createElement("strong");title.textContent=(item.ok?"✓ ":"! ")+item.label;const message=document.createElement("span");message.textContent=item.message;row.append(title,message);if(item.hint){const hint=document.createElement("p");hint.textContent=item.hint;row.append(hint);}$("doctor-checks").append(row);}
    $("doctor-models").textContent=report.models_cached.length?"已缓存语音模型："+report.models_cached.join("、"):"尚未缓存语音模型，可以先用内置演示或提供 SRT。";
  }catch(error){$("doctor-summary").textContent="检查失败："+error.message;}finally{$("doctor-retry").disabled=false;}
}
$("doctor-button").addEventListener("click",()=>{$("doctor-dialog").showModal();checkEnvironment();});$("doctor-retry").addEventListener("click",checkEnvironment);
async function init(){try{const status=await api("/api/status");token=status.token;demoAvailable=status.demo_available;movingDemoAvailable=status.moving_demo_available;lockEditor();await refreshHistory();const id=new URLSearchParams(location.search).get("job");if(id)await openJob(id);}catch(error){toast("服务连接失败："+error.message,true);}}
init();

$("retry-job").addEventListener("click",async()=>{try{$("retry-job").disabled=true;await post(`/api/jobs/${jobId}/retry`,{});await pollJob();}catch(error){toast(error.message,true);}finally{$("retry-job").disabled=false;}});

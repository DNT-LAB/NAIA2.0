'use strict';
const $ = id => document.getElementById(id);
let state = null, modelReady = false, posting = false, resetting = false, settingsSaving = false, prefsDirty = false, rendered = '', epoch = 0;
const welcome = $('messages').cloneNode(true);
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
function node(tag, cls, text) { const el=document.createElement(tag); if(cls)el.className=cls; if(text!==undefined)el.textContent=text; return el; }
function rich(text) {
  const div=node('div','content');
  function inline(value){let pos=0;for(const m of value.matchAll(/\*\*([^*\n]+)\*\*|`([^`\n]+)`/g)){div.append(document.createTextNode(value.slice(pos,m.index)),node(m[1]?'strong':'code','',m[1]||m[2]));pos=m.index+m[0].length;}div.append(document.createTextNode(value.slice(pos)));}
  let pos=0;
  for(const m of text.matchAll(/```(?:[a-zA-Z][\w+-]*[ \t]*\r?\n)?([\s\S]*?)```/g)){inline(text.slice(pos,m.index));div.append(node('pre','prompt-code',m[1].trim()));pos=m.index+m[0].length;}
  inline(text.slice(pos));return div;
}
function message(role,text,round) {
  const div=node('div',`bubble ${role}`);div.append(node('div','who',role==='user'?`YOU · R${round}`:'E2B'),role==='user'?node('div','content',text):rich(text));return div;
}
function busy() { return posting || resetting || settingsSaving || state?.busy; }
function controls() { $('send').disabled=!modelReady||busy();$('cancel').hidden=!state?.busy;$('cancel').disabled=!state?.run||state.run.stage==='cancel_requested';$('context-size').disabled=busy()||!state?.context;$('new').disabled=resetting||settingsSaving; }
function render(data) {
  state=data; controls();
  $('round-count').textContent=`${data.rounds.length} rounds`;
  $('summary').textContent=data.summary||'아직 압축된 대화가 없습니다.';
  $('memory').textContent=data.memory||'이번 대화에서 유지할 사실과 할 일';
  if(!prefsDirty) $('preferences').value=data.preferences;
  $('system').textContent=data.system_prompt;
  const run=data.run;
  if(data.context){
    if(!settingsSaving)$('context-size').value=String(data.context.size);
    $('context-budget').textContent=`입력 예산 ${data.context.input_budget.toLocaleString()} · 출력 최대 ${data.context.output_reserve.toLocaleString()} 토큰 예약`;
    const measured=(run?.usage||[]).filter(u=>Number.isFinite(u.input_tokens));
    const peak=measured.reduce((best,u)=>!best||u.input_tokens>best.input_tokens?u:best,null);
    const estimated=(run?.usage||[]).at(-1);
    $('context-usage').textContent=peak?`이번 라운드 최대 입력 ${peak.input_tokens.toLocaleString()} 토큰 · ${(peak.context_size||run.context_size)/1024}K 사용`:(estimated?`호출 전 예상 입력 ${estimated.estimated_input_tokens.toLocaleString()} 토큰`:'실측 토큰 수는 답변 후 표시됩니다.');
    $('context-usage').title='호출 전 예산 검사는 추정치이며 도구·스키마와 출력 여유를 포함합니다. 실측은 Ollama가 반환한 입력 토큰 수입니다.';
  }
  const stages={routing:'의도 추출 준비',intent:'1 · 문장 해석과 장면 제안',grounded_answer:'2 · 검색 근거로 답변 작성',answer_review:'3 · 원문 조건과 답변 대조',answer_revision:'조건을 반영해 답변 수정',fallback_answer:'일반 답변 재생성',answer:'답변 작성',compacting:'원문 기반 대화 압축',completed:'완료',failed:'실패',cancel_requested:'중단 요청됨 · 현재 모델 호출 종료 대기',cancelled:'중단됨'};
  $('progress').textContent=data.busy?(run?`${stages[run.stage]||run.stage} · ${run.elapsed}s`:'이전 모델 호출 종료 대기 · 새 대화 내용은 비워졌습니다.'):(run?.error?run.error:(data.rounds.length?'직전 라운드 원문 유지 · 이전 대화 압축 완료':'메시지를 입력하세요.'));
  $('intent').textContent=run?.route?.goal?`${run.route.route} · ${run.route.goal}\n${[...(run.route.constraints||[]),...(run.route.source_constraints||[])].join(' · ')}`:'메시지를 보내면 목적과 조건이 표시됩니다.';
  if(run?.route?.must_keep?.length)$('intent').textContent+='\n유지: '+run.route.must_keep.map(r=>r.quote||r.en).join(' · ');
  if(run?.route?.may_choose?.length){const labels={stance:'자세',body_orientation:'몸 방향',hand_placement:'양손 위치',camera:'시점',lighting:'조명',background:'배경',expression:'표정'};$('intent').textContent+='\n선택 가능: '+run.route.may_choose.map(k=>labels[k]||k).join(' · ');}
  if(run?.route?.design)$('intent').textContent+='\n선택한 자세: '+run.route.design.summary_ko;
  if(run?.route?.scene_proposal_en)$('intent').textContent+='\n장면 제안: '+run.route.scene_proposal_en;
  if(run?.route?.catalog_stats){const c=run.route.catalog_stats;$('intent').textContent+=`\n참고 태그 ${c.visible}개 · 확장 후보 ${c.discovery}개`;}
  if(run?.route?.review){const r=run.route.review;const labels={model_pass:'발견된 문제 없음',unresolved:'미해결 조건 있음',unavailable:'점검 미완료'};$('intent').textContent+=`\n모델 조건 점검 · ${labels[r.status]||r.status}${r.repairs?' · 1회 수정':''}`;}
  if(run?.fallback_used)$('intent').textContent+='\n일반 답변으로 전환 · 최종 태그·구도 미검증';
  if(run?.route?.grounding){const g=run.route.grounding;const label={queried:'조회 완료',partial:'일부 조회 오류',no_matches:'일치 관측 없음',error:'조회 오류',unavailable:'사용 불가',no_valid_pins:'유효한 검색 태그 없음',budget_exhausted:'도구 한도 도달'};$('intent').textContent+=`\nEvent Map · ${g.event_queries}회 · ${label[g.status]||g.status}${g.pins?.length?' · '+g.pins.join(', '):''}`;}
  if(run?.route?.scene){const scene=run.route.scene;$('intent').textContent+='\n'+scene.relations.map(r=>`${r.subject.quote} → ${r.action.quote} → ${r.target.quote || '(대상 없음)'}${r.instrument.quote?' · 도구: '+r.instrument.quote:''}`).join('\n');$('intent').textContent+='\n'+scene.details.map(d=>d.quote).join(' · ');}
  $('call-count').textContent=`${run?.usage?.length||0} calls`;
  const traceKey=JSON.stringify([run?.trace||[],run?.validation||[]]);
  if($('trace').dataset.key!==traceKey){$('trace').replaceChildren();$('trace').dataset.key=traceKey;for(const t of run?.trace||[]){const d=node('details');d.append(node('summary','',`${t.status==='error'?'!':'↗'} ${t.name}`),node('pre','',JSON.stringify({arguments:t.arguments,result:t.result},null,2)));$('trace').append(d);}for(const v of run?.validation||[]){const d=node('details');d.append(node('summary','','조건 검사 · '+v.stage),node('pre','',v.issue));$('trace').append(d);}}
  const key=JSON.stringify([data.session_id,data.rounds,run?.id,run?.answer,run?.status]);
  if(key!==rendered){rendered=key;const log=$('messages');const nearBottom=log.scrollHeight-log.scrollTop-log.clientHeight<150;log.replaceChildren();
    if(!data.rounds.length&&!run)log.append(...welcome.cloneNode(true).childNodes);
    for(const r of data.rounds){log.append(message('user',r.user,r.round_id));const answer=message('assistant',r.assistant||r.error,r.round_id);answer.append(node('div','meta',`R${r.round_id}${r.fallback_used?' · 일반 답변':''} · ${r.compaction==='source_quotes'?'원문 기반 압축':r.compaction==='model'?'이전 방식 요약':'원문 발췌 대체'}`));
      for(const s of r.preference_suggestions||[]){const b=node('button','suggestion',`선호에 저장: ${s.value}`);b.title=`근거: ${s.evidence}`;b.addEventListener('click',async()=>{b.disabled=true;try{const text=$('preferences').value.trim()+`\n- ${s.value}`;await api('/api/preferences',{text});$('preferences').value=text;prefsDirty=false;b.textContent='선호 저장됨';}catch(e){$('error').textContent=e.message;b.disabled=false;}});answer.append(b);}log.append(answer);}
    if(run&& !['completed','failed'].includes(run.status)){log.append(message('user',run.text||'처리 중인 메시지',data.rounds.length+1));if(run.answer)log.append(message('assistant',run.answer,data.rounds.length+1));}
    if(nearBottom)log.scrollTop=log.scrollHeight;
  }
  if(data.assets){const assets=$('assets');assets.replaceChildren();if(data.assets.loading)assets.append(node('div','muted','검색 색인을 읽는 중…'));for(const [label,item] of [['TagSearchIndex',data.assets.tag_index],['Event Map',data.assets.event_map]]){const row=node('div','asset-row');row.append(node('span','',label),node('span','',item?.ready?`${(item.count||item.tags||0).toLocaleString()} tags`:item?.error?'사용 불가':'준비 중'));if(item?.error)row.title=item.error;assets.append(row);}assets.append(node('div','asset-row','Fast Search · 6 sources'));}
}
async function refresh(){const ticket=epoch;try{const data=await api('/api/state');if(ticket===epoch)render(data);}catch(e){$('error').textContent=e.message;}}
async function model(){try{const data=await api('/api/model');modelReady=!!data.ready;$('model-status').textContent=data.ready?data.model:'Ollama 연결 또는 E2B 모델을 확인하세요.';$('model-dot').classList.toggle('ready',modelReady);}catch(e){modelReady=false;$('model-status').textContent=e.message;}controls();}
$('form').addEventListener('submit',async e=>{e.preventDefault();if(busy()||!modelReady)return;const text=$('input').value.trim();if(!text)return;posting=true;controls();$('error').textContent='';try{await api('/api/chat',{message:text,request_id:crypto.randomUUID(),session_id:state.session_id});$('input').value='';await refresh();}catch(err){$('error').textContent=err.message;}finally{posting=false;controls();}});
$('input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('form').requestSubmit();}});
document.addEventListener('click',e=>{const example=e.target.closest('[data-example]');if(example){$('input').value=example.dataset.example;$('input').focus();}});
$('new').addEventListener('click',async()=>{epoch++;resetting=true;controls();$('new').disabled=true;try{await api('/api/new',{});rendered='';$('seek-results').replaceChildren();$('error').textContent='';$('input').value='';await refresh();}catch(e){$('error').textContent=e.message;}finally{resetting=false;controls();$('new').disabled=false;}});
$('cancel').addEventListener('click',async()=>{try{await api('/api/cancel',{});await refresh();}catch(e){$('error').textContent=e.message;}});
$('preferences').addEventListener('input',()=>{prefsDirty=true;$('prefs-status').textContent='미저장';});
$('save-prefs').addEventListener('click',async()=>{try{await api('/api/preferences',{text:$('preferences').value});prefsDirty=false;$('prefs-status').textContent='저장됨';}catch(e){$('prefs-status').textContent=e.message;}});
$('context-size').addEventListener('change',async()=>{
  const previous=state?.context?.size;
  if(busy()||!previous){$('context-size').value=String(previous||8192);return;}
  const requested=Number($('context-size').value);
  settingsSaving=true;epoch++;controls();$('context-status').textContent='설정 저장 중…';
  try{const data=await api('/api/settings',{context_size:requested});epoch++;render(data);$('context-status').textContent=`${requested/1024}K 저장됨 · 다음 메시지부터 적용`;}
  catch(e){$('context-status').textContent=`변경되지 않았습니다: ${e.message}`;}
  finally{settingsSaving=false;$('context-size').value=String(state?.context?.size||previous);controls();}
});
$('seek-form').addEventListener('submit',async e=>{e.preventDefault();const ticket=epoch;const q=$('seek-input').value.trim();const id=/^#\d+$/.test(q)?Number(q.slice(1)):0;try{const d=await api(`/api/seek?query=${encodeURIComponent(id?'':q)}&round_id=${id}`);if(ticket!==epoch)return;$('seek-results').replaceChildren();if(!d.items.length)$('seek-results').append(node('p','muted','일치하는 이전 대화가 없습니다.'));for(const r of d.items)$('seek-results').append(node('div','seek-row',`R${r.round_id}\nYOU: ${r.user}\nE2B: ${r.assistant}`));}catch(e){$('error').textContent=e.message;}});
$('recheck').addEventListener('click',model);
void refresh();void model();setInterval(refresh,900);

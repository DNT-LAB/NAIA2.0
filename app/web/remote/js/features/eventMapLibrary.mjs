/* Immediate save and a separate saved-combination panel. */
/** UUID v4. `crypto.randomUUID` 는 보안 컨텍스트(https/localhost)에만 있어 LAN http(폰)에서는 없다 —
 *  그때는 getRandomValues 로 같은 꼴을 만든다(백엔드가 `uuid.UUID()` 로 검증한다). */
function newUuid() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = new Uint8Array(16);
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) crypto.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map(x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
export function initEventMapLibrary({bar, panel, anchor, getSelection, applySelection, toast, resize, onOpen, onClose}) {
  let items = [], categories = [], query = '', category = '*', opened = false, busy = false, saving = false, ticket = 0;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  panel.className = 'em-overlay em-saved-panel'; document.body.append(panel);
  const saveButton = bar.querySelector('[data-library-mode=save]');
  const loadButton = bar.querySelector('[data-library-mode=load]');
  async function request(body) {
    const res = await fetch('/api/event-map/library', {method: body ? 'POST' : 'GET', cache:'no-store',
      headers:{'Content-Type':'application/json'}, body: body ? JSON.stringify(body) : undefined, signal:AbortSignal.timeout(15000)});
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error(data.message || '요청을 처리하지 못했습니다.');
    return data;
  }
  function position() {
    if (!opened) return;
    const r = anchor.getBoundingClientRect(), available = innerWidth - r.right - 16;
    const width = Math.min(360, innerWidth - 16);
    const left = available >= 240 ? r.right + 8 : Math.max(8, innerWidth - width - 8);
    Object.assign(panel.style,{left:`${left}px`,top:`${Math.max(8,r.top)}px`,width:`${available >= 240 ? Math.min(360,available) : width}px`,
      height:`${Math.max(200,Math.min(innerHeight-r.top-16,Math.max(r.height,420)))}px`});
  }
  function update() { saveButton.disabled = saving || !getSelection().pins.length; position(); }
  function close() { opened=false; ticket++; panel.hidden=true; loadButton.setAttribute('aria-expanded','false'); onClose?.(); resize(); }
  function options(selected, all=false) {
    return (all ? '<option value="*">전체 분류</option>' : '') + `<option value="" ${selected===''?'selected':''}>미분류</option>` +
      categories.map(c=>`<option value="${esc(c)}" ${selected===c?'selected':''}>${esc(c)}</option>`).join('');
  }
  function list() {
    const target=panel.querySelector('.em-library-list'); if(!target)return;
    const visible=items.filter(row=>(category==='*'||row.category===category) &&
      [row.name,...row.selection.pins,...row.selection.exclude].join(' ').toLowerCase().includes(query.toLowerCase()));
    target.innerHTML=visible.length ? visible.map(row=>`<div class="em-saved-item" data-item="${esc(row.id)}">
      <div class="em-library-tags">${esc(row.selection.pins.join(', ')||'인원·등급 조합')}</div>
      ${row.selection.exclude.length ? `<div class="em-saved-exclude">제외: ${esc(row.selection.exclude.join(', '))}</div>`:''}
      <div class="em-library-meta">${esc(row.selection.persons.join(' / ').replaceAll('_',' '))} · ${esc(row.selection.ratings.join(' / ').toUpperCase())}</div>
      <div class="em-library-actions"><button type="button" data-load>불러오기</button><button type="button" data-delete>삭제</button>
      <select data-move aria-label="조합 카테고리">${options(row.category)}</select></div></div>`).join('') : '<div class="em-library-empty">저장된 조합이 없습니다.</div>';
  }
  function draw() {
    panel.innerHTML=`<div class="em-bar"><b>저장된 조합</b><span class="em-status">${items.length}개</span><button type="button" class="em-close" data-close aria-label="닫기">×</button></div>
      <div class="em-saved-controls"><div class="em-library-search"><select data-filter aria-label="분류 선택">${options(category,true)}</select><input data-search placeholder="태그 검색…" aria-label="조합 검색" value="${esc(query)}"></div>
      <form class="em-library-search"><input data-category-name maxlength="60" placeholder="새 분류 이름" aria-label="새 분류 이름" required><button type="submit">분류 추가</button></form></div>
      <div class="em-library-error" role="alert"></div><div class="em-body em-library-list"></div>`;
    panel.querySelector('[data-filter]').value=category;
    list(); position();
  }
  async function open() {
    if(opened){close();return;}
    onOpen?.(); opened=true;panel.hidden=false;loadButton.setAttribute('aria-expanded','true');
    const mine=++ticket;panel.innerHTML='<div class="em-library-empty">불러오는 중…</div>';position();
    try {const data=await request();if(mine!==ticket)return;items=data.items;categories=data.categories||[];draw();}
    catch(error){if(mine===ticket)panel.innerHTML=`<div class="em-library-error">${esc(error.message)}</div><button data-close>닫기</button>`;}
  }
  async function save() {
    if(saving || !getSelection().pins.length)return;
    saving=true;update();
    try {await request({id:newUuid(),selection:getSelection()});toast('저장됨','success');
      if(opened){const data=await request();items=data.items;categories=data.categories||[];draw();}}
    catch(error){toast(error.message,'error');}finally{saving=false;update();}
  }
  async function mutate(body) {
    if(busy)return;
    busy=true;panel.inert=true;
    const mine=ticket;
    try {const data=await request(body);if(mine!==ticket)return;items=data.items;categories=data.categories||[];
      if(body.action==='move')toast(`[${data.previous_category||'미분류'}] 에서 [${data.category||'미분류'}] 으로 이동했습니다.`,'success');
      else if(body.action==='delete')toast('삭제됨','success');
      else {category=body.category;toast('분류를 추가했습니다.','success');}draw();
    }catch(error){toast(error.message,'error');if(opened)draw();}finally{busy=false;panel.inert=false;}
  }
  bar.addEventListener('click',event=>{const mode=event.target.closest('[data-library-mode]')?.dataset.libraryMode;if(mode==='save')void save();else if(mode==='load')void open();});
  panel.addEventListener('input',event=>{if(event.target.matches('[data-search]')){query=event.target.value;list();}});
  panel.addEventListener('change',event=>{if(event.target.matches('[data-filter]')){category=event.target.value;list();}
    if(event.target.matches('[data-move]'))void mutate({action:'move',id:event.target.closest('[data-item]').dataset.item,category:event.target.value});});
  panel.addEventListener('submit',event=>{event.preventDefault();const name=panel.querySelector('[data-category-name]').value.trim();if(name)void mutate({action:'add_category',category:name});});
  panel.addEventListener('click',async event=>{
    if(event.target.closest('[data-close]')){close();return;}
    const id=event.target.closest('[data-item]')?.dataset.item;
    if(event.target.closest('[data-delete]')){void mutate({action:'delete',id});return;}
    if(!event.target.closest('[data-load]')||busy)return;
    const row=items.find(item=>item.id===id);if(!row)return;
    busy=true;panel.inert=true;
    try {await applySelection(row.selection);toast('불러왔습니다.','success');}
    catch(error){toast(error.message,'error');}finally{busy=false;panel.inert=false;}
  });
  panel.addEventListener('keydown',event=>event.stopPropagation());
  update();
  return {close,update,position,contains:target=>panel.contains(target),isOpen:()=>opened};
}

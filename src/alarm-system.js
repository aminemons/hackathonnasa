import {HAZARDS, validateFeed, reconcile, sortedAlertHistory, feedStatus, isValidLocation} from './alarm-core.js';

const KEY = 'terrapulse-source-monitor-v2';
const $ = selector => document.querySelector(selector);
const esc = t => String(t ?? '').replace(/[&<>"']/g, c=>({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
}[c]));
const fromStorage = () => {
  try {return JSON.parse(localStorage.getItem(KEY) || '{}');}
  catch {return {};}
};
const persist = data => {try{localStorage.setItem(KEY,JSON.stringify(data));}catch{}};

export function initializeAlarmSystem(mapAPI) {
  const stored = fromStorage();
  const states = Object.fromEntries(HAZARDS.map(h=>[h.id,{
    on: stored.enabled?.includes(h.id) || false, busy:false, error:'',
    initialized:false, seen: new Set(stored.seen?.[h.id] || []),
    lastSuccess:null, latestCount:0, nextDue:0,
  }]));
  let history=sortedAlertHistory(stored.history||[]);
  let soundEnabled=false;
  let notificationEnabled=false;
  const settings = document.createElement('div');
  settings.id='aGlobal';
  settings.className='tp-alarm-global';
  settings.innerHTML=`<div class="tp-alarm-actions">
    <button type="button" class="btn" id="aAll">Monitor all three</button>
    <button type="button" class="btn tp-outline" id="aRefresh">Check now</button>
    <button type="button" class="btn tp-outline" id="aClear">Clear feed history</button>
  </div>
  <p id="aSafety">Research monitoring only. Earthquake and landslide reports can arrive <strong>after</strong> an event.
  Glacial-lake observations are historical, not real-time alerts. No earthquake prediction,
  GLOF breach forecast, or evacuation advice is provided.</p>
  <p><button type="button" class="btn tp-outline" id="aNotify">Enable browser notifications</button>
  <span id="aNotifyStatus" aria-live="polite">Notifications off</span></p>`;
  $('#aCards').before(settings);

  $('#aCards').innerHTML=HAZARDS.map(h=>`<div class="acard">
    <label class="r" style="flex:1;font-weight:700"><input type="checkbox" id="ac_${h.id}"> ${h.icon} ${h.name}</label>
    ${h.id==='eq'?'<label>Minimum magnitude <input type="number" id="aMag" value="5" min="2" max="9" step="0.5" style="width:74px;display:inline-block"></label>':''}
    <small id="as_${h.id}" class="tp-monitor-state">Off</small>
    <small style="flex-basis:100%;color:var(--m)">${h.source} · every ${h.minutes} min · ${h.id==='eq'?'USGS catalogue, not earthquake prediction':h.id==='gl'?'Dated observations through 2024; NOT a live glacier breach alarm':'NASA EONET reports, not a safety warning'}</small>
  </div>`).join('');

  const audio = $('#aSound');
  if (audio) {audio.checked=false;audio.onchange=()=>{soundEnabled=audio.checked;}}

  function save() {
    const seen=Object.fromEntries(Object.entries(states).map(([k,s])=>[k,[...s.seen].slice(-700)]));
    persist({enabled:Object.entries(states).filter(([,s])=>s.on).map(([k])=>k),
      seen,history:history.slice(0,100)});
  }
  function playSound() {
    if(!soundEnabled)return;
    try {
      const ctx=new (window.AudioContext||window.webkitAudioContext)();
      const osc=ctx.createOscillator(), gain=ctx.createGain();
      osc.connect(gain);gain.connect(ctx.destination);
      osc.frequency.value=620;gain.gain.setValueAtTime(.04,ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+.25);
      osc.start();osc.stop(ctx.currentTime+.26);
      osc.onended=()=>ctx.close();
    }catch{}
  }
  function showNotification(h,event) {
    // Browser notifications are explicitly opt-in and never request
    // permission just by checking a monitor toggle.
    if(h.kind==='historical')return; // Never notify for archival glacier observations.
    if(!notificationEnabled || !window.Notification || Notification.permission!=='granted')return;
    if(Date.now()-event.time>2*60*60*1000)return; // not a "new" event if hours old
    try {
      const notice=new Notification(`${h.icon} New ${h.source} report`,{
        body:event.title+' · Informational catalogue report, not emergency warning',
        tag:'terrapulse-'+h.id+'-'+event.id,
      });
      notice.onclick=()=>{window.focus(); if(isValidLocation(event)) {
        mapAPI.go('Map');mapAPI.map.flyTo([event.lat,event.lon],6);
      }};
    }catch{}
  }

  async function check(h,force=false) {
    const state=states[h.id];
    if(!state.on || state.busy)return;
    const now=Date.now();
    if(!force && now<state.nextDue)return;
    state.busy=true;state.error='';render();
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),18000);
    try {
      const params=new URLSearchParams({hazard:h.id});
      if(h.id==='eq') params.set('min_magnitude',$('#aMag').value);
      const response=await fetch('/api/events?'+params,{signal:controller.signal,cache:'no-store'});
      if(!response.headers.get('Content-Type')?.includes('application/json'))
        throw Error('API did not return JSON');
      const feed=await response.json();
      if(!response.ok)throw Error(feed.error||'HTTP '+response.status);
      const records=validateFeed(feed,h.id);
      const previouslySeen=states[h.id].seen;
      const reconciled=reconcile(previouslySeen,records,!state.initialized);
      state.initialized=true;
      state.seen=new Set(reconciled.seen);
      state.latestCount=records.length;
      state.lastSuccess=Date.now();
      state.error='';
      history=sortedAlertHistory([...records.map(x=>({...x,hazard:h.id})),...history]);
      if(reconciled.fresh.length) {
        reconciled.fresh.slice(0,8).forEach(event=>{
          showNotification(h,event);
          if(h.kind!=='historical' && event.level!=='observation')playSound();
        });
      }
      save();
    } catch(e) {
      state.error=e.name==='AbortError'?'Timeout':String(e.message||'Service unavailable').slice(0,95);
      // Don't mark as empty, don't clear old reports, don't fabricate alerts.
    }finally{
      clearTimeout(timeout);state.busy=false;
      state.nextDue=Date.now()+h.minutes*60000;
      render();
    }
  }

  function setWatching(id,on) {
    const state=states[id],h=HAZARDS.find(x=>x.id===id);
    if(!state||!h)return;
    if(on && !state.on) {
      state.on=true;state.initialized=false;state.nextDue=0;state.error='';
      check(h,true);
    }else if(!on) {
      state.on=false;state.nextDue=0;state.error='';state.initialized=false;
    }
    save();render();
  }
  HAZARDS.forEach(h=>{$('#ac_'+h.id).onchange=e=>setWatching(h.id,e.target.checked);});
  $('#aAll').onclick=()=>{const anyOff=HAZARDS.some(h=>!states[h.id].on);
    HAZARDS.forEach(h=>setWatching(h.id,anyOff));};
  $('#aRefresh').onclick=()=>{
    HAZARDS.filter(h=>states[h.id].on).forEach(h=>check(h,true));
    if(!HAZARDS.some(h=>states[h.id].on))mapAPI.toast('Enable a hazard monitor first.');
  };
  $('#aClear').onclick=()=>{history=[];save();render();};
  $('#aNotify').onclick=async()=>{
    if(!window.Notification){$('#aNotifyStatus').textContent='This browser does not support notifications';return;}
    try {
      const status=await Notification.requestPermission();
      notificationEnabled=status==='granted';
      $('#aNotifyStatus').textContent=notificationEnabled
        ?'Notifications allowed for new reports while this page is open'
        :status==='denied'?'Blocked by browser settings':'Notifications not enabled';
    }catch{$('#aNotifyStatus').textContent='Permission request failed'}
  };
  $('#aMag').onchange=()=>{
    const magnitude=Number($('#aMag').value);
    if(!Number.isFinite(magnitude)||magnitude<2||magnitude>9) {
      $('#aMag').value='5'; mapAPI.toast('Magnitude must be between 2 and 9');
    }
    const state=states.eq;
    state.initialized=false;state.seen.clear();
    if(state.on){state.nextDue=0;check(HAZARDS[0],true);}
  };

  function itemMarkup(event,index) {
    const h=HAZARDS.find(h=>h.id===event.hazard);
    const date=new Date(event.time);
    const title=event.hazard==='gl'?'Historical glacier/lake measurement':
      event.level==='impact_report'?'USGS high-impact estimate':
      event.level==='notable'?'USGS notable event':'Reported event';
    const loc=isValidLocation(event);
    return `<article class="alert tp-alarm-item" data-event-index="${index}" ${loc?'tabindex="0" role="button"':''}>
      <div><strong>${h.icon} ${esc(h.name)}</strong>
      <span class="tp-alarm-type">${esc(title)}</span></div>
      <p>${esc(event.title)}</p>
      <small>${date.toLocaleString()} · ${esc(event.notes||h.source)} ·
        <a target="_blank" rel="noopener noreferrer" href="${esc(event.url||'#')}">Source</a></small>
      ${loc?'<small class="tp-map-open">Click to locate on map</small>':'<small>Precise map coordinates not supplied</small>'}
    </article>`;
  }
  const filterRecent = (h)=>history.filter(a=>!h||a.hazard===h).slice(0,45);
  function render() {
    HAZARDS.forEach(h=>{
      const state=states[h.id];
      const input=$('#ac_'+h.id);
      if(input)input.checked=state.on;
      const status=$('#as_'+h.id);
      if(status){status.textContent=feedStatus(state);
        status.classList.toggle('tp-source-error',!!state.error);}
    });
    $('#aAll').textContent=HAZARDS.every(h=>states[h.id].on)?'Stop all monitoring':'Monitor all three';
    const alerts=filterRecent();
    $('#aList').innerHTML=alerts.length?alerts.map((x,i)=>itemMarkup(x,i)).join(''):
      '<p class="tp-empty">No source observations retrieved yet. Enable a monitor to start. Existing events will appear without triggering notifications.</p>';
    const focus=mapAPI.getFocusGroup?.();
    const h=HAZARDS.find(h=>h.name===focus)||(focus==='Glaciers & ice'?HAZARDS.find(h=>h.id==='gl'):null);
    const state=h&&states[h.id];
    $('#miniHead').textContent=h? h.icon+' '+h.name+' reports':'Latest source reports';
    $('#miniCtl').innerHTML=h?`<label class="r"><input id="mc" type="checkbox" ${state.on?'checked':''}> Monitor ${esc(h.name)}</label>
      <small class="${state.error?'tp-source-error':''}">${esc(feedStatus(state))}</small>`:
      '<small>Monitoring updates are available on the Alarm page.</small>';
    if(h)$('#mc').onchange=e=>setWatching(h.id,e.target.checked);
    const filtered=filterRecent(h?.id),brief=filtered.slice(0,5);
    $('#miniAlarm').innerHTML=brief.length?brief.map((x)=>itemMarkup(x,history.indexOf(x))).join(''):
      `<p class="tp-empty">${h&&state?.error?'Data unavailable; last checked feed failed':h&&state?.on?'No reported events in the latest successful check':'No reports yet. Enable a monitor on the Alarm page.'}</p>`;
  }
  function clickEvent(e) {
    if(e.target.closest('a'))return;
    const el=e.target.closest('[data-event-index]');
    if(!el)return;
    const a=history[Number(el.dataset.eventIndex)];
    if(a&&isValidLocation(a)) {
      mapAPI.go('Map');mapAPI.map.flyTo([a.lat,a.lon],6,{duration:1});
    }
  }
  $('#aList').onclick=clickEvent;$('#miniAlarm').onclick=clickEvent;
  for(const el of [$('#aList'),$('#miniAlarm')])el.onkeydown=e=>{
    if(e.key==='Enter'||e.key===' ') {e.preventDefault();clickEvent(e);}
  };
  const tick=()=> {
    if(document.hidden)return;
    HAZARDS.filter(h=>states[h.id].on).forEach(h=>check(h));
  };
  const heartbeat=setInterval(tick,30000);
  document.addEventListener('visibilitychange',tick);
  window.addEventListener('online',tick);
  HAZARDS.filter(h=>states[h.id].on).forEach(h=>check(h,true));
  render();
  const api={render,check,setWatching,states,dispose:()=>clearInterval(heartbeat)};
  window.TerraPulseAlarm=api;
  return api;
}

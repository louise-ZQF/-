'use strict';

// ---------- 常量 ----------
const ASSET_LABELS = {
  us_equity:'美股', cn_equity:'A股', hk_equity:'港股', global_equity:'全球股',
  commodity:'商品', bond:'债券', cash:'现金', other:'其他'
};
const ASSET_OPTIONS = Object.keys(ASSET_LABELS);
const ALLOC_COLORS = ['#2563eb','#16a34a','#f59e0b','#db2777','#0891b2','#7c3aed','#64748b','#dc2626'];
const SIG_CLASS = {hard:'sig-hard', pos:'sig-pos', neg:'sig-neg', neutral:'sig-neutral'};

// ---------- 工具 ----------
const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function pct(x, signed=true, digits=2){
  if(x==null || isNaN(x)) return '—';
  const v=(x*100).toFixed(digits);
  return (signed && x>0 ? '+' : '') + v + '%';
}
function pctHtml(x, signed=true, digits=2){
  if(x==null || isNaN(x)) return '<span class="muted">—</span>';
  const cls = x>0?'pos':(x<0?'neg':'muted');
  return `<span class="${cls}">${pct(x,signed,digits)}</span>`;
}
function money(x){ if(x==null||isNaN(x)) return '—'; return '¥'+Number(x).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function num(x, d=4){ return (x==null||isNaN(x))?'—':Number(x).toFixed(d); }

// ---------- 状态 ----------
const state = { mode:'demo', data:null, holdings:[] };

// ---------- 初始化 ----------
function init(){
  $$('#modeSeg .seg-btn').forEach(b=>b.addEventListener('click', ()=>setMode(b.dataset.mode)));
  $$('.tab').forEach(t=>t.addEventListener('click', ()=>setTab(t.dataset.tab)));
  $('#refreshBtn').addEventListener('click', ()=>loadReport());
  $('#addRowBtn').addEventListener('click', ()=>{ state.holdings.push({}); renderRows(); });
  $('#saveBtn').addEventListener('click', saveHoldings);
  $('#loadExampleBtn').addEventListener('click', loadExample);
  $('#modalClose').addEventListener('click', closeModal);
  $('#modal').addEventListener('click', e=>{ if(e.target.id==='modal') closeModal(); });
  loadReport();
}

function setMode(mode){
  state.mode = mode;
  $$('#modeSeg .seg-btn').forEach(b=>b.classList.toggle('active', b.dataset.mode===mode));
  loadReport();
}
function setTab(tab){
  $$('.tab').forEach(t=>t.classList.toggle('active', t.dataset.tab===tab));
  $$('.view').forEach(v=>v.classList.remove('active'));
  $('#view-'+tab).classList.add('active');
  if(tab==='holdings' && state.holdings.length===0) loadHoldings();
}

// ---------- 加载报告 ----------
async function loadReport(){
  $('#fundList').innerHTML = '<div class="loading">加载中…</div>';
  $('#banner').classList.add('hidden');
  try{
    const r = await fetch('/api/report?mode='+state.mode);
    const data = await r.json();
    if(data.error){ showBanner('加载失败：'+data.error+'（实时模式需要能访问基金/行情数据的网络环境）', true); $('#fundList').innerHTML=''; return; }
    state.data = data;
    renderDashboard(data);
  }catch(e){
    showBanner('网络错误：'+e.message, true);
    $('#fundList').innerHTML='';
  }
}

function showBanner(msg, warn=false){
  const b=$('#banner'); b.textContent=msg; b.classList.remove('hidden');
  b.classList.toggle('warn', warn);
}

// ---------- 渲染仪表盘 ----------
function renderDashboard(d){
  $('#asOf').textContent = (d.title?d.title+' · ':'') + (d.as_of||'');

  if(d.empty){
    showBanner(d.message || '尚未配置持仓。', true);
  }

  // 概览卡片
  const ov = d.overview || {};
  const cards = $('#overview'); cards.innerHTML='';
  if(ov.has_value){
    cards.appendChild(cardEl('已公布净值市值', money(ov.total_value), '按各基金最新公布净值'));
    cards.appendChild(cardEl('时差估算「应有」市值', money(ov.total_implied_value),
      '今日额外涨跌 '+pct(ov.est_today_change), ov.est_today_change));
    cards.appendChild(cardEl('累计收益', pct(ov.total_return), '成本 '+money(ov.total_cost), ov.total_return));
  }else if(!d.empty){
    cards.appendChild(cardEl('提示','仅信号分析','未填份额/成本，补全后可看市值与收益'));
  }

  // 重点提示
  const hp=$('#highlights'), hl=$('#highlightList');
  if(d.highlights && d.highlights.length){
    hp.classList.remove('hidden'); hl.innerHTML='';
    d.highlights.forEach(f=>{
      const div=document.createElement('div'); div.className='hl';
      div.style.borderLeftColor = `var(--${f.action_kind})`;
      div.innerHTML = `<div><b>${esc(f.name)}</b> → <b style="color:var(--${f.action_kind})">${esc(f.action)}</b>
        <div class="hl-reason">${esc(f.rationale)}</div></div>`;
      hl.appendChild(div);
    });
  }else hp.classList.add('hidden');

  // 资产分布
  renderAllocation(d.allocation||[]);

  // 市场情报
  const mb=$('#marketBrief');
  mb.innerHTML = (d.market_brief&&d.market_brief.length)
    ? d.market_brief.map(b=>`<span class="chip">${esc(b)}</span>`).join('')
    : '<div class="empty">暂无</div>';

  // 基金卡片
  const list=$('#fundList'); list.innerHTML='';
  if(!d.funds || !d.funds.length){ list.innerHTML='<div class="empty">暂无持仓</div>'; }
  d.funds && d.funds.forEach((f,i)=>list.appendChild(fundCard(f,i)));

  // 组合建议
  const np=$('#notesPanel'), nl=$('#notesList');
  if(d.portfolio_notes && d.portfolio_notes.length){
    np.classList.remove('hidden');
    nl.innerHTML = d.portfolio_notes.map(n=>`<li>${esc(n)}</li>`).join('');
  }else np.classList.add('hidden');
}

function cardEl(k, v, sub, colorVal){
  const el=document.createElement('div'); el.className='card';
  let vCls='';
  if(colorVal!=null) vCls = colorVal>0?'pos':(colorVal<0?'neg':'');
  el.innerHTML = `<div class="k">${esc(k)}</div><div class="v ${vCls}">${esc(v)}</div><div class="sub">${esc(sub||'')}</div>`;
  return el;
}

function renderAllocation(alloc){
  const wrap=$('#allocChart');
  if(!alloc.length){ wrap.innerHTML='<div class="empty">暂无市值数据</div>'; return; }
  const segs = alloc.map((a,i)=>({pct:a.pct, color:ALLOC_COLORS[i%ALLOC_COLORS.length]}));
  const legend = alloc.map((a,i)=>`<div class="legend-row">
      <span class="legend-dot" style="background:${ALLOC_COLORS[i%ALLOC_COLORS.length]}"></span>
      <span class="lbl">${esc(ASSET_LABELS[a.label]||a.label)}</span>
      <span class="val">${(a.pct*100).toFixed(0)}%</span></div>`).join('');
  wrap.innerHTML = `<div>${donutSVG(segs)}</div><div class="legend">${legend}</div>`;
}

// ---------- SVG 图表（零依赖） ----------
function donutSVG(segments, size=128, thickness=24){
  const r=(size-thickness)/2, cx=size/2, cy=size/2, C=2*Math.PI*r;
  let offset=0, arcs='';
  segments.forEach(s=>{
    const len=Math.max(0,s.pct)*C;
    arcs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}" stroke-width="${thickness}"
      stroke-dasharray="${len.toFixed(2)} ${(C-len).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}"
      transform="rotate(-90 ${cx} ${cy})"/>`;
    offset+=len;
  });
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${arcs}
    <circle cx="${cx}" cy="${cy}" r="${r-thickness/2-1}" fill="#fff"/></svg>`;
}

function sparkSVG(points, h=64){
  if(!points || points.length<2) return '';
  const w=600, navs=points.map(p=>p.nav);
  const min=Math.min(...navs), max=Math.max(...navs), range=(max-min)||1;
  const stepX=w/(points.length-1);
  const xy=points.map((p,i)=>[i*stepX, h-((p.nav-min)/range)*(h-8)-4]);
  const line=xy.map((c,i)=>(i?'L':'M')+c[0].toFixed(1)+' '+c[1].toFixed(1)).join(' ');
  const area='M0 '+h+' '+xy.map(c=>'L'+c[0].toFixed(1)+' '+c[1].toFixed(1)).join(' ')+` L${w} ${h} Z`;
  const up=navs[navs.length-1]>=navs[0], color=up?'#0a7d2c':'#c0392b';
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
    <path d="${area}" fill="${color}" opacity="0.08"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}

// ---------- 基金卡片 ----------
function fundCard(f, idx){
  const m=f.metrics||{};
  const el=document.createElement('div'); el.className='fund'; el.dataset.idx=idx;
  let est='';
  if(f.estimate){
    const e=f.estimate;
    est = `<div class="est">⏱ 时差估算：未体现涨跌累计 <span class="big">${pct(e.cum_return)}</span>
      <span class="muted">(±${pct(e.band,false)})</span>　应有净值 ≈ <b>${num(e.implied_nav)}</b>
      <span class="muted">[${esc(e.method)}·${esc(e.index||'')}·滞后${e.lag_days}日]</span></div>`;
  }
  el.innerHTML = `
    <div class="fund-head">
      <span class="fund-name">${esc(f.name)}</span>
      <span class="fund-code">${esc(f.code)} · ${esc(ASSET_LABELS[f.asset_class]||f.asset_class)}</span>
      <span class="badge ${f.action_kind}">${esc(f.action)}</span>
    </div>
    <div class="fund-line">
      <span>最新净值 <span class="num">${num(m.last_nav)}</span></span>
      <span>持仓收益 ${pctHtml(m.holding_return)}</span>
      <span class="muted">信号分 ${f.score>=0?'+':''}${f.score}</span>
    </div>
    ${est}
    <div class="metrics">
      ${metric('近1周', pctHtml(m.ret_1w))}
      ${metric('近1月', pctHtml(m.ret_1m))}
      ${metric('近3月', pctHtml(m.ret_3m))}
      ${metric('近1年', pctHtml(m.ret_1y))}
      ${metric('RSI', m.rsi14!=null?Math.round(m.rsi14):'—')}
      ${metric('最大回撤', pctHtml(m.max_drawdown))}
      ${metric('年化波动', pct(m.vol_annual,false,1))}
      ${metric('净值分位', m.price_percentile!=null?Math.round(m.price_percentile*100)+'%':'—')}
    </div>
    ${sparkSVG(f.history)}`;
  el.addEventListener('click', ()=>openModal(f));
  return el;
}
function metric(label, val){ return `<div class="metric"><div class="ml">${label}</div><div class="mv">${val}</div></div>`; }

// ---------- 详情弹层 ----------
function openModal(f){
  const m=f.metrics||{};
  let estBlock='';
  if(f.estimate){
    const e=f.estimate;
    estBlock = `<div class="est" style="display:block">
      <div>⏱ <b>时差估算</b>（${esc(e.method)}，跟踪 ${esc(e.index||'')}，滞后 ${e.lag_days} 个指数交易日）</div>
      <div style="margin:6px 0">未体现累计 <b class="big">${pct(e.cum_return)}</b> (±${pct(e.band,false)})，
        最新净值 ${num(e.base_nav)} → 应有净值 ≈ <b>${num(e.implied_nav)}</b></div>
      <div class="sig-list">${(e.detail||[]).map(x=>`<div>· ${esc(x)}</div>`).join('')}</div></div>`;
  }
  const sigs = (f.signals||[]).map(s=>`<div><span class="sig-dot ${SIG_CLASS[s.kind]||''}"></span>${esc(s.text)}</div>`).join('');
  $('#modalBody').innerHTML = `
    <div class="fund-head" style="margin-bottom:10px">
      <span class="fund-name">${esc(f.name)}</span>
      <span class="fund-code">${esc(f.code)} · ${esc(ASSET_LABELS[f.asset_class]||f.asset_class)}</span>
      <span class="badge ${f.action_kind}">${esc(f.action)}</span>
    </div>
    <div class="fund-line">
      <span>最新净值 <span class="num">${num(m.last_nav)}</span></span>
      <span>持仓收益 ${pctHtml(m.holding_return)}</span>
      <span>MA20 ${num(m.ma20)} · MA60 ${num(m.ma60)}</span>
    </div>
    ${estBlock}
    ${sparkSVG(f.history, 96)}
    <div class="panel-title" style="margin-top:14px">触发信号</div>
    <div class="sig-list">${sigs||'<span class="muted">无</span>'}</div>
    <div class="panel-title" style="margin-top:14px">操作建议</div>
    <div>${esc(f.rationale||'—')}</div>`;
  $('#modal').classList.remove('hidden');
}
function closeModal(){ $('#modal').classList.add('hidden'); }

// ---------- 持仓管理 ----------
async function loadHoldings(){
  try{
    const r=await fetch('/api/holdings');
    const d=await r.json();
    state.holdings = (d.holdings&&d.holdings.length)?d.holdings:[{}];
  }catch(e){ state.holdings=[{}]; }
  renderRows();
}
async function loadExample(){
  const r=await fetch('/api/holdings/example');
  const d=await r.json();
  state.holdings = d.holdings || [];
  renderRows();
  setSaveMsg('已载入示例，可修改后保存。', '');
}

function renderRows(){
  const body=$('#holdingsBody'); body.innerHTML='';
  state.holdings.forEach((h,i)=>{
    const tk=h.tracking||{};
    const tr=document.createElement('tr'); tr.dataset.i=i;
    const opts=ASSET_OPTIONS.map(o=>`<option value="${o}" ${h.asset_class===o?'selected':''}>${ASSET_LABELS[o]}</option>`).join('');
    tr.innerHTML = `
      <td><input class="w-code" data-k="code" value="${esc(h.code||'')}" placeholder="270042"></td>
      <td><input data-k="name" value="${esc(h.name||'')}" placeholder="自动获取"></td>
      <td><select data-k="asset_class">${opts}</select></td>
      <td><input class="w-num" data-k="shares" type="number" step="any" value="${h.shares??''}"></td>
      <td><input class="w-num" data-k="cost_nav" type="number" step="any" value="${h.cost_nav??''}"></td>
      <td><input class="w-num" data-k="target_weight" type="number" step="any" value="${h.target_weight??''}" placeholder="0~1"></td>
      <td style="text-align:center"><input data-k="is_dca" type="checkbox" ${h.is_dca?'checked':''}></td>
      <td><input class="w-idx" data-tk="index" value="${esc(tk.index||'')}" placeholder="^NDX"></td>
      <td><input class="w-lag" data-tk="lag_days" type="number" value="${tk.lag_days??1}"></td>
      <td style="text-align:center"><input data-tk="currency_hedged" type="checkbox" ${tk.currency_hedged?'checked':''}></td>
      <td><input class="w-num" data-k="annual_fee" type="number" step="any" value="${h.annual_fee??''}" placeholder="0.008"></td>
      <td><button class="row-del" title="删除">×</button></td>`;
    tr.querySelector('.row-del').addEventListener('click', ()=>{ state.holdings.splice(i,1); if(!state.holdings.length) state.holdings=[{}]; renderRows(); });
    body.appendChild(tr);
  });
}

function collectRows(){
  return $$('#holdingsBody tr').map(tr=>{
    const o={tracking:{}};
    $$('[data-k]',tr).forEach(inp=>{
      o[inp.dataset.k] = inp.type==='checkbox'?inp.checked:inp.value;
    });
    $$('[data-tk]',tr).forEach(inp=>{
      o.tracking[inp.dataset.tk] = inp.type==='checkbox'?inp.checked:inp.value;
    });
    return o;
  }).filter(o=>String(o.code||'').trim());
}

async function saveHoldings(){
  const holdings=collectRows();
  if(!holdings.length){ setSaveMsg('请至少填写一只基金的代码。','neg'); return; }
  $('#saveBtn').disabled=true;
  try{
    const r=await fetch('/api/holdings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({holdings})});
    const d=await r.json();
    if(d.ok){ setSaveMsg(`已保存 ${d.saved} 只基金 ✅　切到上方「我的持仓」即可查看分析。`,'pos'); }
    else setSaveMsg('保存失败：'+(d.error||'未知错误'),'neg');
  }catch(e){ setSaveMsg('保存失败：'+e.message,'neg'); }
  finally{ $('#saveBtn').disabled=false; }
}
function setSaveMsg(msg, cls){ const el=$('#saveMsg'); el.textContent=msg; el.className='save-msg '+(cls||''); }

document.addEventListener('DOMContentLoaded', init);

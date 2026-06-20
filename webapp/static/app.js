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
const state = { data:null, holdings:[], watchlist:[] };

// ---------- 初始化 ----------
function init(){
  $$('.tab').forEach(t=>t.addEventListener('click', ()=>setTab(t.dataset.tab)));
  $('#refreshBtn').addEventListener('click', ()=>loadReport());
  $('#addRowBtn').addEventListener('click', ()=>{ state.holdings.push({}); renderRows(); });
  $('#saveBtn').addEventListener('click', saveHoldings);
  $('#loadExampleBtn').addEventListener('click', loadExample);
  $('#modalClose').addEventListener('click', closeModal);
  $('#modal').addEventListener('click', e=>{ if(e.target.id==='modal') closeModal(); });
  initImport();
  const bib=$('#batchImportBtn'); if(bib) bib.addEventListener('click', doBatchImport);
  const oib=$('#ocrImportBtn'); if(oib) oib.addEventListener('click', doOcrImport);
  const csb=$('#codeSearchBtn'); if(csb) csb.addEventListener('click', doCodeSearch);
  const sad=$('#setAllDailyBtn'); if(sad) sad.addEventListener('click', setAllDaily);
  const aab=$('#aiAnalyzeBtn'); if(aab) aab.addEventListener('click', runAiAnalysis);
  const wla=$('#wlAddBtn'); if(wla) wla.addEventListener('click', toggleAddRow);
  const wlc=$('#wlAddConfirm'); if(wlc) wlc.addEventListener('click', addWatchItem);
  const wlcc=$('#wlAddCancel'); if(wlcc) wlcc.addEventListener('click', toggleAddRow);
  loadReport().then(()=>{
    loadAlerts();
    runAiAnalysis();
    loadExposure();
    loadXirr();
    loadReturnCurve();
  });
  // PWA
  if('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js');
  startAutoRefresh();
}

function setTab(tab){
  $$('.tab').forEach(t=>t.classList.toggle('active', t.dataset.tab===tab));
  $$('.view').forEach(v=>v.classList.remove('active'));
  $('#view-'+tab).classList.add('active');
  if(tab==='holdings' && state.holdings.length===0) loadHoldings();
  if(tab==='watchlist') loadWatchlist();
}

// ---------- 加载报告 ----------
async function loadReport(){
  $('#fundList').innerHTML = '<div class="loading">加载中…</div>';
  $('#banner').classList.add('hidden');
  try{
    const r = await fetch('/api/report?mode=live');
    const data = await r.json();
    if(data.error){ showBanner('加载失败：'+data.error+'（实时模式需要能访问基金/行情数据的网络环境）', true); $('#fundList').innerHTML=''; return; }
    state.data = data;
    renderDashboard(data);
  }catch(e){
    showBanner('网络错误：'+e.message, true);
    $('#fundList').innerHTML='';
  }
}

// ---------- 自动刷新 ----------
let _autoRefreshTimer = null;

function startAutoRefresh(){
  if(_autoRefreshTimer) clearInterval(_autoRefreshTimer);
  _autoRefreshTimer = setInterval(async ()=>{
    try{
      const r = await fetch('/api/report?mode=live');
      const data = await r.json();
      if(!data.error){
        state.data = data;
        renderDashboard(data);
      }
    }catch(e){
      // Silent refresh failure — don't bother the user
    }
  }, 5 * 60 * 1000); // 5 minutes
}

function showBanner(msg, warn=false){
  const b=$('#banner'); b.textContent=msg; b.classList.remove('hidden');
  b.classList.toggle('warn', warn);
}

// ---------- 渲染仪表盘 ----------
function renderDashboard(d){
  $('#asOf').textContent = '最后更新: ' + ((d.title?d.title+' · ':'') + (d.as_of||''));

  if(d.empty){
    showBanner('还没有持仓数据。去「持仓管理」导入你的基金吧 👉', true);
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

  // 重点提示 — 由 AI 分析填充，不再使用机械信号
  const hp=$('#highlights'), hl=$('#highlightList');
  hp.classList.add('hidden');

  // 市场体温计
  if(d.market_indicators && d.market_indicators.length){
    renderThermo(d.market_indicators);
  }

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

function renderThermo(indicators){
  const panel=$('#marketThermo'); if(!panel) return;
  panel.classList.remove('hidden');
  const grid=$('#thermoGrid');
  const levelLabels={low:'偏低', normal:'正常', high:'偏高'};
  const levelIcons={low:'🟢', normal:'🟡', high:'🔴'};
  grid.innerHTML=indicators.map(ind=>{
    const icon=levelIcons[ind.level]||'⚪';
    const label=levelLabels[ind.level]||ind.level;
    return `<div class="thermo-card">
      <div class="thermo-head">
        <span class="thermo-label">${esc(ind.label)}</span>
        <span class="thermo-level" style="color:${ind.color}">${icon} ${label}</span>
      </div>
      <div class="thermo-value">
        <span class="thermo-num">${ind.value}</span>
        <span class="thermo-chg ${ind.change_pct>0?'pos':'neg'}">${ind.change_pct>=0?'+':''}${ind.change_pct}%</span>
        ${ind.ma20 ? `<span class="thermo-ma">MA20: ${ind.ma20}</span>` : ''}
      </div>
      <div class="thermo-bar-wrap">
        <div class="thermo-grad"></div>
        <div class="thermo-dot" style="left:${ind.value_percent||50}%;background:${ind.color}"></div>
      </div>
      <div class="thermo-desc">${esc(ind.desc)}</div>
    </div>`;
  }).join('');
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
      <span class="badge hold">分析中…</span>
    </div>
    <div class="fund-line">
      <span>最新净值 <span class="num">${num(m.last_nav)}</span></span>
      <span>持仓 ¥${Number(f.current_value||f.market_value||0).toLocaleString('zh-CN',{maximumFractionDigits:0})}</span>
      <span>持仓收益 ${pctHtml(m.holding_return)}</span>
      ${f.dca_plan ? `<span class="muted">每日定投 ¥${f.dca_plan.amount}</span>` : ''}
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

// ---------- 持仓管理（极简：代码 + 金额 + 每日定投）----------
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
    const dp=h.dca_plan||{};
    const tr=document.createElement('tr'); tr.dataset.i=i;
    tr.innerHTML = `
      <td><input class="w-code" data-k="code" value="${esc(h.code||'')}" placeholder="270042"></td>
      <td><span class="auto-name">${esc(h.name||'（保存后自动获取）')}</span></td>
      <td><input class="w-num" data-k="current_value" type="number" step="any" value="${h.current_value||''}" placeholder="50000"></td>
      <td><input class="w-num" data-k="dca_amount" type="number" step="any" value="${dp.amount||''}" placeholder="100"></td>
      <td><button class="row-del" title="删除">×</button></td>`;
    tr.querySelector('.row-del').addEventListener('click', ()=>{ state.holdings.splice(i,1); if(!state.holdings.length) state.holdings=[{}]; renderRows(); });
    body.appendChild(tr);
  });
}

function collectRows(){
  return $$('#holdingsBody tr').map(tr=>{
    const o={};
    $$('[data-k]',tr).forEach(inp=>{
      o[inp.dataset.k] = inp.type==='checkbox'?inp.checked:inp.value;
    });
    const code = String(o.code||'').trim();
    if(!code) return null;
    // 自动补全：所有字段都自动填，用户不用管
    o.is_dca = true;  // 默认开启定投
    const dcaAmount = parseFloat(o.dca_amount) || 0;
    if(dcaAmount > 0){
      o.dca_plan = {frequency: 'daily', amount: dcaAmount, enabled: true};
    }
    delete o.dca_amount;
    return o;
  }).filter(Boolean);
}

async function saveHoldings(){
  const holdings=collectRows();
  if(!holdings.length){ setSaveMsg('请至少填写一只基金的代码。','neg'); return; }
  $('#saveBtn').disabled=true;
  try{
    const r=await fetch('/api/holdings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({holdings})});
    const d=await r.json();
    if(d.ok){ setSaveMsg(`已保存 ${d.saved} 只基金 ✅`,'pos'); setTab('dashboard'); loadReport(); }
    else setSaveMsg('保存失败：'+(d.error||'未知错误'),'neg');
  }catch(e){ setSaveMsg('保存失败：'+e.message,'neg'); }
  finally{ $('#saveBtn').disabled=false; }
}
function setSaveMsg(msg, cls){ const el=$('#saveMsg'); el.textContent=msg; el.className='save-msg '+(cls||''); }

// ---------- 一键全部每日定投 ----------
function setAllDaily(){
  if(!state.holdings.length){ setSaveMsg('请先添加基金','neg'); return; }
  const amount=prompt('设置所有基金的每日定投金额（元）：','100');
  if(amount===null) return;
  const amt=parseFloat(amount)||0;
  state.holdings.forEach(h=>{
    if(!h.dca_plan) h.dca_plan={};
    h.dca_plan.frequency='daily';
    h.dca_plan.amount=amt;
    h.dca_plan.enabled=true;
    h.is_dca=true;
  });
  renderRows();
  setSaveMsg(`已设置全部基金每日定投 ¥${amt} ⚡`,'pos');
}

// ---------- 导入面板切换 ----------
function initImport(){
  $$('.imp-tab').forEach(b=>b.addEventListener('click', ()=>{
    const pane=b.dataset.imp;
    $$('.imp-tab').forEach(t=>t.classList.toggle('active', t===b));
    $$('.import-pane').forEach(p=>p.classList.toggle('active', p.id==='import-'+pane));
  }));
}

// ---------- 批量导入 ----------
function setImportStatus(msg,cls){ const el=$('#importStatus'); if(el){el.textContent=msg; el.className='save-msg '+(cls||'');} }

async function doBatchImport(){
  const text=$('#batchText').value.trim();
  if(!text){ setImportStatus('请粘贴持仓数据','neg'); return; }
  setImportStatus('识别中…','');
  try{
    const r=await fetch('/api/import/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    const d=await r.json();
    if(d.error){ setImportStatus(d.error,'neg'); return; }
    // 从批量文本中提取每日定投金额（第三列）
    const lines=text.split('\n').filter(l=>l.trim());
    lines.forEach(line=>{
      const parts=line.trim().split(/\s+/);
      if(parts.length>=3){
        const code=parts[0];
        const dcaAmt=parseFloat(parts[2])||0;
        if(dcaAmt>0){
          const fund=d.funds.find(f=>f.code===code);
          if(fund){
            fund.dca_plan={frequency:'daily', amount:dcaAmt, enabled:true};
            fund.is_dca=true;
          }
        }
      }
    });
    d.funds.forEach(f=>{
      const exist=state.holdings.findIndex(h=>h.code===f.code);
      if(exist>=0) state.holdings[exist]={...state.holdings[exist],...f};
      else state.holdings.push(f);
    });
    renderRows();
    setImportStatus(`已识别并补全 ${d.count} 只基金 ✅（每日定投已自动设置）`,'pos');
  }catch(e){ setImportStatus('导入失败: '+e.message,'neg'); }
}

// ---------- OCR 导入 ----------
async function doOcrImport(){
  const file=$('#ocrFile').files[0];
  if(!file){ setImportStatus('请先选择截图文件','neg'); return; }
  setImportStatus('OCR 识别中…','');
  const fd=new FormData(); fd.append('image',file);
  try{
    const r=await fetch('/api/import/ocr',{method:'POST',body:fd});
    const d=await r.json();
    if(d.error){ setImportStatus(d.error,'neg'); return; }
    d.funds.forEach(f=>{
      const exist=state.holdings.findIndex(h=>h.code===f.code);
      if(exist>=0) state.holdings[exist]={...state.holdings[exist],...f};
      else state.holdings.push(f);
    });
    renderRows();
    setImportStatus(`OCR 识别 ${d.count} 只基金 ✅`,'pos');
  }catch(e){ setImportStatus('OCR 失败: '+e.message,'neg'); }
}

// ---------- 代码搜索 ----------
async function doCodeSearch(){
  const code=$('#codeSearchInput').value.trim();
  if(code.length!==6){ setImportStatus('请输入6位基金代码','neg'); return; }
  setImportStatus('搜索中…','');
  try{
    const r=await fetch('/api/fund/search?code='+code);
    const d=await r.json();
    if(d.error){ setImportStatus(d.error,'neg'); return; }
    const fund=d.fund;
    fund.current_value=parseFloat($('#codeSearchAmount').value)||fund.current_value||0;
    fund.is_dca=true;
    const dcaAmt=parseFloat($('#codeSearchDca')?.value)||0;
    if(dcaAmt>0){
      fund.dca_plan={frequency:'daily', amount:dcaAmt, enabled:true};
    }
    const exist=state.holdings.findIndex(h=>h.code===fund.code);
    if(exist>=0) state.holdings[exist]={...state.holdings[exist],...fund};
    else state.holdings.push(fund);
    renderRows();
    setImportStatus(`已添加 ${fund.name} ✅（类型、跟踪指数等已自动补全）`,'pos');
    $('#codeSearchInput').value=''; $('#codeSearchAmount').value='';
    const dcaEl=$('#codeSearchDca'); if(dcaEl) dcaEl.value='';
  }catch(e){ setImportStatus('搜索失败: '+e.message,'neg'); }
}

// ---------- AI 分析 ----------
async function runAiAnalysis(){
  const panel=$('#aiPanel'); if(panel) panel.classList.remove('hidden');
  const portfolioEl=$('#aiPortfolio'); if(portfolioEl) portfolioEl.innerHTML='<div class="loading">AI 分析中…</div>';
  try{
    const r=await fetch('/api/ai/analyze');
    const d=await r.json();
    if(d.error){
      if(portfolioEl) portfolioEl.innerHTML='<span class="neg">'+esc(d.error)+'</span>';
      return;
    }
    // 组合分析
    let html='';
    if(d.portfolio_analysis) html+=`<div><b>📊 组合分析</b><br>${esc(d.portfolio_analysis)}</div>`;
    if(d.sector_bias) html+=`<div style="margin-top:8px"><b>🏭 行业偏向</b><br>${esc(d.sector_bias)}</div>`;
    if(d.macro_note) html+=`<div style="margin-top:8px"><b>🌍 宏观判断</b><br>${esc(d.macro_note)}</div>`;
    if(portfolioEl) portfolioEl.innerHTML=html||'<div class="empty">暂无</div>';

    // 逐只标签 + 覆盖基金卡片的操作建议
    const tagsEl=$('#aiFundTags');
    if(d.funds && tagsEl){
	      const nameMap={};
	      (state.data?.funds||[]).forEach(f=>{ nameMap[f.code]=f.name; });
      const bullish=[], bearish=[], neutral=[];
      const tags=Object.entries(d.funds).map(([code,s])=>{
        const cls=s.sentiment==='看好'||s.sentiment==='强烈看好'?'bullish':(s.sentiment==='谨慎'||s.sentiment==='规避'?'bearish':'neutral');
        const icon=s.sentiment==='看好'||s.sentiment==='强烈看好'?'🟢':(s.sentiment==='谨慎'||s.sentiment==='规避'?'🔴':'🟡');
        if(s.sentiment==='看好'||s.sentiment==='强烈看好') bullish.push({code,s});
        else if(s.sentiment==='谨慎'||s.sentiment==='规避') bearish.push({code,s});
        else neutral.push({code,s});
        return `<span class="ai-tag ${cls}">${icon} ${esc(nameMap[code]||code)}: ${s.sentiment} — ${esc(s.reason||'')} — ${esc(s.suggestion||'')}</span>`;
      }).join('');
      tagsEl.innerHTML=tags;

      // AI 结果更新基金卡片：用 AI 建议替换机械 badge
      Object.entries(d.funds).forEach(([code,s])=>{
        $$('.fund').forEach(card=>{
          const codeEl=card.querySelector('.fund-code');
          if(codeEl && codeEl.textContent.includes(code)){
            // 替换机械 badge 为 AI 建议
            const badge=card.querySelector('.badge');
            if(badge){
              badge.textContent=s.suggestion||s.sentiment;
              const isBull=s.sentiment==='看好'||s.sentiment==='强烈看好';
              const isBear=s.sentiment==='谨慎'||s.sentiment==='规避';
              badge.className='badge '+(isBull?'hold_pos':(isBear?'trim':'hold'));
            }
          }
        });
      });

      // AI 结果驱动重点提示
      const hp=$('#highlights'), hl=$('#highlightList');
      hp.classList.remove('hidden'); hl.innerHTML='';
      const all=[...bullish.map(x=>({...x,kind:'bullish'})),...bearish.map(x=>({...x,kind:'bearish'}))];
      all.forEach(x=>{
        const div=document.createElement('div'); div.className='hl';
        const color=x.kind==='bullish'?'#16a34a':'#dc2626';
        div.style.borderLeftColor=color;
        div.innerHTML=`<div><b>${esc(nameMap[x.code]||x.code)}</b> → <b style="color:${color}">${esc(x.s.sentiment)}: ${esc(x.s.suggestion)}</b>
          <div class="hl-reason">${esc(x.s.reason||'')}</div></div>`;
        hl.appendChild(div);
      });
    }

    // 新闻 feed
    const newsPanel=$('#newsPanel');
    if(d.news_feed && d.news_feed.length && newsPanel){
      newsPanel.classList.remove('hidden');
      const icons={macro:'📅', institution:'🏦', fund:'📰'};
      const feedHtml=d.news_feed.map(n=>{
        const icon=icons[n.type]||'📌';
        const cls=n.type==='macro'?'nf-macro':(n.type==='institution'?'nf-inst':'nf-fund');
        return `<div class="nf-item ${cls}"><span class="nf-icon">${icon}</span><span class="nf-text">${esc(n.text)}</span></div>`;
      }).join('');
      $('#newsFeed').innerHTML=feedHtml;
    }else if(newsPanel){ newsPanel.classList.add('hidden'); }

    // 定投调整建议
    const dcaEl=$('#aiDcaTips');
    if(d.dca_adjustments && Object.keys(d.dca_adjustments).length && dcaEl){
      const tips=Object.entries(d.dca_adjustments).map(([code,txt])=>`<div>📌 ${code}: ${esc(txt)}</div>`).join('');
      dcaEl.innerHTML=`<b>💡 定投调整建议</b>${tips}`;
    }else if(dcaEl){ dcaEl.innerHTML=''; }
  }catch(e){
    if(portfolioEl) portfolioEl.innerHTML='<span class="neg">AI 分析失败: '+esc(e.message)+'</span>';
  }
}

// ---------- XIRR + 收益曲线 ----------
async function loadXirr(){
  try{
    const r=await fetch('/api/xirr');
    const d=await r.json();
    if(d.error) return;
    const ov=$('#overview');
    const xirrCard=document.createElement('div'); xirrCard.className='card';
    const xirrCls=d.xirr>0?'pos':'neg';
    xirrCard.innerHTML=`<div class="k">📈 XIRR 真实年化收益</div><div class="v ${xirrCls}">${d.xirr>0?'+':''}${d.xirr.toFixed(1)}%</div><div class="sub">投入 ¥${Number(d.total_invested).toLocaleString()} · 收益 ¥${Number(d.total_return).toLocaleString()} · ${d.years.toFixed(1)}年</div>`;
    ov.appendChild(xirrCard);
  }catch(e){}
}

async function loadReturnCurve(){
  try{
    const r=await fetch('/api/snapshot/curve?days=90');
    const d=await r.json();
    if(!d.curve || d.curve.length<2) return;
    const panel=$('#curvePanel'); if(!panel) return;
    panel.classList.remove('hidden');
    const values=d.curve.map(p=>p.total_value);
    const min=Math.min(...values), max=Math.max(...values), range=(max-min)||1;
    const w=600, h=100, pad=8;
    const pts=d.curve.map((p,i)=>({x:i/(d.curve.length-1)*w, y:h-pad-(p.total_value-min)/range*(h-2*pad)}));
    const line=pts.map((c,i)=>(i?'L':'M')+c.x.toFixed(1)+' '+c.y.toFixed(1)).join(' ');
    const area='M0 '+h+' '+pts.map(c=>'L'+c.x.toFixed(1)+' '+c.y.toFixed(1)).join(' ')+` L${w} ${h} Z`;
    const lastVal=d.curve[d.curve.length-1].total_value;
    const firstVal=d.curve[0].total_value;
    const chg=lastVal/firstVal-1;
    const color=chg>=0?'#16a34a':'#dc2626';
    $('#curveSVG').innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
      <path d="${area}" fill="${color}" opacity="0.1"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="2"/>
    </svg>`;
    $('#curveLabel').innerHTML=`<span style="color:${color};font-weight:700">累计 ${(chg*100).toFixed(1)}%</span> · ${d.curve.length} 天`;
  }catch(e){}
}

// ---------- 组合暴露分析 ----------
async function loadExposure(){
  const panel=$('#exposurePanel');
  const body=$('#exposureBody');
  if(body) body.innerHTML='<div class="loading">加载中…</div>';
  try{
    const r=await fetch('/api/portfolio/exposure');
    const d=await r.json();
    if(panel && !d.error && d.total_value){
      panel.classList.remove('hidden');
      const regions=Object.entries(d.by_region||{}).map(([r,p])=>`${r}: ${p}%`).join(' · ');
      const currencies=Object.entries(d.by_currency||{}).map(([c,p])=>`${c}: ${p}%`).join(' · ');
      const benchmarks=Object.entries(d.by_benchmark||{}).slice(0,3).map(([bm,info])=>`${bm}: ${info.pct}%`).join(' · ');
      const warnHtml=(d.warnings||[]).map(w=>`<div style="color:#b26a00;font-size:12px">⚠️ ${esc(w)}</div>`).join('');
      if(body) body.innerHTML=`
        <div><b>地区:</b> ${esc(regions)}</div>
        <div><b>币种:</b> ${esc(currencies)}</div>
        <div><b>指数:</b> ${esc(benchmarks)}</div>
        ${warnHtml?`<div style="margin-top:4px">${warnHtml}</div>`:''}
      `;
    }else if(body && d.error){
      body.innerHTML='<div class="empty">加载失败</div>';
    }
  }catch(e){if(body) body.innerHTML='<div class="empty">加载失败</div>';}
}

// ---------- 自选分析 ----------
async function loadWatchlist(){
  try{
    const r=await fetch('/api/watchlist');
    const d=await r.json();
    state.watchlist=d.watchlist||[];
    renderWatchlistList();
  }catch(e){
    state.watchlist=[];
    $('#wlList').innerHTML='';
  }
}

function renderWatchlistList(){
  const el=$('#wlList');
  if(!state.watchlist.length){
    el.innerHTML='<div class="empty">暂无自选基金，点击「添加自选」开始</div>';
    return;
  }
  el.innerHTML=state.watchlist.map(w=>`<div class="wl-item">
    <span class="wl-name">${esc(w.name||w.code)}</span>
    <span class="wl-code">${esc(w.code)}</span>
    ${w.note ? `<span class="wl-note">${esc(w.note)}</span>` : ''}
    <button class="wl-remove" data-code="${esc(w.code)}">×</button>
  </div>`).join('');
  $$('.wl-remove').forEach(b=>b.addEventListener('click', ()=>removeWatchItem(b.dataset.code)));
}

async function addWatchItem(){
  const code=$('#wlAddCode').value.trim();
  const note=$('#wlAddNote').value.trim();
  if(code.length!==6){ $('#wlStatus').textContent='请输入6位基金代码'; return; }
  try{
    const r=await fetch('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,note})});
    const d=await r.json();
    if(d.error){ $('#wlStatus').textContent=d.error; return; }
    $('#wlAddCode').value='';
    $('#wlAddNote').value='';
    toggleAddRow();
    $('#wlStatus').textContent=`已添加 ${esc(code)} ✅`;
    loadWatchlist();
  }catch(e){
    $('#wlStatus').textContent='添加失败: '+e.message;
  }
}

async function removeWatchItem(code){
  try{
    const r=await fetch('/api/watchlist?code='+code,{method:'DELETE'});
    const d=await r.json();
    if(d.error){ $('#wlStatus').textContent=d.error; return; }
    $('#wlStatus').textContent=`已移除 ${esc(code)}`;
    loadWatchlist();
  }catch(e){
    $('#wlStatus').textContent='移除失败: '+e.message;
  }
}

function toggleAddRow(){
  const row=$('#wlAddRow');
  row.classList.toggle('hidden');
  if(!row.classList.contains('hidden')) $('#wlAddCode').focus();
}

$('#wlAnalyzeBtn')?.addEventListener('click', analyzeWatchlist);

async function analyzeWatchlist(){
  const codes=(state.watchlist||[]).map(w=>w.code);
  if(!codes.length){ $('#wlStatus').textContent='自选列表为空，请先添加基金'; return; }
  $('#wlStatus').textContent=`分析 ${codes.length} 只基金中…`;
  $('#wlResults').innerHTML='<div class="loading">AI 分析中…</div>';
  try{
    const r=await fetch('/api/watchlist/analyze?codes='+codes.join(','));
    const d=await r.json();
    if(d.error){ $('#wlStatus').textContent=d.error; return; }
    $('#wlStatus').textContent=`分析完成 ✅`;
    renderWatchlistResults(d.results||[]);
  }catch(e){
    $('#wlStatus').textContent='分析失败: '+e.message;
    $('#wlResults').innerHTML='';
  }
}

function renderFactorBars(factors){
  if(!factors || !factors.scores) return '';
  const s=factors.scores;
  const colorMap=v=>v>=70?'#16a34a':(v>=50?'#f59e0b':'#dc2626');
  const bars=factors.labels.map((l,i)=>{
    const keys=['momentum','trend_quality','value','risk_adjusted','vol_regime','drawdown_recovery'];
    const v=s[keys[i]]||50;
    return `<div class="fb-row">
      <span class="fb-label">${l}</span>
      <div class="fb-track"><div class="fb-fill" style="width:${v}%;background:${colorMap(v)}"></div></div>
      <span class="fb-val" style="color:${colorMap(v)}">${Math.round(v)}</span>
    </div>`;
  }).join('');
  return `<div class="wl-factors">
    <div class="fb-head"><span>量化因子评分</span><span class="fb-composite" style="color:${colorMap(factors.composite)}">综合 ${Math.round(factors.composite)}/100</span></div>
    ${bars}
    ${factors.summary ? `<div class="fb-summary">${esc(factors.summary)}</div>` : ''}
  </div>`;
}

function renderWatchlistResults(results){
  const el=$('#wlResults');
  el.innerHTML=results.map(r=>{
    if(r.error) return `<div class="wl-card wl-error">${esc(r.code)}: ${esc(r.error)}</div>`;

    const dec=r.decision||{};
    const buyColor=dec.color||'#6b7280';

    const factorHtml=renderFactorBars(r.factors)||'';

    const corrWarnings=(r.correlations||[]).filter(c=>c.correlation>0.7);
    const corrHtml=corrWarnings.length>0
      ? `<div class="wl-corr">${corrWarnings.map(c=>esc(c.warning)).join('<br>')}</div>`
      : '';

    const m=r.metrics||{};

    return `<div class="wl-card">
      <div class="wl-head">
        <span class="wl-name">${esc(r.name)}</span>
        <span class="wl-code">${esc(r.code)} · ${esc(r.asset_class||'')}</span>
        <span class="wl-judgment" style="background:${buyColor}">${esc(dec.label||'—')}</span>
        ${dec.advice ? `<span class="wl-advice-tag">${esc(dec.advice)}</span>` : ''}
      </div>
      <div class="wl-metrics">
        <span>净值 ${num(m.last_nav)}</span>
        <span>近1月 ${pctHtml(m.ret_1m)}</span>
        <span>近3月 ${pctHtml(m.ret_3m)}</span>
        <span>RSI ${m.rsi14!=null?Math.round(m.rsi14):'—'}</span>
        <span>估值分位 ${m.price_percentile!=null?Math.round(m.price_percentile*100)+'%':'—'}</span>
      </div>
      ${factorHtml}
      ${corrHtml}
      <button class="btn ghost wl-transfer-btn" data-code="${r.code}" data-name="${esc(r.name)}" style="margin-top:6px;font-size:11px">📥 一键转入持仓</button>
    </div>`;
  }).join('');
  el.querySelectorAll('.wl-transfer-btn').forEach(btn=>{
    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      transferToHoldings(btn.dataset.code, btn.dataset.name);
    });
  });
}

// ---------- 一键转入持仓 ----------
async function transferToHoldings(code, name){
  const amount=prompt(`为 ${name} 设置持仓金额（元）：`, '10000');
  if(amount===null) return;
  const dca=prompt('每日定投金额（元）：', '100');
  if(dca===null) return;

  try{
    const r=await fetch('/api/fund/search?code='+code);
    const d=await r.json();
    if(d.error){ alert(d.error); return; }

    const fund=d.fund;
    fund.current_value=parseFloat(amount)||0;
    fund.is_dca=true;
    const dcaAmt=parseFloat(dca)||0;
    if(dcaAmt>0){
      fund.dca_plan={frequency:'daily', amount:dcaAmt, enabled:true};
    }

    const hr=await fetch('/api/holdings');
    const hd=await hr.json();
    let holdings=hd.holdings||[];
    const exist=holdings.findIndex(h=>h.code===code);
    if(exist>=0){
      holdings[exist]={...holdings[exist], ...fund};
    } else {
      holdings.push(fund);
    }

    const sr=await fetch('/api/holdings', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({holdings})
    });
    const sd=await sr.json();
    if(sd.ok){
      alert(`已添加 ${name} 到持仓 ✅`);
    } else {
      alert('保存失败: '+(sd.error||'未知错误'));
    }
  }catch(e){
    alert('转入失败: '+e.message);
  }
}

// ---------- 基金筛选 ----------
let scrCategory='us-qdii';
$$('.scr-cat').forEach(b=>b.addEventListener('click',()=>{scrCategory=b.dataset.scr;$$('.scr-cat').forEach(x=>x.classList.toggle('active',x===b));}));
$('#scrRunBtn')?.addEventListener('click', runScreener);

async function runScreener(){
  $('#scrStatus').textContent='启动筛选…';
  $('#scrResults').innerHTML='<div class="loading">正在从完整基金池拉数据…</div>';

  try{
    // Start task
    const r1=await fetch('/api/screener/start?category='+scrCategory, {method:'POST'});
    const d1=await r1.json();
    if(d1.error){ $('#scrStatus').textContent=d1.error; return; }

    const taskId=d1.task_id;
    const start=Date.now();

    // Poll for completion
    while(true){
      await new Promise(r=>setTimeout(r, 2000));
      const r2=await fetch('/api/screener/status/'+taskId);
      const d2=await r2.json();

      if(d2.status==='done'){
        const elapsed=Math.round((Date.now()-start)/1000);
        $('#scrStatus').textContent=`筛选完成，共 ${d2.result.length} 只基金 (${elapsed}s)`;
        renderScreener(d2.result||[]);
        return;
      } else if(d2.status==='error'){
        $('#scrStatus').textContent='筛选失败: '+(d2.error||'未知错误');
        return;
      } else {
        const elapsed=Math.round((Date.now()-start)/1000);
        $('#scrStatus').textContent=`筛选中… (${elapsed}s)`;
      }
    }
  }catch(e){
    $('#scrStatus').textContent='筛选失败: '+e.message;
  }
}

function renderScreener(funds){
  const el=$('#scrResults');
  el.innerHTML=funds.map((f,i)=>{
    const score=f.final_score||f.composite_score||0;
    const scoreColor=score>=65?'#16a34a':(score>=45?'#f59e0b':'#6b7280');
    const ds=f.detail_scores||{};
    const strengthStr=(f.strengths||[]).slice(0,3).join(' · ');
    const riskStr=(f.risks||[]).slice(0,2).join(' · ');
    const dqWarnings=[];
    if(f.annual_fee===null||f.annual_fee===undefined) dqWarnings.push('费率未知');
    if(f.fund_size===null||f.fund_size===undefined) dqWarnings.push('规模未知');
    const dqHtml=dqWarnings.length>0?`<div class="wl-risk-opp"><span class="wl-risk">⚠️ 数据质量: ${dqWarnings.join(', ')} (评分置信度降低)</span></div>`:'';
    const lowQuality = (f.confidence||100) < 50 || dqWarnings.length > 0;
    const dqBadge = lowQuality ? '<span class="wl-judgment" style="background:#f59e0b;font-size:10px">⚠️ 数据不完整</span>' : '';
    return `<div class="wl-card">
      <div class="wl-head">
        <span class="scr-rank">#${i+1}</span>
        <span class="wl-name">${esc(f.name)}</span>
        <span class="wl-code">${esc(f.code)} · ${esc(f.fund_type||'')} · ${esc(f.model_type||'')}</span>
        <span class="wl-judgment" style="background:${scoreColor}">${Math.round(score)}分/${f.confidence||0}%</span>
        ${dqBadge}
      </div>
      <div class="wl-metrics">
        <span>基准: ${esc(f.benchmark_name||'')}</span>
        <span>同类: ${esc(f.peer_rank||'')}</span>
        ${Object.entries(ds).slice(0,5).map(([k,v])=>`<span>${k}: ${Math.round(v)}</span>`).join('')}
      </div>
      ${strengthStr?`<div class="wl-advice">✅ ${esc(strengthStr)}</div>`:''}
      ${riskStr?`<div class="wl-risk-opp"><span class="wl-risk">⚠️ ${esc(riskStr)}</span></div>`:''}
      ${dqHtml}
    </div>`;
  }).join('');
}

// ---------- 智能提醒 ----------
$('#alertsRefreshBtn')?.addEventListener('click', loadAlerts);
function loadAlerts(){
  fetch('/api/alerts').then(r=>r.json()).then(d=>{
    const panel=$('#alertsPanel');
    if(d.error || !d.alerts || !d.alerts.length){
      if(panel) panel.classList.add('hidden');
      return;
    }
    if(panel) panel.classList.remove('hidden');
    const list=$('#alertsList');
    list.innerHTML=d.alerts.map(a=>{
      const bg=a.level==='🔴'?'#fef2f2':(a.level==='🟡'?'#fffbeb':'#f0fdf4');
      return `<div class="alert-item" style="background:${bg}">
        <span class="alert-level">${a.level}</span>
        <div class="alert-body">
          <div class="alert-title">${esc(a.name)} — ${esc(a.message)}</div>
          <div class="alert-action">→ ${esc(a.action)}</div>
        </div>
      </div>`;
    }).join('');
  }).catch(()=>{});
}

document.addEventListener('DOMContentLoaded', init);

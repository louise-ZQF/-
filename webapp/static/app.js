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
const state = { data:null, holdings:[] };

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

function showBanner(msg, warn=false){
  const b=$('#banner'); b.textContent=msg; b.classList.remove('hidden');
  b.classList.toggle('warn', warn);
}

// ---------- 渲染仪表盘 ----------
function renderDashboard(d){
  $('#asOf').textContent = (d.title?d.title+' · ':'') + (d.as_of||'');

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
      <span class="badge ${f.action_kind}">${esc(f.action)}</span>
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

    // 逐只标签
    const tagsEl=$('#aiFundTags');
    if(d.funds && tagsEl){
      const tags=Object.entries(d.funds).map(([code,s])=>{
        const cls=s.sentiment==='看好'?'bullish':(s.sentiment==='谨慎'?'bearish':'neutral');
        const icon=s.sentiment==='看好'?'🟢':(s.sentiment==='谨慎'?'🔴':'🟡');
        return `<span class="ai-tag ${cls}">${icon} ${code}: ${s.sentiment} — ${esc(s.reason||'')} — ${esc(s.suggestion||'')}</span>`;
      }).join('');
      tagsEl.innerHTML=tags;
      // Sync to fund cards
      Object.entries(d.funds).forEach(([code,s])=>{
        $$('.fund').forEach(card=>{
          const codeEl=card.querySelector('.fund-code');
          if(codeEl && codeEl.textContent.includes(code)){
            const cls=s.sentiment==='看好'?'ai-bullish':(s.sentiment==='谨慎'?'ai-bearish':'ai-neutral');
            const icon=s.sentiment==='看好'?'🟢':(s.sentiment==='谨慎'?'🔴':'🟡');
            const existBadge=card.querySelector('.ai-badge');
            if(existBadge) existBadge.remove();
            const head=card.querySelector('.fund-head');
            const badge=document.createElement('span');
            badge.className='ai-badge '+cls;
            badge.textContent=icon+' '+s.sentiment;
            head.appendChild(badge);
          }
        });
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

// ---------- 自选分析 ----------
$('#wlAnalyzeBtn')?.addEventListener('click', analyzeWatchlist);

async function analyzeWatchlist(){
  const raw=$('#wlInput').value.trim();
  if(!raw){ $('#wlStatus').textContent='请输入基金代码'; return; }
  const codes=raw.split(/[,\n\s]+/).filter(c=>c.length===6);
  if(!codes.length){ $('#wlStatus').textContent='未识别到有效代码'; return; }

  $('#wlStatus').textContent=`分析 ${codes.length} 只基金中…`;
  $('#wlResults').innerHTML='<div class="loading">AI 分析中…</div>';

  try{
    const r=await fetch('/api/watchlist/analyze?codes='+codes.join(','));
    const d=await r.json();
    if(d.error){ $('#wlStatus').textContent=d.error; return; }

    $('#wlStatus').textContent=`分析完成 ✅`;
    renderWatchlist(d.results||[]);
  }catch(e){
    $('#wlStatus').textContent='分析失败: '+e.message;
    $('#wlResults').innerHTML='';
  }
}

function renderWatchlist(results){
  const el=$('#wlResults');
  const judgmentColors={看好:'#16a34a', 中性:'#6b7280', 不看好:'#dc2626'};
  const buyColors={是:'#16a34a', 等回调:'#f59e0b', 否:'#dc2626'};
  el.innerHTML=results.map(r=>{
    if(r.error) return `<div class="wl-card wl-error">${r.code}: ${r.error}</div>`;
    const m=r.metrics||{};
    const jc=judgmentColors[r.judgment]||'#6b7280';
    const bc=buyColors[r.buy_signal]||'#6b7280';
    return `<div class="wl-card">
      <div class="wl-head">
        <span class="wl-name">${esc(r.name)}</span>
        <span class="wl-code">${esc(r.code)}</span>
        <span class="wl-judgment" style="background:${jc}">${esc(r.judgment)}</span>
        <span class="wl-buy" style="background:${bc}">${esc(r.buy_signal=='是'?'✅ 适合买入':r.buy_signal=='等回调'?'⏳ 等回调':r.buy_signal=='否'?'❌ 不建议':'—')}</span>
      </div>
      <div class="wl-metrics">
        <span>净值 ${num(m.last_nav)}</span>
        <span>近1月 ${pctHtml(m.ret_1m)}</span>
        <span>近3月 ${pctHtml(m.ret_3m)}</span>
        <span>RSI ${m.rsi14!=null?Math.round(m.rsi14):'—'}</span>
        <span>估值分位 ${m.price_percentile!=null?Math.round(m.price_percentile*100)+'%':'—'}</span>
      </div>
      ${r.advice ? `<div class="wl-advice"><b>建议：</b>${esc(r.advice)}</div>` : ''}
      <div class="wl-risk-opp">
        ${r.risk ? `<span class="wl-risk">⚠️ 风险：${esc(r.risk)}</span>` : ''}
        ${r.opportunity ? `<span class="wl-opp">💡 机会：${esc(r.opportunity)}</span>` : ''}
      </div>
    </div>`;
  }).join('');
}

document.addEventListener('DOMContentLoaded', init);

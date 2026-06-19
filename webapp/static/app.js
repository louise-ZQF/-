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
  initImport();
  // Import buttons
  const bib=$('#batchImportBtn'); if(bib) bib.addEventListener('click', doBatchImport);
  const oib=$('#ocrImportBtn'); if(oib) oib.addEventListener('click', doOcrImport);
  const csb=$('#codeSearchBtn'); if(csb) csb.addEventListener('click', doCodeSearch);
  // AI analysis button
  const aab=$('#aiAnalyzeBtn'); if(aab) aab.addEventListener('click', runAiAnalysis);
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
    const dp=h.dca_plan||{};
    const freqOpts={'daily':'每天','weekly':'每周','monthly':'每月'};
    const tr=document.createElement('tr'); tr.dataset.i=i;
    const opts=ASSET_OPTIONS.map(o=>`<option value="${o}" ${h.asset_class===o?'selected':''}>${ASSET_LABELS[o]}</option>`).join('');
    tr.innerHTML = `
      <td><input class="w-code" data-k="code" value="${esc(h.code||'')}" placeholder="270042"></td>
      <td><input data-k="name" value="${esc(h.name||'')}" placeholder="自动获取"></td>
      <td><select data-k="asset_class">${opts}</select></td>
      <td><input class="w-num" data-k="current_value" type="number" step="any" value="${h.current_value||''}" placeholder="50000"></td>
      <td><input class="w-num" data-k="cost_nav" type="number" step="any" value="${h.cost_nav??''}"></td>
      <td><input class="w-num" data-k="target_weight" type="number" step="any" value="${h.target_weight??''}" placeholder="0~1"></td>
      <td style="text-align:center"><input data-k="is_dca" type="checkbox" ${h.is_dca?'checked':''}></td>
      <td><select data-k="dca_freq">${['daily','weekly','monthly'].map(f=>`<option value="${f}" ${(dp.frequency||'monthly')===f?'selected':''}>${freqOpts[f]}</option>`).join('')}</select></td>
      <td><input class="w-num" data-k="dca_amount" type="number" step="any" value="${dp.amount||''}" placeholder="1000"></td>
      <td><input class="w-idx" data-tk="index" value="${esc(tk.index||'')}" placeholder="^NDX"></td>
      <td><input class="w-lag" data-tk="lag_days" type="number" value="${tk.lag_days??1}"></td>
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
    // Collect DCA plan
    const dcaFreq = tr.querySelector('[data-k="dca_freq"]')?.value || 'monthly';
    const dcaAmount = parseFloat(tr.querySelector('[data-k="dca_amount"]')?.value) || 0;
    if (dcaAmount > 0) {
      o.dca_plan = {frequency: dcaFreq, amount: dcaAmount, enabled: true};
    }
    // Remove raw dca fields from top-level
    delete o.dca_freq;
    delete o.dca_amount;
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
    d.funds.forEach(f=>{
      const exist=state.holdings.findIndex(h=>h.code===f.code);
      if(exist>=0) state.holdings[exist]={...state.holdings[exist],...f};
      else state.holdings.push(f);
    });
    renderRows();
    setImportStatus(`已识别并补全 ${d.count} 只基金 ✅`,'pos');
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
    const exist=state.holdings.findIndex(h=>h.code===fund.code);
    if(exist>=0) state.holdings[exist]={...state.holdings[exist],...fund};
    else state.holdings.push(fund);
    renderRows();
    setImportStatus(`已添加 ${fund.name} ✅`,'pos');
    $('#codeSearchInput').value=''; $('#codeSearchAmount').value='';
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

document.addEventListener('DOMContentLoaded', init);

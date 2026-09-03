'use client';
import { useEffect, useState } from 'react';
const API = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8001';

async function safeFetch(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return { _error: `${r.status} ${r.statusText}`, _url: url };
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('application/json')) return await r.json();
    return await r.text();
  } catch (e) {
    return { _error: e.message, _url: url };
  }
}

export default function Dashboard() {
  const [products,setProducts]=useState([]);
  const [orders,setOrders]=useState([]);
  const [audit,setAudit]=useState([]);
  const [recs,setRecs]=useState([]);
  const [health,setHealth]=useState(null);
  const [events,setEvents]=useState([]);
  const [kpis,setKpis]=useState(null);
  const [traces,setTraces]=useState([]);
  const [opps,setOpps]=useState([]);
  const [camps,setCamps]=useState([]);
  const [errs,setErrs]=useState([]);
  const [chat,setChat]=useState(''); const [chatLog,setChatLog]=useState([]);

  useEffect(()=>{
    (async()=>{
      const e=[];
      const h = await safeFetch(API+'/health');
      if (h._error) e.push(`health: ${h._error}`); else setHealth(h);
      const p = await safeFetch(API+'/api/v1/products');
      if (p._error) e.push(`products: ${p._error}`); else setProducts(Array.isArray(p) ? p : (p.products || p.items || []));
      const o = await safeFetch(API+'/api/v1/orders');
      if (o._error) e.push(`orders: ${o._error}`); else setOrders(Array.isArray(o) ? o : (o.orders || []));
      const a = await safeFetch(API+'/api/v1/audit?merchant_id=m_demo&limit=8');
      if (a._error) e.push(`audit: ${a._error}`); else setAudit(Array.isArray(a) ? a : (a.audit || []));
      const r = await safeFetch(API+'/api/v1/recommendations/cross-sell?product_id=prod_kb1');
      if (r._error) e.push(`recs: ${r._error}`); else setRecs(r.recommendations || r.candidates || []);
      const ev = await safeFetch(API+'/api/v1/events?limit=6');
      if (!ev._error) setEvents(Array.isArray(ev) ? ev : []);
      const kp = await safeFetch(API+'/api/v1/evaluation/kpis');
      if (!kp._error) setKpis(kp);
      const tr = await safeFetch(API+'/api/v1/traces?limit=3');
      if (!tr._error) setTraces(tr.traces || []);
      const op = await safeFetch(API+'/growth/opportunities');
      if (!op._error) setOpps(op.opportunities || []);
      const ca = await safeFetch(API+'/api/v1/campaigns?merchant_id=m_demo');
      if (!ca._error) setCamps(ca.campaigns || []);
      if (e.length) setErrs(e);
    })();
  },[]);

  const askAgent = async ()=>{
    if(!chat.trim()) return;
    const q=chat; setChat('');
    const res = await safeFetch(API+'/api/v1/agent/chat');
    // real call is POST, but safeFetch is GET helper; do POST separately with error handling
    try{
      const r = await fetch(API+'/api/v1/agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({merchant_id:'m_demo',message:q})});
      const j = r.ok ? await r.json() : {reply:`${r.status} ${await r.text()}`.slice(0,400)};
      setChatLog([...chatLog,{q,a:j}]);
    }catch(err){ setChatLog([...chatLog,{q,a:{reply:`fetch failed: ${err.message}`}}]); }
  };

  const askGrowth = async ()=>{
    try{
      const r = await fetch(API+'/api/v1/growth-agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({merchant_id:'m_demo',message:'Find best growth opportunity'})});
      const j = r.ok ? await r.json() : {_error: await r.text()};
      setChatLog([...chatLog,{q:'[growth-agent] Find opportunity',a:{reply:(j.final_reply||j._error||JSON.stringify(j)).slice(0,800), groq:true}}]);
    }catch(err){ setChatLog([...chatLog,{q:'[growth-agent]',a:{reply:err.message}}]); }
  };

  const revenue = orders.filter(o=>o.status==='paid').reduce((s,o)=>s+o.total,0)/100;
  return (
    <div className="min-h-screen p-6 max-w-7xl mx-auto bg-black text-zinc-100">
      <header className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Merchant Autonomous Growth & Commerce Agent <span className="text-sm font-normal text-zinc-400">v{health?.version || '0.17.0'} — Events + Traces + Evaluation live</span></h1>
        <div className="text-xs bg-zinc-800 px-3 py-1 rounded">Backend {health?.version || '...'} | {health?.groq} | razorpay:{health?.razorpay} | db:{health?.db?.slice(0,22)}</div>
      </header>
      {errs.length>0 && <div className="bg-amber-950 border border-amber-800 text-amber-200 text-xs p-2 rounded mb-4">Fetch warnings: {errs.join(' | ')} — backend must be on {API} (uvicorn --port 8001). Check <a className="underline" href={API+'/health'} target="_blank">{API}/health</a> and <a className="underline" href={API+'/docs'} target="_blank">/docs</a></div>}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">REVENUE (paid)</div><div className="text-2xl">₹{revenue.toFixed(0)}</div><div className="text-xs text-emerald-400">orders {orders.length} • conv {kpis?.commerce?.conversion_pct || '?'}%</div></div>
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">ORDERS</div><div className="text-2xl">{orders.length}</div><div className="text-xs">{orders.filter(o=>o.status==='paid').length} paid • AOV ₹{kpis?.commerce?.aov_inr || '?'}</div></div>
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">PRODUCTS</div><div className="text-2xl">{products.length}</div><div className="text-xs">catalog • growth {recs.length} recs</div></div>
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">HEALTH</div><div className="text-xs break-all">{API}/health — {health?.status || 'checking'} • traces {traces.length} • events {events.length}</div><div className="text-xs text-sky-400"><a href={API+'/docs'} target="_blank">Swagger</a> • <a href={API+'/.well-known/ucp'} target="_blank">UCP</a> • <a href={API+'/api/v1/evaluation'} target="_blank">Evaluation</a></div></div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-3">Products — agent-readable catalog</h2>
            <table className="w-full text-sm"><thead className="text-zinc-500"><tr><th className="text-left">Name</th><th>Category</th><th>Price</th><th>Stock</th></tr></thead><tbody>{products.map(p=><tr key={p.id} className="border-t border-zinc-800"><td>{p.name}</td><td className="text-center">{p.category}</td><td className="text-center">₹{(p.price/100).toFixed(0)}</td><td className="text-center">{p.stock}</td></tr>)}{products.length===0 && <tr><td colSpan={4} className="text-center text-zinc-500 py-4">No products — is backend running on {API}?</td></tr>}</tbody></table>
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-3">Orders + Checkout state machine</h2>
            <table className="w-full text-sm"><thead className="text-zinc-500"><tr><th>ID</th><th>Total</th><th>Status</th></tr></thead><tbody>{orders.slice(0,8).map(o=><tr key={o.id} className="border-t border-zinc-800"><td className="text-xs">{o.id.slice(0,14)}</td><td className="text-center">₹{(o.total/100).toFixed(0)}</td><td className="text-center"><span className={"px-2 py-0.5 rounded text-xs "+(o.status==='paid'?'bg-emerald-900':'bg-zinc-800')}>{o.status}</span></td></tr>)}{orders.length===0 && <tr><td colSpan={3} className="text-center text-zinc-500 py-4">No orders yet</td></tr>}</tbody></table>
            {kpis && <div className="text-xs text-zinc-400 mt-2">Completion {kpis.commerce.completion_rate_pct}% • Growth incremental ₹{kpis.growth.expected_incremental_inr} expected • Reliability payment {kpis.reliability.payment_success_pct}%</div>}
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-3">AI Action — Why did the agent do this? (Explainability)</h2>
            {recs.map((r,i)=><div key={i} className="border border-zinc-800 rounded p-3 mb-2"><div className="font-medium">{r.product.name} — ₹{(r.product.price/100).toFixed(0)}</div><div className="text-xs text-zinc-400">Reason: {r.reason}</div><div className="text-xs">Recommendation score: {r.recommendation_score ?? r.score} | Affinity {(r.affinity*100).toFixed(0)}% {r.expected_uplift_pct?`• Uplift ${r.expected_uplift_pct}%`:``} {r.note?`• ${r.note}`:``}</div></div>)}{recs.length===0 && <div className="text-xs text-zinc-500">No recommendations — seed orders first</div>}
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Growth Opportunities — Evidence Pipeline</h2>
            <div className="text-xs text-zinc-400 mb-2">Orders → Profiles → Affinity → Expected Revenue → Recommendation → Outcome</div>
            {opps.map((o,i)=><div key={i} className="border border-zinc-800 rounded p-2 mb-2"><div className="font-medium">{o.context_category} → {o.recommend || o.recommend_category} — ₹{o.expected_revenue_inr || 0} expected</div><div className="text-zinc-400">{o.opportunity}</div><div className="text-zinc-500">{o.evidence} • score {o.score}</div></div>)}{opps.length===0 && <div className="text-zinc-500">No strong opportunities — need more orders</div>}
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Campaigns — Proposed → Approved → Active → Measured</h2>
            {camps.slice(0,4).map(c=><div key={c.id} className="border border-zinc-800 rounded p-2 mb-2"><div className="font-medium text-xs">{c.name} — {c.status}</div><div className="text-xs text-zinc-400">{c.reason}</div><div className="text-xs">Expected ₹{c.expected_inr} {c.measured_inr?`• Measured ₹${c.measured_inr} (${c.measured_conversions} conv)`:``}</div></div>)}{camps.length===0 && <div className="text-zinc-500 text-xs">No campaigns — propose via POST /api/v1/campaigns/propose</div>}
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Traces — TRACE #92AF (OpenTelemetry-style)</h2>
            <div className="text-xs space-y-2 max-h-64 overflow-auto">{traces.map(t=><div key={t.trace_id} className="border border-zinc-800 rounded p-2"><div className="font-mono">{t.trace_id.slice(0,8)} — {t.name} {t.duration_ms?`• ${t.duration_ms}ms`:''}</div>{t.spans.map(s=><div key={s.span_id} className="ml-4 text-zinc-400">↳ {s.name} {s.duration_ms?`${s.duration_ms}ms`:''} {s.status}</div>)}</div>)}{traces.length===0 && <div className="text-zinc-500">No traces yet — trigger a UCP checkout or agent run</div>}</div>
          </div>
        </div>
        <div className="space-y-6">
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Shopper / AI Chat (Groq {health?.groq})</h2>
            <div className="h-64 overflow-auto bg-black rounded p-2 text-xs space-y-2 mb-2">{chatLog.map((c,i)=><div key={i}><div className="text-sky-300">You: {c.q}</div><div className="text-zinc-300 whitespace-pre-wrap">Agent: {c.a.reply || c.a.final_reply || JSON.stringify(c.a).slice(0,400)} {c.a.groq?'(groq)':''}</div></div>)}{chatLog.length===0 && <div className="text-zinc-600">Try: Find me a gaming keyboard under 3000</div>}</div>
            <div className="flex gap-2"><input value={chat} onChange={e=>setChat(e.target.value)} onKeyDown={e=>e.key==='Enter'&&askAgent()} placeholder="I need a gaming keyboard..." className="flex-1 bg-zinc-800 rounded px-2 py-1 text-sm"/><button onClick={askAgent} className="bg-white text-black px-3 py-1 rounded text-sm">Send</button></div>
            <button onClick={askGrowth} className="mt-2 w-full bg-emerald-900 text-emerald-100 rounded py-1 text-xs">Run Growth Agent (evidence table)</button>
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Agent Activity — Audit Ledger</h2>
            <div className="space-y-1 text-xs max-h-64 overflow-auto">{audit.map(a=><div key={a.id} className="border-l-2 pl-2 py-1" style={{borderColor: a.result==='success'?'#22c55e': a.result==='captured'?'#22c55e': a.result==='escalated'?'#f59e0b':'#444'}}><div>{new Date(a.timestamp).toLocaleTimeString()} — {a.action}</div><div className="text-zinc-500">{a.reason} {a.amount?`₹${(a.amount/100).toFixed(0)}`:''} | {a.policy_result} | risk {a.risk_score}</div></div>)}{audit.length===0 && <div className="text-zinc-500">No audit events — add to cart / checkout to generate</div>}</div>
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Events — Redis Streams (fallback memory)</h2>
            <div className="text-xs space-y-1 max-h-48 overflow-auto">{events.slice(-6).map(e=><div key={e.event_id} className="border-l pl-2" style={{borderColor:'#444'}}><span className="text-sky-300">{e.type}</span> <span className="text-zinc-500">{e.event_id}</span></div>)}{events.length===0 && <div className="text-zinc-500">No events — create a cart to emit cart.created</div>}</div>
            <div className="text-xs text-zinc-500 mt-2"><a className="text-sky-400" href={API+'/docs'} target="_blank">/docs</a> • <a className="text-sky-400" href={API+'/.well-known/ucp'} target="_blank">UCP</a> • <a className="text-sky-400" href={API+'/api/v1/evaluation'} target="_blank">Evaluation</a></div>
          </div>
        </div>
      </div>
    </div>
  );
}

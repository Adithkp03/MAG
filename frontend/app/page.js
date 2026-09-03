
'use client';
import { useEffect, useState } from 'react';
const API = 'http://127.0.0.1:8001';
export default function Dashboard() {
  const [products,setProducts]=useState([]);
  const [orders,setOrders]=useState([]);
  const [audit,setAudit]=useState([]);
  const [recs,setRecs]=useState([]);
  const [health,setHealth]=useState(null);
  const [chat,setChat]=useState(''); const [chatLog,setChatLog]=useState([]); const [cartId,setCartId]=useState(null);
  useEffect(()=>{
    fetch(API+'/api/v1/products').then(r=>r.json()).then(setProducts);
    fetch(API+'/api/v1/orders').then(r=>r.json()).then(d=>setOrders(Array.isArray(d)?d:[]));
    fetch(API+'/api/v1/audit?merchant_id=m_demo&limit=8').then(r=>r.json()).then(setAudit);
    fetch(API+'/api/v1/recommendations/cross-sell?product_id=prod_kb1').then(r=>r.json()).then(d=>setRecs(d.recommendations||[]));
    fetch(API+'/health').then(r=>r.json()).then(setHealth);
  },[]);
  const askAgent = async ()=>{
    const res = await fetch(API+'/api/v1/agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({merchant_id:'m_demo',message:chat})});
    const j=await res.json(); setChatLog([...chatLog,{q:chat,a:j}]); setChat('');
  };
  const revenue = orders.filter(o=>o.status==='paid').reduce((s,o)=>s+o.total,0)/100;
  return (
    <div className="min-h-screen p-6 max-w-7xl mx-auto">
      <header className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Merchant Autonomous Growth & Commerce Agent <span className="text-sm font-normal text-zinc-400">Phase 7 — Trust + Growth live</span></h1>
        <div className="text-xs bg-zinc-800 px-3 py-1 rounded">Backend {health?.version || '...'} | {health?.groq} | razorpay:{health?.razorpay} | ngrok: e809-... | Supabase</div>
      </header>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">REVENUE (paid)</div><div className="text-2xl">₹{revenue.toFixed(0)}</div><div className="text-xs text-emerald-400">AI uplift via cross-sell</div></div>
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">ORDERS</div><div className="text-2xl">{orders.length}</div><div className="text-xs">{orders.filter(o=>o.status==='paid').length} paid</div></div>
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">PRODUCTS</div><div className="text-2xl">{products.length}</div><div className="text-xs">pgvector-ready catalog</div></div>
        <div className="bg-zinc-900 p-4 rounded border border-zinc-800"><div className="text-zinc-400 text-xs">WEBHOOK</div><div className="text-xs break-all">https://e809...ngrok-free.app/api/v1/webhooks/razorpay</div><div className="text-xs text-amber-300">dedup + HMAC</div></div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-3">Products — agent-readable catalog</h2>
            <table className="w-full text-sm"><thead className="text-zinc-500"><tr><th className="text-left">Name</th><th>Category</th><th>Price</th><th>Stock</th></tr></thead><tbody>{products.map(p=><tr key={p.id} className="border-t border-zinc-800"><td>{p.name}</td><td className="text-center">{p.category}</td><td className="text-center">₹{(p.price/100).toFixed(0)}</td><td className="text-center">{p.stock}</td></tr>)}</tbody></table>
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-3">Orders + Checkout state machine</h2>
            <table className="w-full text-sm"><thead className="text-zinc-500"><tr><th>ID</th><th>Total</th><th>Status</th></tr></thead><tbody>{orders.slice(0,6).map(o=><tr key={o.id} className="border-t border-zinc-800"><td className="text-xs">{o.id.slice(0,12)}</td><td className="text-center">₹{(o.total/100).toFixed(0)}</td><td className="text-center"><span className={"px-2 py-0.5 rounded text-xs "+(o.status==='paid'?'bg-emerald-900':'bg-zinc-800')}>{o.status}</span></td></tr>)}</tbody></table>
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-3">AI Action — Why did the agent do this? (Explainability)</h2>
            {recs.map((r,i)=><div key={i} className="border border-zinc-800 rounded p-3 mb-2"><div className="font-medium">{r.product.name} — ₹{(r.product.price/100).toFixed(0)}</div><div className="text-xs text-zinc-400">Reason: {r.reason}</div><div className="text-xs">Expected uplift: {r.expected_uplift_pct}% | Policy: {r.policy_note} ✓ in stock</div></div>)}
            <div className="text-xs text-zinc-500 mt-2">Example: Customer purchased gaming laptop → 31% of similar bought mouse → Inventory 82 → uplift 8.4% → discount ≤10% ✓</div>
          </div>
        </div>
        <div className="space-y-6">
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Shopper / AI Chat (Groq {health?.groq})</h2>
            <div className="h-64 overflow-auto bg-black rounded p-2 text-xs space-y-2 mb-2">{chatLog.map((c,i)=><div key={i}><div className="text-sky-300">You: {c.q}</div><div className="text-zinc-300">Agent: {c.a.reply} {c.a.groq?'(groq)':''}</div>{c.a.tool_call && <div className="text-amber-300">Tool {c.a.tool_call.name} → {c.a.tool_call.result?.length||1} result(s)</div>}{c.a.products && <div>{c.a.products.map(p=>p.name).join(', ')}</div>}</div>)}{chatLog.length===0 && <div className="text-zinc-600">Try: Find me a gaming keyboard under 3000</div>}</div>
            <div className="flex gap-2"><input value={chat} onChange={e=>setChat(e.target.value)} onKeyDown={e=>e.key==='Enter'&&askAgent()} placeholder="I need a gaming keyboard..." className="flex-1 bg-zinc-800 rounded px-2 py-1 text-sm"/><button onClick={askAgent} className="bg-white text-black px-3 py-1 rounded text-sm">Send</button></div>
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Agent Activity — Audit Ledger</h2>
            <div className="space-y-1 text-xs max-h-80 overflow-auto">{audit.map(a=><div key={a.id} className="border-l-2 pl-2 py-1" style={{borderColor: a.result==='success'?'#22c55e': a.result==='captured'?'#22c55e': a.result==='escalated'?'#f59e0b':'#444'}}><div>{new Date(a.timestamp).toLocaleTimeString()} — {a.action}</div><div className="text-zinc-500">{a.reason} {a.amount?`₹${(a.amount/100).toFixed(0)}`:''} | {a.policy_result} | risk {a.risk_score}</div></div>)}</div>
            <div className="text-xs text-zinc-500 mt-2">LLM → Tool Gateway → Policy → Authorization → Commerce → Razorpay → Webhook → Audit</div>
          </div>
          <div className="bg-zinc-900 rounded border border-zinc-800 p-4">
            <h2 className="font-semibold mb-2">Quick flows</h2>
            <div className="text-xs space-y-1 text-zinc-400"><div>User → AI Agent → search → cart → policy → Razorpay → webhook → order → audit</div><div className="mt-2"><a href="http://127.0.0.1:8001/docs" target="_blank" className="text-sky-400">Swagger /docs</a> • <a href="http://127.0.0.1:8001/.well-known/ucp" target="_blank" className="text-sky-400">UCP profile</a></div></div>
          </div>
        </div>
      </div>
    </div>
  );
}

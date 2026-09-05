"use client";
import { useEffect, useState } from "react";
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const MERCHANT_KEY = process.env.NEXT_PUBLIC_MERCHANT_KEY || "demo_key_123";
function authHeaders(extra={}){ return {"X-Merchant-Id":"m_demo","X-API-Key":MERCHANT_KEY,"Content-Type":"application/json",...extra}; }
async function safeFetch(url, opts={}){
 try{ const r=await fetch(url, opts); const j=await r.json().catch(()=>({})); return { ok:r.ok, status:r.status, data:j }; }catch(e){ return{ ok:false, status:0, data:{error:e.message}}; }
}
export default function Page(){
 const [health,setHealth]=useState(null); const [products,setProducts]=useState([]); const [opps,setOpps]=useState([]); const [customers,setCustomers]=useState([]); const [prodIntel,setProdIntel]=useState([]); const [objectives,setObjectives]=useState(null); const [campaigns,setCampaigns]=useState([]); const [warnings,setWarnings]=useState([]); const [running,setRunning]=useState(false); const [explain,setExplain]=useState(null); const [campDetail,setCampDetail]=useState(null);
 const [version,setVersion]=useState("0.20.0");
 async function load(){
  const warns=[];
  const h=await safeFetch(API+"/health"); if(h.ok){ setHealth(h.data); setVersion(h.data.version||"0.20.0"); } else warns.push("health");
  const headers=authHeaders();
  const p=await safeFetch(API+"/api/v1/products",{headers}); if(p.ok) setProducts(Array.isArray(p.data)?p.data: p.data.products||[]); else warns.push("products");
  const o=await safeFetch(API+"/api/v1/opportunities?merchant_id=m_demo",{headers}); if(o.ok) setOpps(o.data.opportunities||[]); else warns.push("opps");
  const c=await safeFetch(API+"/api/v1/intelligence/customers?merchant_id=m_demo",{headers}); if(c.ok) setCustomers(c.data.customers||[]); else warns.push("customers");
  const pi=await safeFetch(API+"/api/v1/intelligence/products?merchant_id=m_demo",{headers}); if(pi.ok) setProdIntel(pi.data.products||[]); else warns.push("prodIntel");
  const obj=await safeFetch(API+"/api/v1/merchant/objectives?merchant_id=m_demo",{headers}); if(obj.ok) setObjectives(obj.data); else warns.push("objectives");
  const camps=await safeFetch(API+"/api/v1/campaigns?merchant_id=m_demo",{headers}); if(camps.ok) setCampaigns(camps.data.campaigns||camps.data||[]); else warns.push("camps");
  setWarnings(warns);
 }
 useEffect(()=>{ load(); },[]);
 async function runMAG(){
  setRunning(true);
  try{
   let r=await safeFetch(API+"/api/v1/autonomous/run?merchant_id=m_demo",{method:"POST",headers:authHeaders()});
   if(!r.ok){
    await safeFetch(API+"/api/v1/opportunities/detect?merchant_id=m_demo",{method:"POST",headers:authHeaders()});
   }
   await load();
  } finally { setRunning(false); }
 }
 async function doExplain(id){ const r=await safeFetch(API+"/api/v1/explain/"+id,{headers:authHeaders()}); if(r.ok) setExplain(r.data); }
 async function planOpp(id){ const r=await safeFetch(API+"/api/v1/opportunities/"+id+"/plan",{method:"POST",headers:authHeaders()}); await load(); alert(r.ok? "Planned "+(r.data.campaign_id||""): JSON.stringify(r.data)); }
 async function openCampaign(id){ const r=await safeFetch(API+"/api/v1/campaigns/"+id,{headers:authHeaders()}); if(r.ok) setCampDetail(r.data); }
 return (
  <div className="min-h-screen bg-[#fafafa] text-gray-900 font-sans p-6">
   <div className="max-w-6xl mx-auto space-y-6">
    {/* TOP — Health + Controls + KPIs */}
    <div className="flex justify-between items-center pb-4 border-b border-gray-200">
     <div>
      <h1 className="text-2xl font-black tracking-tight text-gray-900">MAG GROWTH CONTROL CENTER</h1>
      <div className="text-sm font-medium text-gray-500 mt-1">Autonomous Growth v{version} — {health ? health.status : "Connecting..."}</div>
     </div>
     <button onClick={runMAG} disabled={running} className="bg-black hover:bg-gray-800 text-white transition-colors duration-200 px-6 py-3 rounded-xl font-bold text-sm shadow-sm flex items-center gap-2">
      {running ? "Running Analysis…" : "▶ Run MAG Analysis"}
     </button>
    </div>

    {warnings.length > 0 && <div className="bg-red-50 text-red-700 border border-red-100 px-4 py-3 rounded-xl text-sm font-medium shadow-sm">Warnings: {warnings.join(", ")}</div>}

    {/* Metrics Row */}
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
     <div className="bg-white p-5 rounded-2xl shadow-sm border border-gray-100 flex flex-col justify-center hover:shadow-md transition-shadow">
      <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Revenue Products</div>
      <div className="text-2xl font-black text-gray-900">{products.length}</div>
     </div>
     <div className="bg-white p-5 rounded-2xl shadow-sm border border-gray-100 flex flex-col justify-center hover:shadow-md transition-shadow">
      <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Avg Margin</div>
      <div className="text-2xl font-black text-gray-900">{prodIntel.length ? (prodIntel.reduce((a,p)=>a+p.margin_pct,0)/prodIntel.length).toFixed(0) : 0}%</div>
     </div>
     <div className="bg-white p-5 rounded-2xl shadow-sm border border-gray-100 flex flex-col justify-center hover:shadow-md transition-shadow">
      <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Customers</div>
      <div className="text-2xl font-black text-gray-900">{customers.length}</div>
      <div className="text-xs font-semibold text-red-500 mt-1">{customers.filter(c=>c.churn_prob>0.6).length} at-risk</div>
     </div>
     <div className="bg-white p-5 rounded-2xl shadow-sm border border-gray-100 flex flex-col justify-center hover:shadow-md transition-shadow">
      <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Opportunities</div>
      <div className="text-2xl font-black text-gray-900">{opps.length}</div>
     </div>
    </div>

    {/* Opportunities Section */}
    {/* CENTER — Scored Opportunities + Explain */}
    <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100">
     <div className="flex justify-between items-end mb-4">
      <h2 className="text-lg font-bold text-gray-900 tracking-tight">Opportunities <span className="ml-2 px-2 py-1 bg-gray-100 text-gray-600 rounded-lg text-xs">{opps.length} detected</span></h2>
      <span className="text-xs font-medium text-gray-400">Score = Value(objective) × Prob − Cost − Risk</span>
     </div>
     
     {opps.length === 0 ? (
      <div className="text-sm text-gray-500 font-medium py-8 text-center bg-gray-50 rounded-xl border border-dashed border-gray-200">
       No opportunities detected. Click "Run MAG Analysis" to scan for growth strategies.
      </div>
     ) : (
      <div className="space-y-3">
       {opps.slice(0,7).map(o=>(
        <div key={o.opportunity_id} className="flex justify-between items-center bg-gray-50 hover:bg-gray-100 transition-colors p-4 rounded-2xl border border-gray-100">
         <div>
          <div className="font-bold text-sm text-gray-900">{o.type} <span className="text-gray-500 font-medium ml-1">— {o.recommended_action}</span></div>
          <div className="text-xs font-medium text-gray-500 mt-1">Conf {(o.confidence*100).toFixed(0)}% • Risk {typeof o.risk==='number' ? (o.risk*100).toFixed(0)+'%' : o.risk} • Priority {o.priority}</div>
          {o.evidence && (o.evidence.conv_source||o.evidence.affinity) && <div className="text-xs font-medium text-indigo-600 mt-1">Evidence: {o.evidence.affinity!=null?Math.round(o.evidence.affinity*100)+"% attach • ":""}{o.evidence.conv!=null?"conv "+(o.evidence.conv*100).toFixed(1)+"% ("+o.evidence.conv_source+", n="+(o.evidence.conv_sample||o.evidence.order_count||"?")+")":""}{o.evidence.margin_estimated?" • margin estimated":""}</div>}
         </div>
         <div className="text-right">
          <div className="font-bold text-green-600 text-sm">₹{o.expected_revenue_inr} rev <span className="text-gray-300 mx-1">|</span> ₹{o.expected_margin_inr} margin</div>
          <div className="flex gap-2 justify-end mt-2">
           <button onClick={()=>doExplain(o.opportunity_id)} className="text-xs bg-white text-gray-700 hover:bg-gray-200 border border-gray-200 font-semibold px-3 py-1.5 rounded-lg transition-colors">Explain</button>
           <button onClick={()=>planOpp(o.opportunity_id)} className="text-xs bg-black text-white hover:bg-gray-800 font-semibold px-3 py-1.5 rounded-lg transition-colors shadow-sm">Plan</button>
          </div>
         </div>
        </div>
       ))}
      </div>
     )}
     {explain && (
      <div className="mt-4 bg-indigo-50 border border-indigo-100 p-4 rounded-2xl text-sm text-indigo-900 shadow-sm">
       <b className="font-bold block mb-1">{explain.opportunity_id}</b>
       <p className="mb-2">{explain.WHY}</p>
       <div className="text-xs opacity-80 font-mono mb-2 bg-indigo-100/50 p-2 rounded-lg break-all">Evidence: {JSON.stringify(explain.EVIDENCE)}</div>
       <div className="font-semibold text-indigo-700">Impact: ₹{explain.IMPACT?.expected_revenue_inr} • Risk: {explain.RISK}</div>
      </div>
     )}
    </div>

    {/* Objective */}
    <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100">
     <h2 className="text-lg font-bold text-gray-900 tracking-tight mb-4">Merchant Objective</h2>
     {objectives ? (
      <div className="flex flex-wrap gap-3">
       <span className="bg-gray-50 border border-gray-100 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600">Primary: <b className="text-gray-900">{objectives.primary_objective}</b></span>
       <span className="bg-gray-50 border border-gray-100 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600">Risk: <b className="text-gray-900">{objectives.risk_tolerance}</b></span>
       <span className="bg-gray-50 border border-gray-100 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600">Min Margin: <b className="text-gray-900">{objectives.min_margin_pct}%</b></span>
       <span className="bg-gray-50 border border-gray-100 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600">Max Discount: <b className="text-gray-900">{objectives.max_discount}%</b></span>
       <span className="bg-gray-50 border border-gray-100 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600">Budget: <b className="text-gray-900">₹{(objectives.max_campaign_budget/100).toFixed(0)}</b></span>
      </div>
     ) : <div className="text-sm text-gray-400 font-medium">Loading objectives...</div>}
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
     {/* Customer Intel */}
     <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100">
      <h3 className="text-sm font-bold tracking-tight text-gray-900 uppercase mb-4">Customer Intelligence</h3>
      <div className="space-y-3">
       {customers.slice(0,5).map(c=>(
        <div key={c.customer_id} className="flex justify-between items-center pb-3 border-b border-gray-50 last:border-0 last:pb-0">
         <div>
          <div className="font-semibold text-sm text-gray-800">{c.customer_id}</div>
          <div className="text-xs font-medium text-gray-400 mt-0.5">{c.segment} • RFM {c.rfm}</div>
         </div>
         <div className="text-right">
          <div className="font-bold text-sm text-gray-900">₹{c.clv_inr} <span className="text-gray-400 font-normal text-xs ml-1">CLV</span></div>
          <div className={`text-xs font-bold mt-0.5 ${c.churn_prob > 0.6 ? 'text-red-500' : 'text-green-500'}`}>
           {(c.churn_prob*100).toFixed(0)}% churn
          </div>
         </div>
        </div>
       ))}
      </div>
     </div>

     {/* Product Intel */}
     <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100">
      <h3 className="text-sm font-bold tracking-tight text-gray-900 uppercase mb-4">Product Intelligence</h3>
      <div className="space-y-3">
       {prodIntel.slice(0,5).map(p=>(
        <div key={p.product_id} className="flex justify-between items-center pb-3 border-b border-gray-50 last:border-0 last:pb-0">
         <div>
          <div className="font-semibold text-sm text-gray-800 truncate max-w-[200px]">{p.name}</div>
          <div className="text-xs font-medium text-gray-400 mt-0.5">{p.velocity}/day • {p.doi} days inv</div>
         </div>
         <div className="text-right">
          <div className="font-bold text-sm text-gray-900">{p.margin_pct}%</div>
          <div className="text-xs text-gray-400 font-medium mt-0.5">margin</div>
         </div>
        </div>
       ))}
      </div>
     </div>
    </div>

    {/* Campaigns */}
    {/* BOTTOM — Campaigns + Agent Runs (18-step final acceptance) */}
    <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100">
     <h3 className="text-sm font-bold tracking-tight text-gray-900 uppercase mb-4">Active Campaigns</h3>
     {campaigns.length === 0 ? (
      <div className="text-sm text-gray-500 font-medium py-6 text-center bg-gray-50 rounded-xl border border-dashed border-gray-200">
       No active campaigns. Plan an opportunity to launch one.
      </div>
     ) : (
      <div className="space-y-3">
       {campaigns.slice(0,5).map(c=>(
        <div key={"wrap-"+(c.id||c.campaign_id)}><div onClick={()=>openCampaign(c.id||c.campaign_id)} className="cursor-pointer">
        <div key={c.id||c.campaign_id} className="flex justify-between items-center p-3 bg-gray-50 rounded-xl border border-gray-100">
         <div className="font-semibold text-sm text-gray-900">{c.name||c.id}</div>
         <div className="flex items-center gap-3">
          {c.discount && <span className="bg-green-100 text-green-700 font-bold px-2 py-0.5 rounded text-xs">{c.discount}% OFF</span>}
          <span className="text-xs font-bold uppercase tracking-wider text-gray-500">{c.status}</span>
         </div>
        </div></div>
       ))}
      </div>
     )}
     {campDetail && (
      <div className="mt-4 bg-amber-50 border border-amber-200 p-4 rounded-2xl text-sm text-amber-900">
       <div className="flex justify-between items-center mb-2"><b>{campDetail.campaign?.name}</b><button onClick={()=>setCampDetail(null)} className="text-xs underline">close</button></div>
       <div className="text-xs mb-2">Status: <b>{campDetail.campaign?.status}</b> • {campDetail.metrics?.some(m=>m.simulation_mode)?<span className="bg-amber-200 px-2 py-0.5 rounded font-bold">Demo simulation — not observed behavior</span>:<span className="bg-green-200 px-2 py-0.5 rounded font-bold">Observed</span>}</div>
       <div className="text-xs font-mono bg-amber-100/60 p-2 rounded-lg break-all mb-2">Reason: {campDetail.campaign?.reason}</div>
       <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="bg-white p-2 rounded-lg">Treatment: {campDetail.metrics?.[0]?.treatment_eligible ?? "?"} eligible • {campDetail.metrics?.[0]?.treatment_purchases ?? "?"} purch • ₹{(((campDetail.metrics?.[0]?.treatment_revenue)||0)/100).toFixed(0)}</div>
        <div className="bg-white p-2 rounded-lg">Control: {campDetail.metrics?.[0]?.control_eligible ?? "?"} eligible • {campDetail.metrics?.[0]?.control_purchases ?? "?"} purch • ₹{(((campDetail.metrics?.[0]?.control_revenue)||0)/100).toFixed(0)}</div>
        <div className="bg-white p-2 rounded-lg">Incremental: {campDetail.metrics?.[0]?.incremental_orders ?? "?"} orders • ₹{(((campDetail.metrics?.[0]?.incremental_revenue)||0)/100).toFixed(0)} rev • ₹{(((campDetail.metrics?.[0]?.incremental_margin)||0)/100).toFixed(0)} margin {campDetail.metrics?.[0]?.sample_adequate?"• adequate":"• small sample"}</div>
       </div>
      </div>
     )}
    </div>

    <div className="text-xs text-gray-400 font-medium text-center pt-4">
     API: {API} • <a href={API+"/docs"} className="text-black hover:underline">Swagger Docs</a>
    </div>

   </div>
  </div>
 );
}

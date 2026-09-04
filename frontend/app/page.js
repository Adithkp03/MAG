"use client";
import { useEffect, useState } from "react";
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8001";
async function safeFetch(url, opts={}){
 try{ const r=await fetch(url, opts); const j=await r.json().catch(()=>({})); return { ok:r.ok, status:r.status, data:j }; }catch(e){ return{ ok:false, status:0, data:{error:e.message}}; }
}
export default function Page(){
 const [health,setHealth]=useState(null); const [products,setProducts]=useState([]); const [opps,setOpps]=useState([]); const [customers,setCustomers]=useState([]); const [prodIntel,setProdIntel]=useState([]); const [objectives,setObjectives]=useState(null); const [campaigns,setCampaigns]=useState([]); const [warnings,setWarnings]=useState([]); const [running,setRunning]=useState(false); const [explain,setExplain]=useState(null);
 const [version,setVersion]=useState("0.20.0");
 async function load(){
  const warns=[];
  const h=await safeFetch(API+"/health"); if(h.ok){ setHealth(h.data); setVersion(h.data.version||"0.20.0"); } else warns.push("health");
  const p=await safeFetch(API+"/api/v1/products"); if(p.ok) setProducts(Array.isArray(p.data)?p.data: p.data.products||[]); else warns.push("products");
  const o=await safeFetch(API+"/api/v1/opportunities?merchant_id=m_demo"); if(o.ok) setOpps(o.data.opportunities||[]); else warns.push("opps");
  const c=await safeFetch(API+"/api/v1/intelligence/customers?merchant_id=m_demo"); if(c.ok) setCustomers(c.data.customers||[]); else warns.push("customers");
  const pi=await safeFetch(API+"/api/v1/intelligence/products?merchant_id=m_demo"); if(pi.ok) setProdIntel(pi.data.products||[]); else warns.push("prodIntel");
  const obj=await safeFetch(API+"/api/v1/merchant/objectives?merchant_id=m_demo"); if(obj.ok) setObjectives(obj.data); else warns.push("objectives");
  const camps=await safeFetch(API+"/api/v1/campaigns?merchant_id=m_demo"); if(camps.ok) setCampaigns(camps.data.campaigns||camps.data||[]); else warns.push("camps");
  setWarnings(warns);
 }
 useEffect(()=>{ load(); },[]);
 async function runMAG(){
  setRunning(true);
  let r=await safeFetch(API+"/api/v1/autonomous/run?merchant_id=m_demo",{method:"POST",headers:{"X-Merchant-Id":"m_demo","Content-Type":"application/json"}});
  if(!r.ok){
   await safeFetch(API+"/api/v1/opportunities/detect?merchant_id=m_demo",{method:"POST",headers:{"X-Merchant-Id":"m_demo"}});
  }
  await load(); setRunning(false);
 }
 async function doExplain(id){ const r=await safeFetch(API+"/api/v1/explain/"+id); if(r.ok) setExplain(r.data); }
 async function planOpp(id){ const r=await safeFetch(API+"/api/v1/opportunities/"+id+"/plan",{method:"POST",headers:{"X-Merchant-Id":"m_demo"}}); await load(); alert(r.ok? "Planned "+(r.data.campaign_id||""): JSON.stringify(r.data)); }
 return (<div style={{fontFamily:"system-ui,sans-serif",background:"#0a0a0f",color:"#e5e7eb",minHeight:"100vh",padding:"24px"}}>
  <div style={{maxWidth:"1200px",margin:"0 auto"}}>
   <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",borderBottom:"1px solid #222",paddingBottom:"12px",marginBottom:"16px"}}>
    <div><h1 style={{fontSize:"22px",fontWeight:800}}>MAG GROWTH CONTROL CENTER</h1><div style={{color:"#9ca3af",fontSize:"12px"}}>Autonomous Growth v{version} — {health?health.status:""}</div></div>
    <button onClick={runMAG} disabled={running} style={{background:running?"#333":"#7c3aed",color:"#fff",padding:"12px 20px",borderRadius:"10px",fontWeight:700,border:"none",cursor:"pointer"}}>{running?"Running…":"▶ Run MAG Analysis"}</button>
   </div>
   {warnings.length>0 && <div style={{background:"#422006",color:"#fbbf24",padding:"8px 12px",borderRadius:"8px",marginBottom:"12px",fontSize:"12px"}}>Warnings: {warnings.join(", ")}</div>}
   <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:"12px",marginBottom:"16px"}}>
    <div style={{background:"#111827",padding:"16px",borderRadius:"12px"}}><div style={{color:"#9ca3af",fontSize:"11px"}}>REVENUE</div><div style={{fontSize:"20px",fontWeight:800}}>{products.length} products</div></div>
    <div style={{background:"#111827",padding:"16px",borderRadius:"12px"}}><div style={{color:"#9ca3af",fontSize:"11px"}}>AVG MARGIN</div><div style={{fontSize:"20px",fontWeight:800}}>{prodIntel.length? (prodIntel.reduce((a,p)=>a+p.margin_pct,0)/prodIntel.length).toFixed(0):0}%</div></div>
    <div style={{background:"#111827",padding:"16px",borderRadius:"12px"}}><div style={{color:"#9ca3af",fontSize:"11px"}}>CUSTOMERS</div><div style={{fontSize:"20px",fontWeight:800}}>{customers.length}</div><div style={{fontSize:"11px",color:"#6b7280"}}>{customers.filter(c=>c.churn_prob>0.6).length} at-risk</div></div>
    <div style={{background:"#111827",padding:"16px",borderRadius:"12px"}}><div style={{color:"#9ca3af",fontSize:"11px"}}>OPPORTUNITIES</div><div style={{fontSize:"20px",fontWeight:800}}>{opps.length}</div></div>
   </div>
   <div style={{background:"#111827",padding:"16px",borderRadius:"12px",marginBottom:"16px"}}>
    <div style={{display:"flex",justifyContent:"space-between",marginBottom:"10px"}}><h2 style={{fontWeight:700}}>OPPORTUNITIES — {opps.length} detected</h2><span style={{fontSize:"11px",color:"#9ca3af"}}>Score = Margin × Prob × Strategic − Cost − Risk</span></div>
    {opps.length===0? <div style={{color:"#6b7280",fontSize:"13px"}}>No opportunities — click Run MAG Analysis (10 types: cross-sell, upsell, churn, repeat, dead stock, high-margin, low-margin, stock-risk, high-value, abandoned)</div>:
    <div style={{display:"grid",gap:"8px"}}>
     {opps.slice(0,7).map(o=>(<div key={o.opportunity_id} style={{display:"flex",justifyContent:"space-between",alignItems:"center",background:"#0f172a",padding:"10px 12px",borderRadius:"8px",border:"1px solid #1f2937"}}>
      <div><div style={{fontWeight:600,fontSize:"13px"}}>{o.type} <span style={{color:"#9ca3af",fontWeight:400}}>— {o.recommended_action}</span></div><div style={{fontSize:"11px",color:"#9ca3af"}}>Conf {o.confidence} · Risk {o.risk} · Priority {o.priority}</div></div>
      <div style={{textAlign:"right"}}><div style={{fontWeight:700,color:"#34d399"}}>₹{o.expected_revenue_inr} rev · ₹{o.expected_margin_inr} margin</div><div style={{display:"flex",gap:"6px",justifyContent:"flex-end",marginTop:"4px"}}><button onClick={()=>doExplain(o.opportunity_id)} style={{fontSize:"11px",background:"#1f2937",color:"#e5e7eb",border:"none",padding:"4px 8px",borderRadius:"6px",cursor:"pointer"}}>Explain</button><button onClick={()=>planOpp(o.opportunity_id)} style={{fontSize:"11px",background:"#7c3aed",color:"#fff",border:"none",padding:"4px 8px",borderRadius:"6px",cursor:"pointer"}}>Plan</button></div></div>
     </div>))}
    </div>}
    {explain && <div style={{marginTop:"10px",background:"#1e1b4b",padding:"12px",borderRadius:"8px",fontSize:"12px"}}><b>{explain.opportunity_id}</b> {explain.WHY}<br/>Evidence {JSON.stringify(explain.EVIDENCE)}<br/>Impact ₹{explain.IMPACT.expected_revenue_inr} · Risk {explain.RISK}</div>}
   </div>
   <div style={{background:"#111827",padding:"16px",borderRadius:"12px",marginBottom:"16px"}}>
    <h2 style={{fontWeight:700,marginBottom:"8px"}}>MERCHANT OBJECTIVE</h2>
    {objectives? <div style={{fontSize:"12px",display:"flex",gap:"16px",flexWrap:"wrap"}}><span>Primary <b>{objectives.primary_objective}</b></span><span>Risk <b>{objectives.risk_tolerance}</b></span><span>Min margin {objectives.min_margin_pct}%</span><span>Max discount {objectives.max_discount}%</span><span>Max budget ₹{(objectives.max_campaign_budget/100).toFixed(0)}</span></div>:"loading…"}
   </div>
   <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"12px",marginBottom:"16px"}}>
    <div style={{background:"#111827",padding:"16px",borderRadius:"12px"}}><h3 style={{fontWeight:700,fontSize:"13px",marginBottom:"8px"}}>CUSTOMER INTELLIGENCE</h3>{customers.slice(0,5).map(c=>(<div key={c.customer_id} style={{fontSize:"11px",display:"flex",justifyContent:"space-between",borderBottom:"1px solid #1f2937",padding:"6px 0"}}><span>{c.customer_id} · {c.segment} · RFM {c.rfm}</span><span style={{color:c.churn_prob>0.6?"#f87171":"#34d399"}}>CLV ₹{c.clv_inr} · churn {(c.churn_prob*100).toFixed(0)}%</span></div>))}</div>
    <div style={{background:"#111827",padding:"16px",borderRadius:"12px"}}><h3 style={{fontWeight:700,fontSize:"13px",marginBottom:"8px"}}>PRODUCT INTELLIGENCE</h3>{prodIntel.slice(0,5).map(p=>(<div key={p.product_id} style={{fontSize:"11px",display:"flex",justifyContent:"space-between",borderBottom:"1px solid #1f2937",padding:"6px 0"}}><span>{p.name} · vel {p.velocity}/d · DOI {p.doi}d</span><span>margin {p.margin_pct}%</span></div>))}</div>
   </div>
   <div style={{background:"#111827",padding:"16px",borderRadius:"12px",marginBottom:"16px"}}>
    <h3 style={{fontWeight:700,marginBottom:"8px"}}>CAMPAIGNS</h3>
    {campaigns.length===0? <div style={{fontSize:"12px",color:"#6b7280"}}>No campaigns — Plan an opportunity, then approve & execute. Funnel: eligible → exposed → viewed → clicked → added → purchased → revenue/margin (10% holdout for incrementality).</div>: campaigns.slice(0,5).map(c=>(<div key={c.id||c.campaign_id} style={{fontSize:"12px",display:"flex",justifyContent:"space-between",padding:"6px 0",borderBottom:"1px solid #1f2937"}}><span>{c.name||c.id} — {c.status}</span><span>{c.discount?c.discount+"%":""}</span></div>))}
   </div>
   <div style={{fontSize:"11px",color:"#6b7280"}}>API {API} · <a href={API+"/docs"} style={{color:"#7c3aed"}}>docs</a></div>
  </div>
 </div>);
}

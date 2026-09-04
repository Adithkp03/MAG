#!/usr/bin/env python3
"""
Realistic merchant dataset simulator — deterministic with --seed 42.
Generates data/*.csv and seeds DB. Phase 2 acceptance:
  python backend/scripts/seed_realistic.py --seed 42 --reset
  -> same counts on re-run, CSVs in data/, merchant isolation.
"""
import argparse, csv, os, random, sys, json
from datetime import datetime, timedelta
from pathlib import Path

# allow import from backend
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Product catalog definition — realistic price bands INR -> paise
CATALOG = [
    ("keyboard", "Gaming Keyboard", 180000, 350000, 0.30, 80),
    ("keyboard", "Mechanical Keyboard TKL", 450000, 850000, 0.35, 40),
    ("mouse", "Wireless Gaming Mouse", 59900, 129900, 0.45, 120),
    ("mouse", "Ergonomic Mouse", 39900, 79900, 0.50, 150),
    ("laptop", "Gaming Laptop 16GB RTX4060", 6500000, 11000000, 0.12, 12),
    ("laptop", "Ultrabook 14in", 5500000, 8500000, 0.15, 15),
    ("headset", "Wireless Headset ANC", 249900, 449900, 0.38, 60),
    ("headset", "Wired Headset", 99900, 199900, 0.42, 90),
    ("mousepad", "XL Mousepad 900x400", 29900, 69900, 0.60, 200),
    ("bag", "Laptop Bag 15in", 99900, 199900, 0.40, 70),
    ("monitor", "27in 144Hz Monitor", 1800000, 3200000, 0.18, 25),
    ("chair", "Gaming Chair Ergonomic", 1500000, 2800000, 0.20, 20),
]

CATEGORIES = ["keyboard","mouse","laptop","headset","mousepad","bag","monitor","chair"]

# attach affinity matrix P(B|A) derived from realistic retail
AFFINITY = {
    "laptop": {"mouse": 0.45, "bag": 0.35, "headset": 0.25, "mousepad": 0.30, "monitor": 0.15},
    "keyboard": {"mouse": 0.30, "mousepad": 0.35, "headset": 0.15},
    "mouse": {"mousepad": 0.40, "keyboard": 0.20},
    "headset": {"mousepad": 0.10},
    "monitor": {"keyboard": 0.15, "mouse": 0.20},
}

def gen_products(rng, merchant_id, n=24):
    rows=[]
    for i in range(n):
        cat, base_name, pmin, pmax, margin_hint, stock_base = rng.choice(CATALOG)
        price = rng.randint(pmin, pmax)//100*100  # round to 1 INR
        # stock inversely correlated with price + noise
        stock = max(5, int(rng.gauss(stock_base, stock_base*0.35)))
        if price > 5000000: stock = max(3, int(rng.gauss(12, 5)))
        cost_price = int(price * (1 - rng.uniform(margin_hint-0.05, margin_hint+0.05)))
        rows.append({
            "id": f"prod_{merchant_id[-4:]}_{i+1:02d}",
            "merchant_id": merchant_id,
            "name": f"{base_name} {rng.choice(['Pro','Air','Max','Lite','RGB','Ultra'])} {i+1}",
            "category": cat,
            "price": price,
            "cost_price": cost_price,
            "margin_pct": round((price-cost_price)/price*100),
            "stock": stock,
            "description": f"{base_name} {cat} - realistic catalog"
        })
    return rows

def gen_customers(rng, merchant_id, n=120):
    rows=[]
    first_names=["Aarav","Vivaan","Aditya","Arjun","Reyansh","Sai","Aisha","Diya","Ananya","Kavya","Rohan","Priya","Neha","Amit","Sneha","Rahul","Pooja","Karan","Meera","Vikram"]
    last_names=["Sharma","Verma","Gupta","Patel","Kumar","Singh","Reddy","Nair","Joshi","Mehta"]
    for i in range(n):
        # recency + frequency skewed: pareto
        rows.append({
            "id": f"cust_{merchant_id[-4:]}_{i+1:03d}",
            "merchant_id": merchant_id,
            "name": f"{rng.choice(first_names)} {rng.choice(last_names)}",
            "email": f"cust{i+1:03d}_{merchant_id}@example.local",
            "phone": f"9{rng.randint(100000000,999999999)}",
        })
    return rows

def gen_orders(rng, merchant_id, products, customers, days=120, daily_lambda=4.5):
    orders=[]
    items=[]
    start = datetime.utcnow() - timedelta(days=days)
    oid=1
    for d in range(days):
        # weekly seasonality: weekends +15%, month-end +10%
        base = rng.poissonvariate(daily_lambda) if hasattr(rng, 'poissonvariate') else rng.randint(2,7)
        # use simple poisson via exp
        # fallback: deterministic count using gauss
        n_orders = max(0, int(rng.gauss(daily_lambda, 1.5)))
        # seasonality
        weekday = (start + timedelta(days=d)).weekday()
        if weekday in (5,6): n_orders = int(n_orders*1.15)
        if d % 30 in (28,29): n_orders = int(n_orders*1.10)
        # trend: growing 0.05% per day
        n_orders = max(0, int(n_orders * (1 + d*0.0005)))
        for _ in range(n_orders):
            cust = rng.choice(customers)
            # basket size: 1-3, attach logic
            # pick primary category weighted by product revenue
            primary = rng.choice(products)
            basket=[primary]
            # attach based on AFFINITY
            aff = AFFINITY.get(primary["category"], {})
            for cat, prob in aff.items():
                if rng.random() < prob * 0.6:  # dampen
                    cands=[p for p in products if p["category"]==cat]
                    if cands: basket.append(rng.choice(cands))
            # occasionally add random upsell
            if rng.random() < 0.08:
                basket.append(rng.choice(products))
            # dedup
            seen=set(); uniq=[]
            for p in basket:
                if p["id"] not in seen:
                    uniq.append(p); seen.add(p["id"])
            basket=uniq[:3]
            total = sum(p["price"] * (1 if p!=primary else 1) for p in basket)
            # quantity 1 mostly, 2 for cheap items
            qtys=[]
            for p in basket:
                q=1
                if p["price"] < 100000 and rng.random()<0.18: q=2
                qtys.append(q)
            total = sum(p["price"]*q for p,q in zip(basket,qtys))
            ts = start + timedelta(days=d, seconds=rng.randint(0,86399))
            oid_str = f"ord_{merchant_id[-4:]}_{oid:05d}"
            orders.append({
                "id": oid_str,
                "merchant_id": merchant_id,
                "customer_id": cust["id"],
                "total": total,
                "status": "paid",
                "created_at": ts.isoformat(),
            })
            for p,q in zip(basket, qtys):
                items.append({
                    "order_id": oid_str,
                    "product_id": p["id"],
                    "quantity": q,
                    "unit_price": p["price"],
                    "line_total": p["price"]*q,
                })
            oid+=1
    return orders, items

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--merchants", type=int, default=2, help="number of merchants to generate (1-2, second for isolation test)")
    args=ap.parse_args()
    rng=random.Random(args.seed)

    # merchants
    merchants=[
        {"id":"m_demo","name":"Demo Merchant","email":"merchant@demo.local"},
        {"id":"m_acme","name":"Acme Retail","email":"acme@example.local"},
    ][:args.merchants]

    all_products=[]; all_customers=[]; all_orders=[]; all_items=[]
    for m in merchants:
        prods=gen_products(rng, m["id"], n=24 if m["id"]=="m_demo" else 18)
        custs=gen_customers(rng, m["id"], n=120 if m["id"]=="m_demo" else 60)
        orders, items = gen_orders(rng, m["id"], prods, custs, days=120, daily_lambda=5 if m["id"]=="m_demo" else 2)
        all_products.extend(prods); all_customers.extend(custs); all_orders.extend(orders); all_items.extend(items)

    # write CSVs
    write_csv(DATA_DIR / "products.csv", all_products, ["id","merchant_id","name","category","price","cost_price","margin_pct","stock","description"])
    write_csv(DATA_DIR / "customers.csv", all_customers, ["id","merchant_id","name","email","phone"])
    write_csv(DATA_DIR / "orders.csv", all_orders, ["id","merchant_id","customer_id","total","status","created_at"])
    write_csv(DATA_DIR / "order_items.csv", all_items, ["order_id","product_id","quantity","unit_price","line_total"])
    write_csv(DATA_DIR / "merchants.csv", merchants, ["id","name","email"])
    # summary
    summary={"seed":args.seed,"merchants":len(merchants),"products":len(all_products),"customers":len(all_customers),"orders":len(all_orders),"items":len(all_items)}
    with open(DATA_DIR / "summary.json","w") as f: json.dump(summary,f,indent=2)
    print(f"CSV generated seed={args.seed}: {summary}")
    # seed DB if requested
    if args.reset or "--reset" in sys.argv:
        seed_db(merchants, all_products, all_customers, all_orders, all_items)

def seed_db(merchants, products, customers, orders, items):
    # import DB
    try:
        from app.core.database import Base, engine, SessionLocal
        from app.models.entities import Merchant, Customer, Product, Cart, CartItem, Checkout, Order, Policy, MerchantObjective, Payment
        from sqlalchemy import text
    except Exception as e:
        print(f"DB import failed (run from backend/): {e}")
        # try alternative path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.core.database import Base, engine, SessionLocal
        from app.models.entities import Merchant, Customer, Product, Cart, CartItem, Checkout, Order, Policy, MerchantObjective, Payment
        from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    # migrate new cols if missing
    with engine.connect() as conn:
        for ddl in [
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price INT",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS reserved INT DEFAULT 0",
            "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS api_key TEXT",
        ]:
            try: conn.execute(text(ddl)); conn.commit()
            except Exception as ex: print(f"migrate skip {ddl[:40]}: {ex}")
    db=SessionLocal()
    try:
        # clear existing data for idempotent reset - truncate leaf -> root with CASCADE
        db.rollback()
        # truncate in correct FK order using CASCADE to handle circular refs
        truncate_tables = [
            "audit_events","outbox_events","webhook_events","agent_tool_calls","agent_messages","agent_runs","agent_sessions",
            "campaign_metrics","campaign_runs","campaign_actions","campaign_audiences","campaigns",
            "opportunities","product_profiles","customer_profiles","approvals",
            "orders","payments","checkouts","cart_items","carts"
        ]
        for tbl in truncate_tables:
            try:
                db.execute(text(f'TRUNCATE TABLE "{tbl}" CASCADE'))
                db.commit()
            except Exception as e:
                db.rollback()
                # fallback delete
                try:
                    db.execute(text(f'DELETE FROM "{tbl}"'))
                    db.commit()
                except Exception as e2:
                    db.rollback()
        # products/customers after dependents cleared
        for tbl in ["products","customers"]:
            try:
                db.execute(text(f'TRUNCATE TABLE "{tbl}" CASCADE'))
                db.commit()
            except Exception as e:
                db.rollback()
                try:
                    db.execute(text(f'DELETE FROM "{tbl}"'))
                    db.commit()
                except Exception as e2:
                    db.rollback()
                    print(f"delete skip {tbl}: {e2}")
        # upsert merchants + policies
        for m in merchants:
            try:
                db.merge(Merchant(id=m["id"], name=m["name"], email=m["email"]))
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"merchant merge {m['id']}: {e}")
            # policy per merchant
            if not db.query(Policy).filter(Policy.merchant_id==m["id"]).first():
                db.add(Policy(merchant_id=m["id"], max_transaction=500000, max_discount=15, auto_approve=True))
                db.commit()
            if not db.query(MerchantObjective).filter(MerchantObjective.merchant_id==m["id"]).first():
                db.add(MerchantObjective(merchant_id=m["id"]))
                db.commit()
        db.commit()
        for c in customers:
            db.add(Customer(id=c["id"], merchant_id=c["merchant_id"], name=c["name"], email=c["email"], phone=c["phone"]))
        db.commit()
        # bulk products: use raw SQL for cost_price since model may lack column
        for p in products:
            try:
                db.execute(text("INSERT INTO products (id, merchant_id, name, category, price, stock, description, cost_price) VALUES (:id,:mid,:name,:cat,:price,:stock,:desc,:cp) ON CONFLICT (id) DO UPDATE SET merchant_id=EXCLUDED.merchant_id, name=EXCLUDED.name, category=EXCLUDED.category, price=EXCLUDED.price, stock=EXCLUDED.stock, cost_price=EXCLUDED.cost_price"), {"id":p["id"],"mid":p["merchant_id"],"name":p["name"],"cat":p["category"],"price":p["price"],"stock":p["stock"],"desc":p["description"],"cp":p["cost_price"]})
            except Exception as ex:
                print(f"product insert {p['id']}: {ex}")
                db.rollback()
        db.commit()
        # orders + payments + checkouts + carts synthesized from orders — bulk prep then one commit per batch
        carts=[]; checkouts=[]; payments=[]; orders_rows=[]
        for o in orders:
            cart_id=f"cart_{o['id'][4:]}"
            chk_id=f"chk_{o['id'][4:]}"
            pay_id=f"pay_{o['id'][4:]}"
            carts.append(Cart(id=cart_id, merchant_id=o["merchant_id"], customer_id=o["customer_id"], status="checked_out", total=o["total"]))
            checkouts.append(Checkout(id=chk_id, cart_id=cart_id, merchant_id=o["merchant_id"], customer_id=o["customer_id"], status="captured", total=o["total"], idempotency_key=f"idem_{chk_id}"))
            payments.append(Payment(id=pay_id, merchant_id=o["merchant_id"], amount=o["total"], status="captured", razorpay_order_id=f"order_{pay_id}", razorpay_payment_id=f"pay_{pay_id}", idempotency_key=f"idem_{pay_id}"))
            orders_rows.append(Order(id=o["id"], checkout_id=chk_id, merchant_id=o["merchant_id"], customer_id=o["customer_id"], status="paid", total=o["total"], payment_id=pay_id))
        try:
            db.add_all(carts); db.commit()
        except Exception as e: db.rollback(); print(f"bulk carts: {e}")
        try:
            db.add_all(checkouts); db.commit()
        except Exception as e: db.rollback(); print(f"bulk checkouts: {e}")
        try:
            db.add_all(payments); db.commit()
        except Exception as e: db.rollback(); print(f"bulk payments: {e}")
        try:
            db.add_all(orders_rows); db.commit()
        except Exception as e: db.rollback(); print(f"bulk orders: {e}")
        # order_items -> cart_items bulk
        cart_items=[CartItem(cart_id=f"cart_{it['order_id'][4:]}", product_id=it["product_id"], quantity=it["quantity"], unit_price=it["unit_price"], line_total=it["line_total"]) for it in items]
        try:
            db.add_all(cart_items); db.commit()
        except Exception as e:
            db.rollback(); print(f"bulk cart_items: {e}")
        print(f"DB seeded: {len(products)} products, {len(customers)} customers, {len(orders)} orders, {len(items)} items")
    finally:
        db.close()

if __name__=="__main__":
    main()

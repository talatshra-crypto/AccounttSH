# -*- coding: utf-8 -*-
"""
نظام ادارة المخازن والمحاسبة
يعمل بـ Python فقط - بدون اي مكتبات خارجية
"""
import sqlite3, json, os, sys, hashlib, time, webbrowser, threading, signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get('PORT', 8080))
# Railway: استخدام /tmp للبيانات المؤقتة أو مسار قابل للكتابة
_base = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_base, "inventory.db")

# ══════════════════════════════════════════════
#  قاعدة البيانات
# ══════════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def rows(cur): return [dict(r) for r in cur.fetchall()]
def row1(cur):
    r = cur.fetchone()
    return dict(r) if r else None

def init_db():
    c = get_db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT DEFAULT '',
        role TEXT DEFAULT 'admin'
    );
    CREATE TABLE IF NOT EXISTS suppliers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        contact TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        city TEXT DEFAULT '',
        balance REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        contact TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        city TEXT DEFAULT '',
        balance REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT UNIQUE NOT NULL,
        serial TEXT DEFAULT '',
        name TEXT NOT NULL,
        category TEXT DEFAULT '',
        unit TEXT DEFAULT 'قطعة',
        buy_price REAL DEFAULT 0,
        sell_price REAL DEFAULT 0,
        stock INTEGER DEFAULT 0,
        supplier_id INTEGER REFERENCES suppliers(id),
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS purchases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER REFERENCES suppliers(id),
        date TEXT NOT NULL,
        total REAL DEFAULT 0,
        status TEXT DEFAULT 'معلق',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS purchase_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER REFERENCES purchases(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        qty INTEGER DEFAULT 1,
        price REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS purchase_returns(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER REFERENCES purchases(id),
        supplier_id INTEGER REFERENCES suppliers(id),
        date TEXT NOT NULL,
        total REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS purchase_return_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        return_id INTEGER REFERENCES purchase_returns(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        qty INTEGER DEFAULT 1,
        price REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sales(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER REFERENCES customers(id),
        date TEXT NOT NULL,
        total REAL DEFAULT 0,
        status TEXT DEFAULT 'مدفوع',
        pay_method TEXT DEFAULT 'نقدي',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS sale_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER REFERENCES sales(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        qty INTEGER DEFAULT 1,
        price REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS purchase_returns(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER REFERENCES purchases(id),
        supplier_id INTEGER REFERENCES suppliers(id),
        date TEXT NOT NULL,
        total REAL DEFAULT 0,
        reason TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS purchase_return_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        return_id INTEGER REFERENCES purchase_returns(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        qty INTEGER DEFAULT 1,
        price REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ref_type TEXT NOT NULL,
        ref_id INTEGER NOT NULL,
        party_type TEXT NOT NULL,
        party_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        method TEXT DEFAULT 'نقدي',
        cheque_no TEXT DEFAULT '',
        cheque_date TEXT DEFAULT '',
        cheque_bank TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        date TEXT NOT NULL,
        created_at TEXT DEFAULT(datetime('now'))
    );
    """)
    if not row1(c.execute("SELECT id FROM users WHERE username='admin'")):
        c.execute("INSERT INTO users(username,password,full_name,role) VALUES(?,?,?,?)",
                  ("admin", hashlib.sha256("admin123".encode()).hexdigest(), "المدير العام", "admin"))
    c.commit()
    c.close()
    print("قاعدة البيانات جاهزة")

def check_auth(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "): return None
    token = auth[7:]
    c = get_db()
    u = row1(c.execute("SELECT * FROM users WHERE password=?", (token,)))
    c.close()
    return u

# ══════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════
def handle_api(method, path, body, req):
    parsed = urlparse(path)
    parts  = parsed.path.strip("/").split("/")
    qs     = parse_qs(parsed.query)

    # AUTH login
    if len(parts) >= 3 and parts[1] == "auth" and parts[2] == "login":
        u = body.get("username",""); p = body.get("password","")
        c = get_db()
        user = row1(c.execute("SELECT * FROM users WHERE username=?", (u,)))
        c.close()
        hp = hashlib.sha256(p.encode()).hexdigest()
        if not user or user["password"] != hp:
            return 401, {"detail": "اسم المستخدم او كلمة المرور غير صحيحة"}
        return 200, {"access_token": user["password"], "token_type": "bearer",
                     "user": {"id":user["id"],"username":user["username"],
                              "full_name":user["full_name"],"role":user["role"],"is_active":1}}

    if len(parts) >= 3 and parts[1] == "auth" and parts[2] == "me":
        u = check_auth(req)
        if not u: return 401, {"detail":"غير مصرح"}
        return 200, {"id":u["id"],"username":u["username"],
                     "full_name":u["full_name"],"role":u["role"],"is_active":1}

    u = check_auth(req)
    if not u: return 401, {"detail":"غير مصرح"}
    c = get_db()
    ep = parts[1] if len(parts) > 1 else ""

    # ── SUPPLIERS ──
    if ep == "suppliers":
        if method=="GET" and len(parts)==2:
            r = rows(c.execute("SELECT * FROM suppliers ORDER BY id DESC")); c.close(); return 200,r
        if method=="POST":
            cur = c.execute("INSERT INTO suppliers(name,contact,phone,email,city,balance,notes) VALUES(?,?,?,?,?,?,?)",
                (body.get("name",""),body.get("contact",""),body.get("phone",""),
                 body.get("email",""),body.get("city",""),body.get("balance",0),body.get("notes","")))
            c.commit()
            r = row1(c.execute("SELECT * FROM suppliers WHERE id=?",(cur.lastrowid,))); c.close(); return 201,r
        if method=="PUT" and len(parts)==3:
            c.execute("UPDATE suppliers SET name=?,contact=?,phone=?,email=?,city=?,balance=?,notes=? WHERE id=?",
                (body.get("name",""),body.get("contact",""),body.get("phone",""),
                 body.get("email",""),body.get("city",""),body.get("balance",0),body.get("notes",""),int(parts[2])))
            c.commit()
            r = row1(c.execute("SELECT * FROM suppliers WHERE id=?",(int(parts[2]),))); c.close(); return 200,r
        if method=="DELETE" and len(parts)==3:
            c.execute("DELETE FROM suppliers WHERE id=?",(int(parts[2]),)); c.commit(); c.close(); return 200,{"ok":True}

    # ── CUSTOMERS ──
    if ep == "customers":
        if method=="GET" and len(parts)==2:
            r = rows(c.execute("SELECT * FROM customers ORDER BY id DESC")); c.close(); return 200,r
        if method=="POST":
            cur = c.execute("INSERT INTO customers(name,contact,phone,email,city,balance,notes) VALUES(?,?,?,?,?,?,?)",
                (body.get("name",""),body.get("contact",""),body.get("phone",""),
                 body.get("email",""),body.get("city",""),body.get("balance",0),body.get("notes","")))
            c.commit()
            r = row1(c.execute("SELECT * FROM customers WHERE id=?",(cur.lastrowid,))); c.close(); return 201,r
        if method=="PUT" and len(parts)==3:
            c.execute("UPDATE customers SET name=?,contact=?,phone=?,email=?,city=?,balance=?,notes=? WHERE id=?",
                (body.get("name",""),body.get("contact",""),body.get("phone",""),
                 body.get("email",""),body.get("city",""),body.get("balance",0),body.get("notes",""),int(parts[2])))
            c.commit()
            r = row1(c.execute("SELECT * FROM customers WHERE id=?",(int(parts[2]),))); c.close(); return 200,r
        if method=="DELETE" and len(parts)==3:
            c.execute("DELETE FROM customers WHERE id=?",(int(parts[2]),)); c.commit(); c.close(); return 200,{"ok":True}

    # ── PRODUCTS ──
    if ep == "products":
        if method=="GET" and len(parts)==2:
            r = rows(c.execute("SELECT * FROM products ORDER BY id DESC")); c.close(); return 200,r
        if method=="GET" and len(parts)==4 and parts[2]=="barcode":
            code = parts[3]
            r = row1(c.execute("SELECT * FROM products WHERE barcode=? OR serial=?",(code,code))); c.close()
            if not r: return 404,{"detail":"غير موجود"}
            return 200,r
        if method=="GET" and len(parts)==4 and parts[2]=="search":
            q = parts[3]
            r = rows(c.execute("SELECT * FROM products WHERE name LIKE ? OR barcode LIKE ? OR serial LIKE ?",
                               (f"%{q}%",f"%{q}%",f"%{q}%"))); c.close(); return 200,r
        if method=="POST":
            try:
                cur = c.execute(
                    "INSERT INTO products(barcode,serial,name,category,unit,buy_price,sell_price,stock,supplier_id) VALUES(?,?,?,?,?,?,?,?,?)",
                    (body.get("barcode",""),body.get("serial",""),body.get("name",""),
                     body.get("category",""),body.get("unit","قطعة"),body.get("buy_price",0),
                     body.get("sell_price",0),body.get("stock",0),body.get("supplier_id")))
                c.commit()
                r = row1(c.execute("SELECT * FROM products WHERE id=?",(cur.lastrowid,))); c.close(); return 201,r
            except sqlite3.IntegrityError:
                c.close(); return 400,{"detail":"الباركود موجود مسبقاً"}
        if method=="PUT" and len(parts)==3:
            c.execute(
                "UPDATE products SET barcode=?,serial=?,name=?,category=?,unit=?,buy_price=?,sell_price=?,stock=?,supplier_id=? WHERE id=?",
                (body.get("barcode",""),body.get("serial",""),body.get("name",""),
                 body.get("category",""),body.get("unit","قطعة"),body.get("buy_price",0),
                 body.get("sell_price",0),body.get("stock",0),body.get("supplier_id"),int(parts[2])))
            c.commit()
            r = row1(c.execute("SELECT * FROM products WHERE id=?",(int(parts[2]),))); c.close(); return 200,r
        if method=="DELETE" and len(parts)==3:
            c.execute("DELETE FROM products WHERE id=?",(int(parts[2]),)); c.commit(); c.close(); return 200,{"ok":True}

    # ── PURCHASES ──
    if ep == "purchases":
        if method=="GET" and len(parts)==2:
            ps = rows(c.execute("SELECT * FROM purchases ORDER BY id DESC"))
            for p in ps:
                p["items"] = rows(c.execute(
                    "SELECT pi.*, pr.name as product_name, pr.barcode, pr.unit "
                    "FROM purchase_items pi LEFT JOIN products pr ON pr.id=pi.product_id "
                    "WHERE pi.purchase_id=?", (p["id"],)))
            c.close(); return 200,ps
        if method=="POST":
            # التحقق من وجود المورد
            if not body.get("supplier_id"):
                c.close(); return 400,{"detail":"يجب تحديد المورد"}
            items = body.get("items",[])
            if not items:
                c.close(); return 400,{"detail":"يجب إضافة صنف واحد على الأقل"}
            total = sum(i["qty"]*i["price"] for i in items)
            cur = c.execute(
                "INSERT INTO purchases(supplier_id,date,status,notes,total) VALUES(?,?,?,?,?)",
                (int(body.get("supplier_id")) if body.get("supplier_id") else None, body.get("date",""),body.get("status","معلق"),body.get("notes",""),total))
            pid = cur.lastrowid
            for i in items:
                c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,price) VALUES(?,?,?,?)",
                          (pid,i["product_id"],i["qty"],i["price"]))
                c.execute("UPDATE products SET stock=stock+? WHERE id=?",(i["qty"],i["product_id"]))
            c.commit()
            p = row1(c.execute("SELECT * FROM purchases WHERE id=?",(pid,)))
            p["items"] = rows(c.execute(
                "SELECT pi.*, pr.name as product_name, pr.barcode, pr.unit "
                "FROM purchase_items pi LEFT JOIN products pr ON pr.id=pi.product_id "
                "WHERE pi.purchase_id=?", (pid,)))
            c.close(); return 201,p

    # ── PURCHASE UPDATE ──
    if ep == "purchases" and method == "PUT" and len(parts) == 3:
        pid = int(parts[2])
        items = body.get("items", [])
        total = sum(i["qty"] * i["price"] for i in items)
        # تحديث بيانات الفاتورة
        c.execute("UPDATE purchases SET supplier_id=?,date=?,status=?,notes=?,total=? WHERE id=?",
                  (int(body.get("supplier_id")) if body.get("supplier_id") else None,
                   body.get("date",""), body.get("status","معلق"),
                   body.get("notes",""), total, pid))
        # حذف الأصناف القديمة وإعادة المخزون
        old_items = rows(c.execute("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,)))
        for oi in old_items:
            c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?", (oi["qty"], oi["product_id"]))
        c.execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))
        # إضافة الأصناف الجديدة
        for i in items:
            c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,price) VALUES(?,?,?,?)",
                      (pid, i["product_id"], i["qty"], i["price"]))
            c.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))
        c.commit()
        p = row1(c.execute("SELECT * FROM purchases WHERE id=?", (pid,)))
        p["items"] = rows(c.execute(
            "SELECT pi.*, pr.name as product_name, pr.barcode, pr.unit "
            "FROM purchase_items pi LEFT JOIN products pr ON pr.id=pi.product_id "
            "WHERE pi.purchase_id=?", (pid,)))
        c.close(); return 200, p

    # ── PURCHASE DELETE ──
    if ep == "purchases" and method == "DELETE" and len(parts) == 3:
        pid = int(parts[2])
        old_items = rows(c.execute("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,)))
        for oi in old_items:
            c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?", (oi["qty"], oi["product_id"]))
        c.execute("DELETE FROM purchases WHERE id=?", (pid,))
        c.commit(); c.close(); return 200, {"ok": True}

    # ── PURCHASE RETURNS ──
    if ep == "purchase_returns":
        if method == "GET" and len(parts) == 2:
            rs = rows(c.execute("SELECT * FROM purchase_returns ORDER BY id DESC"))
            for r in rs:
                r["items"] = rows(c.execute(
                    "SELECT pri.*, pr.name as product_name, pr.barcode, pr.unit "
                    "FROM purchase_return_items pri LEFT JOIN products pr ON pr.id=pri.product_id "
                    "WHERE pri.return_id=?", (r["id"],)))
            c.close(); return 200, rs
        if method == "POST":
            items = body.get("items", [])
            total = sum(i["qty"] * i["price"] for i in items)
            cur = c.execute(
                "INSERT INTO purchase_returns(purchase_id,supplier_id,date,total,notes) VALUES(?,?,?,?,?)",
                (body.get("purchase_id"), int(body.get("supplier_id")) if body.get("supplier_id") else None,
                 body.get("date",""), total, body.get("notes","")))
            rid = cur.lastrowid
            for i in items:
                c.execute("INSERT INTO purchase_return_items(return_id,product_id,qty,price) VALUES(?,?,?,?)",
                          (rid, i["product_id"], i["qty"], i["price"]))
                # إرجاع المخزون (طرح الكمية المرتجعة)
                c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?", (i["qty"], i["product_id"]))
            c.commit()
            r = row1(c.execute("SELECT * FROM purchase_returns WHERE id=?", (rid,)))
            r["items"] = rows(c.execute(
                "SELECT pri.*, pr.name as product_name, pr.barcode, pr.unit "
                "FROM purchase_return_items pri LEFT JOIN products pr ON pr.id=pri.product_id "
                "WHERE pri.return_id=?", (rid,)))
            c.close(); return 201, r

    # ── PURCHASE UPDATE ──
    if ep == "purchases" and method == "PUT" and len(parts) == 3:
        pid = int(parts[2])
        items = body.get("items", [])
        total = sum(i["qty"] * i["price"] for i in items)
        # استرداد الكميات القديمة وإعادتها للمخزون
        old_items = rows(c.execute("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,)))
        for oi in old_items:
            c.execute("UPDATE products SET stock=stock-? WHERE id=?", (oi["qty"], oi["product_id"]))
        # حذف الأصناف القديمة
        c.execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))
        # تحديث الفاتورة
        c.execute("UPDATE purchases SET supplier_id=?,date=?,status=?,notes=?,total=? WHERE id=?",
            (int(body.get("supplier_id")) if body.get("supplier_id") else None,
             body.get("date",""), body.get("status","معلق"), body.get("notes",""), total, pid))
        # إضافة الأصناف الجديدة
        for i in items:
            c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,price) VALUES(?,?,?,?)",
                      (pid, i["product_id"], i["qty"], i["price"]))
            c.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))
        c.commit()
        p = row1(c.execute("SELECT * FROM purchases WHERE id=?", (pid,)))
        p["items"] = rows(c.execute(
            "SELECT pi.*, pr.name as product_name, pr.barcode, pr.unit "
            "FROM purchase_items pi LEFT JOIN products pr ON pr.id=pi.product_id "
            "WHERE pi.purchase_id=?", (pid,)))
        c.close(); return 200, p

    # ── PURCHASE RETURNS ──
    if ep == "purchase_returns":
        if method == "GET" and len(parts) == 2:
            rs = rows(c.execute("SELECT * FROM purchase_returns ORDER BY id DESC"))
            for r in rs:
                r["items"] = rows(c.execute(
                    "SELECT pri.*, pr.name as product_name, pr.barcode, pr.unit "
                    "FROM purchase_return_items pri LEFT JOIN products pr ON pr.id=pri.product_id "
                    "WHERE pri.return_id=?", (r["id"],)))
            c.close(); return 200, rs
        if method == "POST":
            items = body.get("items", [])
            total = sum(i["qty"] * i["price"] for i in items)
            cur = c.execute(
                "INSERT INTO purchase_returns(purchase_id,supplier_id,date,total,reason,notes) VALUES(?,?,?,?,?,?)",
                (body.get("purchase_id"), 
                 int(body.get("supplier_id")) if body.get("supplier_id") else None,
                 body.get("date",""), total, body.get("reason",""), body.get("notes","")))
            rid = cur.lastrowid
            for i in items:
                c.execute("INSERT INTO purchase_return_items(return_id,product_id,qty,price) VALUES(?,?,?,?)",
                          (rid, i["product_id"], i["qty"], i["price"]))
                # إعادة الكمية للمخزون
                c.execute("UPDATE products SET stock=stock-? WHERE id=?", (i["qty"], i["product_id"]))
            c.commit()
            r = row1(c.execute("SELECT * FROM purchase_returns WHERE id=?", (rid,)))
            r["items"] = rows(c.execute(
                "SELECT pri.*, pr.name as product_name, pr.barcode, pr.unit "
                "FROM purchase_return_items pri LEFT JOIN products pr ON pr.id=pri.product_id "
                "WHERE pri.return_id=?", (rid,)))
            c.close(); return 201, r

    # ── SALES ──
    if ep == "sales":
        if method=="GET" and len(parts)==2:
            ss = rows(c.execute("SELECT * FROM sales ORDER BY id DESC"))
            for s in ss:
                s["items"] = rows(c.execute("SELECT * FROM sale_items WHERE sale_id=?",(s["id"],)))
            c.close(); return 200,ss
        if method=="POST":
            items = body.get("items",[])
            total = sum(i["qty"]*i["price"] for i in items)
            cur = c.execute(
                "INSERT INTO sales(customer_id,date,status,pay_method,notes,total) VALUES(?,?,?,?,?,?)",
                (body.get("customer_id"),body.get("date",""),body.get("status","مدفوع"),
                 body.get("pay_method","نقدي"),body.get("notes",""),total))
            sid = cur.lastrowid
            for i in items:
                c.execute("INSERT INTO sale_items(sale_id,product_id,qty,price) VALUES(?,?,?,?)",
                          (sid,i["product_id"],i["qty"],i["price"]))
                c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?",(i["qty"],i["product_id"]))
            c.commit()
            s = row1(c.execute("SELECT * FROM sales WHERE id=?",(sid,)))
            s["items"] = rows(c.execute("SELECT * FROM sale_items WHERE sale_id=?",(sid,)))
            c.close(); return 201,s

    # ── DASHBOARD ──
    if ep == "dashboard":
        ts = c.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
        tp = c.execute("SELECT COALESCE(SUM(total),0) FROM purchases").fetchone()[0]
        lw = c.execute("SELECT COUNT(*) FROM products WHERE stock<20").fetchone()[0]
        rs = rows(c.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 6"))
        lp = rows(c.execute("SELECT * FROM products WHERE stock<20 ORDER BY stock LIMIT 7"))
        c.close()
        return 200,{"total_sales":ts,"total_purchases":tp,"profit":ts-tp,
                    "low_stock_count":lw,"recent_sales":rs,"low_products":lp}

    # ── SUPPLIER REPORT ──
    if ep == "reports" and len(parts) >= 3 and parts[2] == "supplier":
        try:
            sup_id = int(qs.get("supplier_id",[0])[0])
        except:
            c.close(); return 400,{"detail":"رقم المورد غير صحيح"}
        date_from = qs.get("date_from",[""])[0]
        date_to   = qs.get("date_to",  [""])[0]

        # اذا لم يتم تحديد تواريخ نستخدم نطاق واسع
        if not date_from: date_from = "2000-01-01"
        if not date_to:   date_to   = "2099-12-31"

        sup = row1(c.execute("SELECT * FROM suppliers WHERE id=?",(sup_id,)))
        if not sup: c.close(); return 404,{"detail":"المورد غير موجود"}

        # جلب المشتريات - نحوّل supplier_id الى int للمقارنة الصحيحة
        ps = rows(c.execute(
            "SELECT * FROM purchases WHERE (CAST(supplier_id AS INTEGER)=? OR supplier_id=?) AND date>=? AND date<=? ORDER BY date",
            (sup_id, str(sup_id), date_from, date_to)))

        for p in ps:
            # جلب تفاصيل الأصناف لكل فاتورة
            items_raw = rows(c.execute(
                "SELECT pi.id, pi.purchase_id, pi.product_id, pi.qty, pi.price, "
                "pr.name as product_name, pr.barcode, pr.unit "
                "FROM purchase_items pi "
                "LEFT JOIN products pr ON pr.id = pi.product_id "
                "WHERE pi.purchase_id = ?", (p["id"],)))
            # إذا لم تجد بالـ LEFT JOIN جرب بدونها
            if not items_raw:
                items_raw = rows(c.execute(
                    "SELECT * FROM purchase_items WHERE purchase_id=?", (p["id"],)))
                for item in items_raw:
                    prod = row1(c.execute("SELECT * FROM products WHERE id=?", (item["product_id"],)))
                    if prod:
                        item["product_name"] = prod["name"]
                        item["barcode"]       = prod["barcode"]
                        item["unit"]          = prod["unit"]
                    else:
                        item["product_name"] = "منتج محذوف"
                        item["barcode"]       = ""
                        item["unit"]          = ""
            p["items"] = items_raw
        total = sum(p["total"] for p in ps)
        c.close()
        return 200,{"supplier":sup,"purchases":ps,"total":total,
                    "date_from":date_from,"date_to":date_to,"count":len(ps)}

    # ── PAYMENTS ──
    if ep == "payments":
        if method == "GET":
            ref_type = qs.get("ref_type",[""])[0]
            ref_id   = qs.get("ref_id",[""])[0]
            party_type = qs.get("party_type",[""])[0]
            party_id   = qs.get("party_id",[""])[0]
            if ref_type and ref_id:
                ps = rows(c.execute(
                    "SELECT * FROM payments WHERE ref_type=? AND ref_id=? ORDER BY date DESC",
                    (ref_type, int(ref_id))))
            elif party_type and party_id:
                ps = rows(c.execute(
                    "SELECT * FROM payments WHERE party_type=? AND party_id=? ORDER BY date DESC",
                    (party_type, int(party_id))))
            else:
                ps = rows(c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 100"))
            c.close(); return 200, ps

        if method == "POST":
            amount = float(body.get("amount", 0))
            if amount <= 0:
                c.close(); return 400, {"detail": "المبلغ يجب أن يكون أكبر من صفر"}
            cur = c.execute(
                "INSERT INTO payments(ref_type,ref_id,party_type,party_id,amount,method,cheque_no,cheque_date,cheque_bank,notes,date) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (body.get("ref_type",""), int(body.get("ref_id",0)),
                 body.get("party_type",""), int(body.get("party_id",0)),
                 amount, body.get("method","نقدي"),
                 body.get("cheque_no",""), body.get("cheque_date",""),
                 body.get("cheque_bank",""), body.get("notes",""),
                 body.get("date","")))
            c.commit()

            # تحديث حالة الفاتورة تلقائياً
            ref_type = body.get("ref_type","")
            ref_id   = int(body.get("ref_id",0))
            table    = "purchases" if ref_type=="purchase" else "sales"
            inv      = row1(c.execute(f"SELECT * FROM {table} WHERE id=?", (ref_id,)))
            if inv:
                paid_total = c.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM payments WHERE ref_type=? AND ref_id=?",
                    (ref_type, ref_id)).fetchone()[0]
                inv_total = abs(inv["total"])
                if paid_total >= inv_total:
                    new_status = "مدفوع"
                elif paid_total > 0:
                    new_status = "مدفوع جزئياً"
                else:
                    new_status = "معلق"
                c.execute(f"UPDATE {table} SET status=? WHERE id=?", (new_status, ref_id))
                c.commit()

            pay = row1(c.execute("SELECT * FROM payments WHERE id=?", (cur.lastrowid,)))
            c.close(); return 201, pay

        if method == "DELETE" and len(parts)==3:
            c.execute("DELETE FROM payments WHERE id=?", (int(parts[2]),))
            c.commit(); c.close(); return 200, {"ok": True}

    # ── PAYMENTS SUMMARY ──
    if ep == "payments_summary":
        party_type = qs.get("party_type",[""])[0]
        party_id   = int(qs.get("party_id",[0])[0])
        # جلب كل الفواتير
        if party_type == "supplier":
            invs = rows(c.execute(
                "SELECT * FROM purchases WHERE CAST(supplier_id AS INTEGER)=? AND status!='مردود'",
                (party_id,)))
            ref_type = "purchase"
        else:
            invs = rows(c.execute(
                "SELECT * FROM sales WHERE CAST(customer_id AS INTEGER)=?", (party_id,)))
            ref_type = "sale"
        # حساب المدفوع لكل فاتورة
        result = []
        total_inv = 0; total_paid = 0
        for inv in invs:
            paid = c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM payments WHERE ref_type=? AND ref_id=?",
                (ref_type, inv["id"])).fetchone()[0]
            remaining = abs(inv["total"]) - paid
            total_inv  += abs(inv["total"])
            total_paid += paid
            result.append({**inv, "paid": paid, "remaining": remaining})
        c.close()
        return 200, {"invoices": result, "total_invoices": total_inv,
                     "total_paid": total_paid, "total_remaining": total_inv - total_paid}

    # ── UPDATE PURCHASE ──
    if ep == "purchases" and method == "PUT" and len(parts) == 3:
        pid = int(parts[2])
        items = body.get("items", [])
        total = sum(i["qty"] * i["price"] for i in items)
        # إعادة المخزون القديم
        old_items = rows(c.execute("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,)))
        for oi in old_items:
            c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?", (oi["qty"], oi["product_id"]))
        # حذف الأصناف القديمة
        c.execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))
        # تحديث الفاتورة
        c.execute("UPDATE purchases SET supplier_id=?,date=?,status=?,notes=?,total=? WHERE id=?",
            (int(body.get("supplier_id")) if body.get("supplier_id") else None,
             body.get("date",""), body.get("status","معلق"), body.get("notes",""), total, pid))
        # إضافة الأصناف الجديدة
        for i in items:
            c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,price) VALUES(?,?,?,?)",
                      (pid, i["product_id"], i["qty"], i["price"]))
            c.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))
        c.commit()
        p = row1(c.execute("SELECT * FROM purchases WHERE id=?", (pid,)))
        p["items"] = rows(c.execute(
            "SELECT pi.*, pr.name as product_name, pr.barcode, pr.unit "
            "FROM purchase_items pi LEFT JOIN products pr ON pr.id=pi.product_id "
            "WHERE pi.purchase_id=?", (pid,)))
        c.close(); return 200, p

    # ── DELETE PURCHASE ──
    if ep == "purchases" and method == "DELETE" and len(parts) == 3:
        pid = int(parts[2])
        old_items = rows(c.execute("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,)))
        for oi in old_items:
            c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?", (oi["qty"], oi["product_id"]))
        c.execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))
        c.execute("DELETE FROM purchases WHERE id=?", (pid,))
        c.commit(); c.close(); return 200, {"ok": True}

    # ── PURCHASE RETURN (مردود) ──
    if ep == "purchase_return" and method == "POST":
        pid    = body.get("purchase_id")
        items  = body.get("items", [])   # الأصناف المردودة مع الكميات
        notes  = body.get("notes", "")
        date   = body.get("date", "")
        total  = sum(i["qty"] * i["price"] for i in items)
        # إنشاء فاتورة مردود (total سالب)
        sup_row = row1(c.execute("SELECT supplier_id FROM purchases WHERE id=?", (pid,)))
        sup_id  = sup_row["supplier_id"] if sup_row else None
        cur = c.execute(
            "INSERT INTO purchases(supplier_id,date,status,notes,total) VALUES(?,?,?,?,?)",
            (sup_id, date, "مردود", f"مردود من فاتورة #{pid} - {notes}", -total))
        ret_id = cur.lastrowid
        for i in items:
            c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,price) VALUES(?,?,?,?)",
                      (ret_id, i["product_id"], i["qty"], i["price"]))
            # إنقاص المخزون عند المردود
            c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?", (i["qty"], i["product_id"]))
        c.commit()
        ret = row1(c.execute("SELECT * FROM purchases WHERE id=?", (ret_id,)))
        ret["items"] = rows(c.execute("SELECT * FROM purchase_items WHERE purchase_id=?", (ret_id,)))
        c.close(); return 201, ret

    c.close()
    return 404,{"detail":"not found"}

# ══════════════════════════════════════════════
#  HTML
# ══════════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>نظام ادارة المخازن</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800;900&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Tajawal',sans-serif;background:#0f1117;color:#e2e8f0;direction:rtl}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:#1a1d27}::-webkit-scrollbar-thumb{background:#2d6a4f;border-radius:10px}
input,select,textarea{font-family:'Tajawal',sans-serif!important}
.btn{cursor:pointer;border:none;border-radius:8px;font-family:'Tajawal',sans-serif;font-size:14px;font-weight:600;transition:all .2s;display:inline-flex;align-items:center;gap:6px;padding:8px 16px}
.btn:disabled{opacity:.5;cursor:not-allowed}
.p{background:linear-gradient(135deg,#2d6a4f,#1b4332);color:#fff}.p:hover:not(:disabled){background:linear-gradient(135deg,#3d8b67,#2d6a4f);transform:translateY(-1px)}
.s{background:#1e2130;color:#94a3b8;border:1px solid #2d3349}.s:hover:not(:disabled){background:#252839;color:#52b788;border-color:#3d8b67}
.d{background:#3d1515;color:#f87171;border:1px solid #5c2323}.d:hover:not(:disabled){background:#5c2323}
.card{background:#161923;border:1px solid #1e2537;border-radius:12px}
.inp{background:#1a1d27;border:1px solid #2d3349;border-radius:8px;color:#e2e8f0;padding:10px 14px;font-size:14px;outline:none;width:100%;transition:border .2s}
.inp:focus{border-color:#2d6a4f;box-shadow:0 0 0 3px rgba(45,106,79,.15)}
.badge{padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;display:inline-block}
.g{background:rgba(45,106,79,.2);color:#52b788}.r{background:rgba(239,68,68,.15);color:#f87171}
.y{background:rgba(251,191,36,.15);color:#fbbf24}.b{background:rgba(59,130,246,.15);color:#60a5fa}
table{width:100%;border-collapse:collapse}
th{background:#1a1d27;color:#64748b;font-size:12px;font-weight:700;padding:10px 14px;text-align:right;border-bottom:1px solid #1e2537}
td{padding:10px 14px;border-bottom:1px solid #1a1d27;color:#cbd5e1;font-size:14px}
tr:hover td{background:#1a1d27}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
.modal{background:#161923;border:1px solid #2d3349;border-radius:16px;padding:24px;width:95%;max-width:660px;max-height:90vh;overflow-y:auto}
.stat{background:linear-gradient(135deg,#161923,#1a1d27);border:1px solid #1e2537;border-radius:12px;padding:18px}
.nav{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:10px;cursor:pointer;transition:all .2s;color:#64748b;font-size:14px;font-weight:500;border:1px solid transparent;white-space:nowrap}
.nav:hover{background:#1a1d27;color:#94a3b8}
.nav.on{background:linear-gradient(135deg,rgba(45,106,79,.25),rgba(27,67,50,.15));color:#52b788;border-color:rgba(45,106,79,.3)}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.lbl{display:block;color:#94a3b8;font-size:13px;font-weight:600;margin-bottom:5px}
.err{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:10px;color:#f87171;font-size:13px;margin-bottom:10px;text-align:center}
.ti{font-size:21px;font-weight:800;color:#f1f5f9;margin-bottom:3px}
.sub{font-size:13px;color:#64748b;margin-bottom:18px}
@keyframes spin{to{transform:rotate(360deg)}}
.spin{width:32px;height:32px;border:3px solid #1e2537;border-top-color:#2d6a4f;border-radius:50%;animation:spin .8s linear infinite;margin:50px auto}
.pos-sug-item:hover{background:#252839 !important}
.pos-sug-item.active{background:#252839}
</style>
</head>
<body>
<div id="app"></div>
<script>
const API='';
let TOKEN=localStorage.getItem('token'), USER=null;

async function api(method,path,body){
  const h={'Content-Type':'application/json'};
  if(TOKEN) h['Authorization']='Bearer '+TOKEN;
  const r=await fetch(API+path,{method,headers:h,body:body?JSON.stringify(body):undefined});
  if(!r.ok){
    if(r.status===401){TOKEN=null;localStorage.removeItem('token');render();}
    const e=await r.json().catch(()=>({}));
    throw new Error(e.detail||'خطأ');
  }
  return r.json();
}

let page='dashboard', sideOpen=true;
let products=[], suppliers=[], customers=[], purchases=[], sales=[], stats=null, loading=false, purchaseReturns=[];

async function loadAll(){
  loading=true; render();
  try{
    const [p,s,cu,pu,sl,st,pr] = await Promise.all([
      api('GET','/api/products'), api('GET','/api/suppliers'), api('GET','/api/customers'),
      api('GET','/api/purchases'), api('GET','/api/sales'), api('GET','/api/dashboard'),
      api('GET','/api/purchase_returns').catch(()=>[])
    ]);
    products=p; suppliers=s; customers=cu; purchases=pu; sales=sl; stats=st; purchaseReturns=pr;
  }catch(e){console.error(e);}
  loading=false; render();
}

function render(){
  const el=document.getElementById('app');
  if(!TOKEN){el.innerHTML=loginHTML(); bindLogin(); return;}
  el.innerHTML=appHTML(); bindApp();
}

// ── LOGIN ──────────────────────────────────────
function loginHTML(){
  return `<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;">
  <div style="width:360px;padding:36px;background:#161923;border-radius:18px;border:1px solid #1e2537;">
    <div style="text-align:center;margin-bottom:26px;">
      <div style="width:54px;height:54px;background:linear-gradient(135deg,#2d6a4f,#1b4332);border-radius:14px;display:flex;align-items:center;justify-content:center;margin:0 auto 12px;">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
      </div>
      <div style="font-size:21px;font-weight:900;color:#f1f5f9;">نظام ادارة المخازن</div>
      <div style="color:#52b788;font-size:13px;margin-top:3px;">ادارة متكاملة للمخازن والمحاسبة</div>
    </div>
    <div id="lerr"></div>
    <div style="margin-bottom:12px;"><label class="lbl">اسم المستخدم</label><input class="inp" id="lu" value="admin"/></div>
    <div style="margin-bottom:20px;"><label class="lbl">كلمة المرور</label><input class="inp" id="lp" type="password" value="admin123"/></div>
    <button class="btn p" id="lbtn" style="width:100%;justify-content:center;height:44px;font-size:15px;">دخول</button>
    <div style="text-align:center;margin-top:10px;font-size:12px;color:#475569;">افتراضي: admin / admin123</div>
  </div></div>`;
}

function bindLogin(){
  const go=async()=>{
    const u=document.getElementById('lu').value, p=document.getElementById('lp').value;
    const btn=document.getElementById('lbtn');
    btn.disabled=true; btn.textContent='جاري الدخول...';
    try{
      const r=await fetch('/api/auth/login',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:u,password:p})});
      const data=await r.json();
      if(!r.ok) throw new Error(data.detail||'خطأ');
      TOKEN=data.access_token; USER=data.user;
      localStorage.setItem('token',TOKEN);
      await loadAll();
    }catch(e){
      document.getElementById('lerr').innerHTML=`<div class="err">${e.message}</div>`;
      btn.disabled=false; btn.textContent='دخول';
    }
  };
  document.getElementById('lbtn').onclick=go;
  document.getElementById('lp').onkeydown=e=>e.key==='Enter'&&go();
  document.getElementById('lu').onkeydown=e=>e.key==='Enter'&&go();
}

// ── APP SHELL ──────────────────────────────────
const NAV=[
  {id:'dashboard',label:'لوحة التحكم',ic:'M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2zM9 22V12h6v10'},
  {id:'products',label:'المنتجات',ic:'M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z'},
  {id:'warehouse',label:'المخازن',ic:'M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2zM9 22V12h6v10'},
  {id:'purchases',label:'المشتريات',ic:'M1 3h15v13H1zM16 8h4l3 3v5h-7V8z'},
  {id:'pos',label:'نقطة البيع',ic:'M6 2H3L1 1M23 6H6l2.68 13.39a2 2 0 002 1.61h9.72a2 2 0 002-1.61L23 6z'},
  {id:'suppliers',label:'الموردون',ic:'M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 7a4 4 0 100 8 4 4 0 000-8z'},
  {id:'customers',label:'الزبائن',ic:'M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 7a4 4 0 100 8 4 4 0 000-8z'},
  {id:'accounting',label:'الحسابات',ic:'M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6'},
  {id:'reports',label:'التقارير',ic:'M18 20V10M12 20V4M6 20v-6'},
];

function ic(d,s=18){
  return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  ${d.split('M').filter(Boolean).map(p=>`<path d="M${p}"/>`).join('')}</svg>`;
}

function appHTML(){
  const w=sideOpen?224:58;
  return `<div style="display:flex;height:100vh;overflow:hidden;">
  <aside style="width:${w}px;min-width:${w}px;background:#0d1018;border-left:1px solid #1e2537;transition:all .25s;display:flex;flex-direction:column;overflow:hidden;">
    <div style="padding:16px 12px;border-bottom:1px solid #1e2537;display:flex;align-items:center;gap:10px;">
      <div style="width:32px;height:32px;min-width:32px;background:linear-gradient(135deg,#2d6a4f,#1b4332);border-radius:8px;display:flex;align-items:center;justify-content:center;">
        ${ic('M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2zM9 22V12h6v10',15)}
      </div>
      ${sideOpen?`<div><div style="font-size:13px;font-weight:800;color:#f1f5f9;">نظام المخازن</div><div style="font-size:11px;color:#52b788;">${USER?.full_name||'مرحبا'}</div></div>`:''}
    </div>
    <div style="flex:1;padding:8px 6px;overflow-y:auto;display:flex;flex-direction:column;gap:2px;">
      ${NAV.map(n=>`<div class="nav${page===n.id?' on':''}" data-page="${n.id}" title="${!sideOpen?n.label:''}">${ic(n.ic,17)}${sideOpen?`<span>${n.label}</span>`:''}</div>`).join('')}
    </div>
    <div style="padding:8px 6px;border-top:1px solid #1e2537;display:flex;flex-direction:column;gap:4px;">
      <div class="nav" id="tog">${ic('M3 12h18M3 6h18M3 18h18',17)}${sideOpen?'<span>طي القائمة</span>':''}</div>
      <div class="nav" style="color:#f87171;" id="lout">${ic('M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9',17)}${sideOpen?'<span>خروج</span>':''}</div>
    </div>
  </aside>
  <main style="flex:1;overflow-y:auto;padding:22px;">
    ${loading?'<div class="spin"></div>':pageHTML()}
  </main>
  </div>${modalHTML()}`;
}

function bindApp(){
  document.querySelectorAll('[data-page]').forEach(el=>{el.onclick=()=>{page=el.dataset.page;render();};});
  document.getElementById('tog').onclick=()=>{sideOpen=!sideOpen;render();};
  document.getElementById('lout').onclick=()=>{TOKEN=null;USER=null;localStorage.removeItem('token');render();};
  bindPage(); bindModal();
}

// ── PAGES ──────────────────────────────────────
function pageHTML(){
  if(page==='dashboard')  return dashHTML();
  if(page==='products')   return productsHTML();
  if(page==='warehouse')  return warehouseHTML();
  if(page==='purchases')  return purchasesHTML();
  if(page==='pos')        return posHTML();
  if(page==='suppliers')  return entityHTML('suppliers','الموردون','ادارة الموردين والارصدة');
  if(page==='customers')  return entityHTML('customers','الزبائن','ادارة الزبائن والارصدة');
  if(page==='accounting') return accountingHTML();
  if(page==='reports')    return reportsHTML();
  return '';
}

// DASHBOARD
function dashHTML(){
  if(!stats) return '<div class="spin"></div>';
  return `<div class="ti">لوحة التحكم</div><div class="sub">نظرة عامة على النظام</div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px;">
    ${[['المبيعات',stats.total_sales,'#52b788'],['المشتريات',stats.total_purchases,'#60a5fa'],
       ['الربح',stats.profit,stats.profit>=0?'#fbbf24':'#f87171'],['مخزون منخفض',stats.low_stock_count,'#f87171']
    ].map(([l,v,c])=>`<div class="stat"><div style="font-size:13px;color:#64748b;">${l}</div>
    <div style="font-size:19px;font-weight:800;color:${c};margin-top:7px;">${Number(v).toLocaleString()} ${l==='مخزون منخفض'?'منتج':'ر.س'}</div></div>`).join('')}
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    <div class="card" style="padding:16px;">
      <div style="font-weight:700;color:#f1f5f9;margin-bottom:12px;">اخر المبيعات</div>
      <table><thead><tr><th>التاريخ</th><th>الاجمالي</th><th>الحالة</th></tr></thead><tbody>
      ${(stats.recent_sales||[]).map(s=>`<tr><td>${s.date}</td>
      <td>${(s.total||0).toLocaleString()} ر.س</td>
      <td><span class="badge ${s.status==='مدفوع'?'g':'y'}">${s.status}</span></td></tr>`).join('')}
      </tbody></table>
    </div>
    <div class="card" style="padding:16px;">
      <div style="font-weight:700;color:#f1f5f9;margin-bottom:12px;">تنبيهات المخزون</div>
      ${(stats.low_products||[]).map(p=>`<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #1e2537;">
        <span style="font-size:13px;color:#cbd5e1;">${p.name}</span>
        <span class="badge ${p.stock===0?'r':'y'}">${p.stock===0?'نفد':p.stock}</span>
      </div>`).join('')||'<div style="color:#64748b;text-align:center;padding:20px;">المخزون كافٍ</div>'}
    </div>
  </div>`;
}

// PRODUCTS
function productsHTML(){
  return `<div class="ti">المنتجات</div><div class="sub">ادارة المنتجات بالباركود والسيريال</div>
  <div style="display:flex;gap:10px;margin-bottom:14px;">
    <input class="inp" id="pq" placeholder="بحث بالاسم او الباركود..." style="flex:1;"/>
    <button class="btn p" id="pa">+ اضافة منتج</button>
  </div>
  <div class="card"><table>
    <thead><tr><th>الباركود</th><th>السيريال</th><th>المنتج</th><th>الفئة</th><th>الشراء</th><th>البيع</th><th>المخزون</th><th></th></tr></thead>
    <tbody id="ptb"></tbody>
  </table></div>`;
}
function renderProds(q=''){
  const f=products.filter(p=>p.name?.includes(q)||p.barcode?.includes(q)||p.serial?.includes(q));
  const tb=document.getElementById('ptb'); if(!tb)return;
  tb.innerHTML=f.map(p=>`<tr>
    <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${p.barcode}</td>
    <td style="font-family:monospace;font-size:12px;color:#94a3b8;">${p.serial||''}</td>
    <td style="font-weight:600;color:#f1f5f9;">${p.name}</td>
    <td><span class="badge b">${p.category||''}</span></td>
    <td>${(p.buy_price||0).toLocaleString()} ر.س</td>
    <td style="color:#52b788;">${(p.sell_price||0).toLocaleString()} ر.س</td>
    <td><span class="badge ${p.stock<20?'r':'g'}">${p.stock} ${p.unit}</span></td>
    <td><div style="display:flex;gap:5px;">
      <button class="btn s" style="padding:4px 8px;" onclick="openEdit('products',${p.id})">✏️</button>
      <button class="btn d" style="padding:4px 8px;" onclick="delItem('products',${p.id})">🗑️</button>
    </div></td></tr>`).join('')||'<tr><td colspan="8" style="text-align:center;color:#475569;padding:28px;">لا توجد منتجات</td></tr>';
}

// WAREHOUSE
function warehouseHTML(){
  const cats=[...new Set(products.map(p=>p.category||'غير مصنف'))];
  const tv=products.reduce((s,p)=>s+p.stock*p.buy_price,0);
  return `<div class="ti">المخازن</div><div class="sub">تفاصيل المخزون الحالي</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:20px;">
    <div class="stat"><div style="font-size:13px;color:#64748b;">اجمالي المنتجات</div><div style="font-size:24px;font-weight:800;color:#52b788;margin-top:7px;">${products.length}</div></div>
    <div class="stat"><div style="font-size:13px;color:#64748b;">اجمالي الوحدات</div><div style="font-size:24px;font-weight:800;color:#60a5fa;margin-top:7px;">${products.reduce((s,p)=>s+p.stock,0).toLocaleString()}</div></div>
    <div class="stat"><div style="font-size:13px;color:#64748b;">قيمة المخزون</div><div style="font-size:18px;font-weight:800;color:#fbbf24;margin-top:7px;">${tv.toLocaleString()} ر.س</div></div>
  </div>
  ${cats.map(cat=>{const ps=products.filter(p=>(p.category||'غير مصنف')===cat); return `
  <div class="card" style="margin-bottom:12px;padding:14px;">
    <div style="font-weight:700;color:#52b788;margin-bottom:10px;">${cat}</div>
    <table><thead><tr><th>المنتج</th><th>الباركود</th><th>الكمية</th><th>التكلفة</th><th>القيمة</th><th>الحالة</th></tr></thead><tbody>
    ${ps.map(p=>`<tr>
      <td style="font-weight:600;">${p.name}</td>
      <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${p.barcode}</td>
      <td>${p.stock} ${p.unit}</td>
      <td>${(p.buy_price||0).toLocaleString()} ر.س</td>
      <td style="color:#52b788;font-weight:600;">${(p.stock*p.buy_price).toLocaleString()} ر.س</td>
      <td><span class="badge ${p.stock===0?'r':p.stock<20?'y':'g'}">${p.stock===0?'نفد':p.stock<20?'منخفض':'جيد'}</span></td>
    </tr>`).join('')}
    </tbody></table>
  </div>`;}).join('')}`;
}

// PURCHASES - مع التاريخ والتفاصيل والفلترة
function purchasesHTML(){
  const today=new Date().toISOString().slice(0,10);
  const first=today.slice(0,7)+'-01';
  return `<div class="ti">المشتريات</div><div class="sub">فواتير الشراء من الموردين</div>
  <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center;">
    <button class="btn p" id="pur-add">+ فاتورة شراء جديدة</button>
    <div style="display:flex;align-items:center;gap:8px;background:#161923;border:1px solid #1e2537;border-radius:8px;padding:6px 12px;">
      <span style="color:#64748b;font-size:13px;">من</span>
      <input class="inp" type="date" id="pff" value="${first}" style="width:138px;padding:4px 8px;font-size:13px;"/>
      <span style="color:#64748b;font-size:13px;">الى</span>
      <input class="inp" type="date" id="pft" value="${today}" style="width:138px;padding:4px 8px;font-size:13px;"/>
      <button class="btn s" id="pfb" style="padding:5px 12px;font-size:13px;">🔍 فلترة</button>
      <button class="btn s" id="pfc" style="padding:5px 12px;font-size:13px;">الكل</button>
    </div>
  </div>
  <div id="pur-sum" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px;">${purSum(purchases)}</div>
  <div class="card">
    <table>
      <thead><tr><th>#</th><th>📅 تاريخ الشراء</th><th>المورد</th><th>الاصناف</th><th>الاجمالي</th><th>الحالة</th><th>الإجراءات</th></tr></thead>
      <tbody id="pur-tb">${purRows(purchases)}</tbody>
    </table>
    <div id="pur-grand" style="text-align:left;padding:10px 16px;font-size:15px;font-weight:800;color:#52b788;border-top:1px solid #1e2537;">
      الاجمالي: ${purchases.reduce((s,p)=>s+p.total,0).toLocaleString()} ر.س
    </div>
  </div>`;
}

function purSum(list){
  const t=list.reduce((s,p)=>s+p.total,0);
  const paid=list.filter(p=>p.status==='مدفوع').reduce((s,p)=>s+p.total,0);
  const pend=list.filter(p=>p.status==='معلق').reduce((s,p)=>s+p.total,0);
  return `
  <div class="stat"><div style="font-size:12px;color:#64748b;">اجمالي الفترة</div><div style="font-size:17px;font-weight:800;color:#60a5fa;margin-top:6px;">${t.toLocaleString()} ر.س</div></div>
  <div class="stat"><div style="font-size:12px;color:#64748b;">مدفوع</div><div style="font-size:17px;font-weight:800;color:#52b788;margin-top:6px;">${paid.toLocaleString()} ر.س</div></div>
  <div class="stat"><div style="font-size:12px;color:#64748b;">معلق</div><div style="font-size:17px;font-weight:800;color:#fbbf24;margin-top:6px;">${pend.toLocaleString()} ر.س</div></div>`;
}

function purRows(list){
  if(!list.length) return '<tr><td colspan="7" style="text-align:center;color:#475569;padding:28px;">لا توجد مشتريات في هذه الفترة</td></tr>';
  return list.map(p=>`
  <tr>
    <td style="color:#64748b;font-weight:600;">#${p.id}</td>
    <td style="color:#f1f5f9;font-weight:700;font-size:14px;">📅 ${p.date}</td>
    <td style="color:#60a5fa;font-weight:600;">${suppliers.find(s=>s.id===p.supplier_id)?.name||'—'}</td>
    <td><span class="badge b">${p.items?.length||0} صنف</span></td>
    <td style="font-weight:800;color:#f1f5f9;">${(p.total||0).toLocaleString()} ر.س</td>
    <td><span class="badge ${p.status==='مدفوع'?'g':p.status==='معلق'?'y':'b'}">${p.status}</span></td>
    <td>
      <div style="display:flex;gap:4px;flex-wrap:wrap;">
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="togPur(${p.id})">📋 تفاصيل</button>
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="editPur(${p.id})">✏️ تعديل</button>
        ${p.status!=='مردود'?`<button class="btn p" style="padding:3px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay(${p.id},'purchase')">💳 دفعة</button>`:''}
        ${p.status!=='مردود'?`<button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="viewPayHist(${p.id},'purchase')">📊 الدفعات</button>`:''}
        ${p.status!=='مردود'?`<button class="btn s" style="padding:3px 8px;font-size:11px;color:#fbbf24;border-color:#5c4a23;" onclick="returnPur(${p.id})">↩️ مردود</button>`:''}
        <button class="btn d" style="padding:3px 8px;font-size:11px;" onclick="deletePur(${p.id})">🗑️</button>
      </div>
    </td>
  </tr>
  <tr id="pd-${p.id}" style="display:none;">
    <td colspan="7" style="padding:0;">
      <div style="background:#1a1d27;padding:14px 18px;border-bottom:2px solid #2d6a4f;">
        <div style="font-weight:700;color:#52b788;margin-bottom:10px;">
          تفاصيل الفاتورة #${p.id} &mdash; ${p.date} &mdash; ${suppliers.find(s=>s.id===p.supplier_id)?.name||'—'}
        </div>
        <table><thead><tr>
          <th style="background:#0f1117;font-size:12px;">الباركود</th>
          <th style="background:#0f1117;font-size:12px;">المنتج</th>
          <th style="background:#0f1117;font-size:12px;">الكمية</th>
          <th style="background:#0f1117;font-size:12px;">سعر الوحدة</th>
          <th style="background:#0f1117;font-size:12px;">الاجمالي</th>
        </tr></thead><tbody>
        ${(p.items||[]).map(item=>{
          const pr=products.find(x=>x.id===item.product_id);
          return `<tr>
            <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${item.barcode||pr?.barcode||'—'}</td>
            <td style="color:#f1f5f9;font-weight:600;">${item.product_name||pr?.name||'—'}</td>
            <td style="color:#94a3b8;">${item.qty} ${item.unit||pr?.unit||''}</td>
            <td>${(item.price||0).toLocaleString()} ر.س</td>
            <td style="color:#52b788;font-weight:700;">${(item.qty*item.price).toLocaleString()} ر.س</td>
          </tr>`;}).join('')||'<tr><td colspan="5" style="color:#64748b;text-align:center;padding:10px;">لا توجد اصناف</td></tr>'}
        </tbody></table>
        ${p.notes?`<div style="margin-top:8px;color:#64748b;font-size:13px;">📝 ${p.notes}</div>`:''}
      </div>
    </td>
  </tr>`).join('');
}
window.togPur=function(id){
  const r=document.getElementById('pd-'+id);
  if(r) r.style.display=r.style.display==='none'?'table-row':'none';
};

// تعديل فاتورة شراء
window.editPur=function(id){
  const p=purchases.find(x=>x.id===id);
  if(!p){alert('الفاتورة غير موجودة');return;}
  MS={type:'editpur', data:JSON.parse(JSON.stringify(p))};
  render();
};

// مردود مشتريات
window.returnPur=function(id){
  const p=purchases.find(x=>x.id===id);
  if(!p){alert('الفاتورة غير موجودة');return;}
  MS={type:'returnpur', data:JSON.parse(JSON.stringify(p))};
  render();
};

// POS
function posHTML(){
  return `<div style="display:grid;grid-template-columns:1fr 300px;gap:14px;height:calc(100vh - 44px);">
  <div style="display:flex;flex-direction:column;gap:10px;overflow:hidden;">
    <div><div class="ti">نقطة البيع</div><div class="sub">بيع بالباركود او السيريال او الاسم</div></div>
    <div style="display:flex;gap:8px;position:relative;">
      <div style="position:relative;flex:1;">
        <input class="inp" id="pi"
          placeholder="امسح الباركود أو اكتب اسم المنتج..."
          style="height:44px;font-size:15px;"
          autocomplete="off"/>
        <span style="position:absolute;right:12px;top:50%;transform:translateY(-50%);color:#52b788;pointer-events:none;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        </span>
        <div id="pos-suggest" style="display:none;position:absolute;top:100%;right:0;left:0;background:#1e2130;border:1px solid #2d6a4f;border-radius:0 0 10px 10px;max-height:240px;overflow-y:auto;z-index:200;box-shadow:0 8px 24px rgba(0,0,0,.4);"></div>
      </div>
      <button class="btn p" id="po" style="height:44px;padding:0 18px;">+ إضافة</button>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;overflow-y:auto;flex:1;">
      ${products.map(p=>`<div class="card" style="padding:11px;cursor:pointer;" onclick="addCart(${p.id})">
        <div style="font-size:12px;font-weight:700;color:#f1f5f9;margin-bottom:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${p.name}</div>
        <div style="font-size:11px;color:#64748b;margin-bottom:6px;">${p.barcode}</div>
        <div style="display:flex;justify-content:space-between;">
          <span style="color:#52b788;font-weight:700;font-size:13px;">${p.sell_price} ر.س</span>
          <span class="badge ${p.stock===0?'r':p.stock<5?'y':'g'}" style="font-size:11px;">${p.stock}</span>
        </div>
      </div>`).join('')}
    </div>
  </div>
  <div style="display:flex;flex-direction:column;gap:10px;">
    <div class="card" style="flex:1;padding:13px;overflow:hidden;display:flex;flex-direction:column;">
      <div style="font-weight:700;color:#52b788;margin-bottom:8px;">🛒 السلة <span id="cc" class="badge b" style="display:none;"></span></div>
      <div id="ci" style="flex:1;overflow-y:auto;color:#475569;text-align:center;padding:28px;font-size:13px;">السلة فارغة</div>
    </div>
    <div class="card" style="padding:13px;">
      <div style="margin-bottom:9px;"><label class="lbl">الزبون</label>
        <select class="inp" id="pc"><option value="">-- زبون عام --</option>
        ${customers.map(c=>`<option value="${c.id}">${c.name}</option>`).join('')}</select>
      </div>
      <div style="margin-bottom:12px;"><label class="lbl">طريقة الدفع</label>
        <select class="inp" id="pm">${['نقدي','بطاقة','تحويل','آجل'].map(m=>`<option>${m}</option>`).join('')}</select>
      </div>
      <div style="background:#1a1d27;border-radius:10px;padding:11px;margin-bottom:11px;text-align:center;">
        <div style="font-size:12px;color:#64748b;">الاجمالي</div>
        <div id="ct" style="font-size:26px;font-weight:900;color:#52b788;">0 <span style="font-size:13px;">ر.س</span></div>
      </div>
      <button class="btn p" id="pco" style="width:100%;justify-content:center;height:43px;font-size:15px;">اتمام البيع</button>
      <button class="btn s" id="pcl" style="width:100%;justify-content:center;margin-top:6px;">مسح السلة</button>
    </div>
  </div></div>`;
}

// ENTITY
function entityHTML(type,title,sub){
  return `<div class="ti">${title}</div><div class="sub">${sub}</div>
  <div style="display:flex;gap:10px;margin-bottom:14px;">
    <input class="inp" id="eq" placeholder="بحث..." style="flex:1;"/>
    <button class="btn p" id="ea" data-type="${type}">+ اضافة</button>
  </div>
  <div class="card"><table>
    <thead><tr><th>الاسم</th><th>الهاتف</th><th>المدينة</th><th>الرصيد</th><th></th></tr></thead>
    <tbody id="etb"></tbody>
  </table></div>`;
}
function renderEntity(type,q=''){
  const data=type==='suppliers'?suppliers:customers;
  const f=data.filter(x=>x.name?.includes(q)||x.phone?.includes(q));
  const tb=document.getElementById('etb'); if(!tb)return;
  tb.innerHTML=f.map(x=>`<tr>
    <td style="font-weight:700;color:#f1f5f9;">${x.name}</td>
    <td style="color:#60a5fa;">${x.phone||''}</td>
    <td><span class="badge b">${x.city||''}</span></td>
    <td><span class="badge ${x.balance!==0?'y':'g'}">${Math.abs(x.balance||0).toLocaleString()} ر.س</span></td>
    <td><div style="display:flex;gap:5px;">
      <button class="btn s" style="padding:4px 8px;" onclick="openEdit('${type}',${x.id})">✏️</button>
      <button class="btn d" style="padding:4px 8px;" onclick="delItem('${type}',${x.id})">🗑️</button>
    </div></td></tr>`).join('')||'<tr><td colspan="5" style="text-align:center;color:#475569;padding:28px;">لا توجد بيانات</td></tr>';
}

// ACCOUNTING
function accountingHTML(){
  const ts = sales.reduce((s,x)=>s+x.total, 0);
  const tp = purchases.reduce((s,x)=>s+x.total, 0);

  // حساب إجمالي مشتريات كل مورد من الفواتير الفعلية
  const supStats = suppliers.map(s=>{
    const purList = purchases.filter(p=> parseInt(p.supplier_id)===s.id);
    const total   = purList.reduce((t,p)=>t+p.total, 0);
    const paid    = purList.filter(p=>p.status==='مدفوع').reduce((t,p)=>t+p.total, 0);
    const pending = purList.filter(p=>p.status!=='مدفوع').reduce((t,p)=>t+p.total, 0);
    return {...s, purTotal:total, purPaid:paid, purPending:pending, purCount:purList.length};
  });

  // حساب إجمالي مبيعات كل زبون من الفواتير الفعلية
  const custStats = customers.map(c=>{
    const saleList = sales.filter(s=> parseInt(s.customer_id)===c.id);
    const total    = saleList.reduce((t,s)=>t+s.total, 0);
    const paid     = saleList.filter(s=>s.status==='مدفوع').reduce((t,s)=>t+s.total, 0);
    const pending  = saleList.filter(s=>s.status!=='مدفوع').reduce((t,s)=>t+s.total, 0);
    return {...c, saleTotal:total, salePaid:paid, salePending:pending, saleCount:saleList.length};
  });

  const totalPending = supStats.reduce((s,x)=>s+x.purPending, 0);
  const totalReceive = custStats.reduce((s,x)=>s+x.salePending, 0);

  return `<div class="ti">الحسابات</div><div class="sub">المتابعة المالية الشاملة</div>
  <div style="display:flex;gap:8px;margin-bottom:16px;">
    <button class="btn p" id="acc-tab-sum" onclick="accTab('sum')">ملخص</button>
    <button class="btn s" id="acc-tab-sup" onclick="accTab('sup')">كشف موردين</button>
    <button class="btn s" id="acc-tab-cust" onclick="accTab('cust')">كشف زبائن</button>
    <button class="btn s" id="acc-tab-pays" onclick="accTab('pays')">سجل الدفعات</button>
  </div>
  <div id="acc-content">

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px;">
    <div class="stat">
      <div style="font-size:12px;color:#64748b;">إجمالي المبيعات</div>
      <div style="font-size:18px;font-weight:800;color:#52b788;margin-top:6px;">${ts.toLocaleString()} ر.س</div>
    </div>
    <div class="stat">
      <div style="font-size:12px;color:#64748b;">إجمالي المشتريات</div>
      <div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:6px;">${tp.toLocaleString()} ر.س</div>
    </div>
    <div class="stat">
      <div style="font-size:12px;color:#64748b;">مستحق للموردين</div>
      <div style="font-size:18px;font-weight:800;color:#f87171;margin-top:6px;">${totalPending.toLocaleString()} ر.س</div>
    </div>
    <div class="stat">
      <div style="font-size:12px;color:#64748b;">مستحق من الزبائن</div>
      <div style="font-size:18px;font-weight:800;color:#fbbf24;margin-top:6px;">${totalReceive.toLocaleString()} ر.س</div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">

    <div class="card" style="padding:0;overflow:hidden;">
      <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;">
        <div style="font-weight:700;color:#f1f5f9;">حسابات الموردين</div>
        <div style="font-size:12px;color:#64748b;margin-top:2px;">إجمالي المشتريات لكل مورد</div>
      </div>
      ${supStats.length ? supStats.map(s=>`
      <div style="padding:12px 16px;border-bottom:1px solid #1e2537;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span style="font-weight:700;color:#f1f5f9;font-size:14px;">${s.name}</span>
          <span style="font-weight:800;color:#60a5fa;font-size:14px;">${s.purTotal.toLocaleString()} ر.س</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <span class="badge b">${s.purCount} فاتورة</span>
          ${s.purPaid>0?`<span class="badge g">مدفوع: ${s.purPaid.toLocaleString()} ر.س</span>`:''}
          ${s.purPending>0?`<span class="badge r">معلق: ${s.purPending.toLocaleString()} ر.س</span>`:''}
          ${s.purTotal===0?`<span class="badge y">لا توجد مشتريات</span>`:''}
        </div>
      </div>`).join('') : '<div style="color:#64748b;text-align:center;padding:20px;">لا يوجد موردون</div>'}
    </div>

    <div class="card" style="padding:0;overflow:hidden;">
      <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;">
        <div style="font-weight:700;color:#f1f5f9;">حسابات الزبائن</div>
        <div style="font-size:12px;color:#64748b;margin-top:2px;">إجمالي المبيعات لكل زبون</div>
      </div>
      ${custStats.length ? custStats.map(c=>`
      <div style="padding:12px 16px;border-bottom:1px solid #1e2537;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <span style="font-weight:700;color:#f1f5f9;font-size:14px;">${c.name}</span>
          <span style="font-weight:800;color:#52b788;font-size:14px;">${c.saleTotal.toLocaleString()} ر.س</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <span class="badge b">${c.saleCount} فاتورة</span>
          ${c.salePaid>0?`<span class="badge g">مدفوع: ${c.salePaid.toLocaleString()} ر.س</span>`:''}
          ${c.salePending>0?`<span class="badge y">معلق: ${c.salePending.toLocaleString()} ر.س</span>`:''}
          ${c.saleTotal===0?`<span class="badge y">لا توجد مبيعات</span>`:''}
        </div>
      </div>`).join('') : '<div style="color:#64748b;text-align:center;padding:20px;">لا يوجد زبائن</div>'}
    </div>

  </div></div>
  </div>`;
}

window.accTab = async function(tab){
  document.querySelectorAll('[id^="acc-tab-"]').forEach(b=>{
    b.className = b.id==='acc-tab-'+tab ? 'btn p' : 'btn s';
  });
  const el = document.getElementById('acc-content');
  if(!el) return;

  if(tab==='sum'){
    el.innerHTML = document.getElementById('acc-sum-content')?.innerHTML || '';
    return;
  }

  if(tab==='pays'){
    el.innerHTML='<div class="spin"></div>';
    try{
      const pays = await api('GET','/api/payments');
      el.innerHTML = pays.length
        ? '<div class="card"><table>'
          + '<thead><tr><th>التاريخ</th><th>النوع</th><th>المبلغ</th><th>الطريقة</th><th>رقم الشيك</th><th>البنك</th><th>ملاحظات</th></tr></thead><tbody>'
          + pays.map(p=>{
              const inv = p.ref_type==='purchase'
                ? purchases.find(x=>x.id===p.ref_id)
                : sales.find(x=>x.id===p.ref_id);
              const party = p.party_type==='supplier'
                ? suppliers.find(s=>s.id===parseInt(p.party_id))?.name||'—'
                : customers.find(c=>c.id===parseInt(p.party_id))?.name||'—';
              return '<tr>'
                + '<td style="font-weight:600;">'+p.date+'</td>'
                + '<td><div style="font-size:12px;"><span class="badge '+(p.ref_type==='purchase'?'b':'g')+'">'+(p.ref_type==='purchase'?'شراء':'بيع')+'</span><div style="color:#94a3b8;font-size:11px;margin-top:2px;">'+party+'</div></div></td>'
                + '<td style="font-weight:800;color:#52b788;">'+p.amount.toLocaleString()+' ر.س</td>'
                + '<td><span class="badge '+(p.method==='نقدي'?'g':p.method==='شيك'?'b':'y')+'">'+p.method+'</span></td>'
                + '<td style="font-family:monospace;color:#60a5fa;">'+(p.cheque_no||'—')+'</td>'
                + '<td style="font-size:12px;color:#94a3b8;">'+(p.cheque_bank||'—')+'</td>'
                + '<td style="font-size:12px;color:#64748b;">'+(p.notes||'')+'</td>'
              + '</tr>';
            }).join('')
          + '</tbody></table></div>'
          + '<div style="text-align:left;padding:12px 16px;font-size:15px;font-weight:800;color:#52b788;background:#161923;border-radius:8px;margin-top:8px;">'
          + 'إجمالي الدفعات: '+pays.reduce((s,p)=>s+p.amount,0).toLocaleString()+' ر.س</div>'
        : '<div style="text-align:center;color:#64748b;padding:30px;">لا توجد دفعات مسجلة</div>';
    }catch(e){ el.innerHTML='<div class="err">خطأ: '+e.message+'</div>'; }
    return;
  }

  if(tab==='sup'){
    const rows = supStats.map(s=>`
    <div class="card" style="margin-bottom:10px;padding:14px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <div style="font-weight:700;color:#f1f5f9;font-size:15px;">${s.name}</div>
        <button class="btn p" style="padding:5px 12px;font-size:12px;background:linear-gradient(135deg,#1e40af,#1e3a8a);"
          onclick="openSupPaySummary(${s.id})">💳 كشف الحساب</button>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <span class="badge b">${s.purCount} فاتورة</span>
        <span style="color:#60a5fa;font-weight:700;">${s.purTotal.toLocaleString()} ر.س إجمالي</span>
        ${s.purPaid>0?`<span class="badge g">مدفوع: ${s.purPaid.toLocaleString()} ر.س</span>`:''}
        ${s.purPending>0?`<span class="badge r">معلق: ${s.purPending.toLocaleString()} ر.س</span>`:''}
      </div>
    </div>`).join('');
    el.innerHTML = rows || '<div style="color:#64748b;text-align:center;padding:20px;">لا يوجد موردون</div>';
    return;
  }

  if(tab==='cust'){
    const rows = custStats.map(c=>`
    <div class="card" style="margin-bottom:10px;padding:14px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <div style="font-weight:700;color:#f1f5f9;font-size:15px;">${c.name}</div>
        <button class="btn p" style="padding:5px 12px;font-size:12px;"
          onclick="openCustPaySummary(${c.id})">📊 كشف الحساب</button>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <span class="badge b">${c.saleCount} فاتورة</span>
        <span style="color:#52b788;font-weight:700;">${c.saleTotal.toLocaleString()} ر.س إجمالي</span>
        ${c.salePaid>0?`<span class="badge g">مدفوع: ${c.salePaid.toLocaleString()} ر.س</span>`:''}
        ${c.salePending>0?`<span class="badge y">معلق: ${c.salePending.toLocaleString()} ر.س</span>`:''}
      </div>
    </div>`).join('');
    el.innerHTML = rows || '<div style="color:#64748b;text-align:center;padding:20px;">لا يوجد زبائن</div>';
    return;
  }
};

window.openSupPaySummary = async function(sup_id){
  const sup = suppliers.find(s=>s.id===sup_id);
  if(!sup) return;
  const el = document.getElementById('acc-content');
  if(el) el.innerHTML='<div class="spin"></div>';
  try{
    const data = await api('GET','/api/payments_summary?party_type=supplier&party_id='+sup_id);
    if(el) el.innerHTML = paySummaryHTML(data, sup.name, 'supplier');
  }catch(e){ if(el) el.innerHTML='<div class="err">'+e.message+'</div>'; }
};

window.openCustPaySummary = async function(cust_id){
  const cust = customers.find(c=>c.id===cust_id);
  if(!cust) return;
  const el = document.getElementById('acc-content');
  if(el) el.innerHTML='<div class="spin"></div>';
  try{
    const data = await api('GET','/api/payments_summary?party_type=customer&party_id='+cust_id);
    if(el) el.innerHTML = paySummaryHTML(data, cust.name, 'customer');
  }catch(e){ if(el) el.innerHTML='<div class="err">'+e.message+'</div>'; }
};

function paySummaryHTML(data, name, party_type){
  const {invoices, total_invoices, total_paid, total_remaining} = data;
  const ref_type = party_type==='supplier' ? 'purchase' : 'sale';
  return '<div>'
  + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
    + '<div style="font-size:16px;font-weight:800;color:#f1f5f9;">كشف حساب: '+name+'</div>'
    + '<button class="btn s" style="font-size:12px;" onclick="accTab('sum')">← رجوع</button>'
  + '</div>'
  + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">'
    + '<div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">إجمالي الفواتير</div><div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:6px;">'+total_invoices.toLocaleString()+' ر.س</div></div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">إجمالي المدفوع</div><div style="font-size:18px;font-weight:800;color:#52b788;margin-top:6px;">'+total_paid.toLocaleString()+' ر.س</div></div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">المتبقي</div><div style="font-size:18px;font-weight:800;color:'+(total_remaining>0?'#f87171':'#52b788')+';margin-top:6px;">'+total_remaining.toLocaleString()+' ر.س</div></div>'
  + '</div>'
  + '<div class="card"><table>'
    + '<thead><tr><th>#</th><th>التاريخ</th><th>الإجمالي</th><th>المدفوع</th><th>المتبقي</th><th>الحالة</th><th></th></tr></thead>'
    + '<tbody>'
    + invoices.map(inv=>'<tr>'
        + '<td style="color:#64748b;">#'+inv.id+'</td>'
        + '<td>'+inv.date+'</td>'
        + '<td style="font-weight:700;">'+Math.abs(inv.total||0).toLocaleString()+' ر.س</td>'
        + '<td style="color:#52b788;font-weight:600;">'+(inv.paid||0).toLocaleString()+' ر.س</td>'
        + '<td style="color:'+(inv.remaining>0?'#f87171':'#52b788')+';font-weight:700;">'+(inv.remaining||0).toLocaleString()+' ر.س</td>'
        + '<td><span class="badge '+(inv.status==='مدفوع'?'g':inv.status==='معلق'?'r':'b')+'">'+inv.status+'</span></td>'
        + '<td><div style="display:flex;gap:4px;">'
          + (inv.remaining>0?'<button class="btn p" style="padding:3px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay('+inv.id+',''+ref_type+'')">💳 دفعة</button>':'')
          + '<button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="viewPayHist('+inv.id+',''+ref_type+'')">📊</button>'
        + '</div></td>'
      + '</tr>').join('')
    + '</tbody></table></div>'
  + '</div>';
}

// REPORTS
function reportsHTML(){
  const ts=sales.reduce((s,x)=>s+x.total,0), tp=purchases.reduce((s,x)=>s+x.total,0);
  return `<div class="ti">التقارير</div><div class="sub">تقارير شاملة لجميع العمليات</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px;">
    <div class="stat"><div style="font-size:13px;color:#64748b;">المبيعات</div><div style="font-size:19px;font-weight:800;color:#52b788;margin-top:7px;">${ts.toLocaleString()} ر.س</div></div>
    <div class="stat"><div style="font-size:13px;color:#64748b;">المشتريات</div><div style="font-size:19px;font-weight:800;color:#60a5fa;margin-top:7px;">${tp.toLocaleString()} ر.س</div></div>
    <div class="stat"><div style="font-size:13px;color:#64748b;">الربح الصافي</div><div style="font-size:19px;font-weight:800;color:#fbbf24;margin-top:7px;">${(ts-tp).toLocaleString()} ر.س</div></div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;" id="rep-tabs">
    ${[['sales','المبيعات'],['purchases','المشتريات'],['sup-detail','كشف مورد 🔍'],['customers','الزبائن'],['inventory','المخزون']
    ].map(([id,label],i)=>`<button class="btn ${i===0?'p':'s'}" data-rep="${id}">${label}</button>`).join('')}
  </div>
  <div id="rc">${repContent('sales')}</div>`;
}

function repContent(type){
  if(type==='sales') return `<div class="card"><table>
    <thead><tr><th>#</th><th>التاريخ</th><th>الزبون</th><th>الاجمالي</th><th>الحالة</th><th>الدفع</th><th>إجراءات</th></tr></thead>
    <tbody>${sales.map(s=>`<tr>
    <td style="color:#64748b;">#${s.id}</td>
    <td style="font-weight:600;">${s.date}</td>
    <td style="color:#52b788;font-weight:600;">${customers.find(c=>c.id===s.customer_id)?.name||'زبون عام'}</td>
    <td style="font-weight:700;">${(s.total||0).toLocaleString()} ر.س</td>
    <td><span class="badge ${s.status==='مدفوع'?'g':'y'}">${s.status}</span></td>
    <td>${s.pay_method}</td>
    <td><div style="display:flex;gap:4px;">
      ${s.status!=='مدفوع'?`<button class="btn p" style="padding:3px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay(${s.id},'sale')">💳 دفعة</button>`:''}
      <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="viewPayHist(${s.id},'sale')">📊 الدفعات</button>
    </div></td>
    </tr>`).join('')||'<tr><td colspan="7" style="text-align:center;color:#475569;padding:20px;">لا توجد مبيعات</td></tr>'}
    </tbody></table></div>`;

  if(type==='purchases') return `<div class="card"><table>
    <thead><tr><th>#</th><th>التاريخ</th><th>المورد</th><th>الاصناف</th><th>الاجمالي</th><th>الحالة</th></tr></thead>
    <tbody>${purchases.map(p=>`<tr><td style="color:#64748b;">#${p.id}</td>
    <td style="font-weight:700;color:#f1f5f9;">📅 ${p.date}</td>
    <td style="color:#60a5fa;font-weight:600;">${suppliers.find(s=>s.id===p.supplier_id)?.name||'—'}</td>
    <td><span class="badge b">${p.items?.length||0} صنف</span></td>
    <td style="font-weight:700;">${(p.total||0).toLocaleString()} ر.س</td>
    <td><span class="badge ${p.status==='مدفوع'?'g':'y'}">${p.status}</span></td></tr>`).join('')}
    </tbody></table></div>`;

  if(type==='sup-detail'){
    const today=new Date().toISOString().slice(0,10);
    const first=today.slice(0,7)+'-01';
    const supOpts = suppliers.map(s=>'<option value="'+s.id+'">'+s.name+'</option>').join('');
    // نُرجع HTML مع استدعاء مباشر للدالة - بدون id binding
    return '<div class="card" style="padding:20px;margin-bottom:14px;">'
      + '<div style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:16px;">🔍 كشف حساب مورد تفصيلي</div>'
      + '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px;">'
        + '<div><label class="lbl">اختر المورد</label>'
          + '<select class="inp" id="srid" onchange=""><option value="">-- اختر المورد --</option>'+supOpts+'</select>'
        + '</div>'
        + '<div><label class="lbl">من تاريخ</label>'
          + '<input class="inp" type="date" id="srf" value="'+first+'"/>'
        + '</div>'
        + '<div><label class="lbl">الى تاريخ</label>'
          + '<input class="inp" type="date" id="srt" value="'+today+'"/>'
        + '</div>'
      + '</div>'
      + '<button class="btn p" id="srb" style="height:44px;width:100%;justify-content:center;font-size:15px;" '
      + 'onclick="doSupReport()">🔍 عرض كشف المورد</button>'
      + '<div id="srr" style="margin-top:16px;"></div>'
    + '</div>';
  }

  if(type==='customers') return `<div class="card"><table>
    <thead><tr><th>الزبون</th><th>المدينة</th><th>الطلبات</th><th>الاجمالي</th><th>الرصيد</th></tr></thead>
    <tbody>${customers.map(c=>{const o=sales.filter(s=>s.customer_id===c.id);
    return `<tr><td style="font-weight:700;color:#f1f5f9;">${c.name}</td><td>${c.city||''}</td>
    <td><span class="badge b">${o.length}</span></td>
    <td style="color:#52b788;font-weight:600;">${o.reduce((t,s)=>t+s.total,0).toLocaleString()} ر.س</td>
    <td><span class="badge ${c.balance>0?'y':'g'}">${Math.abs(c.balance||0).toLocaleString()} ر.س</span></td></tr>`;}).join('')}
    </tbody></table></div>`;

  if(type==='inventory') return `<div class="card"><table>
    <thead><tr><th>المنتج</th><th>الفئة</th><th>المخزون</th><th>القيمة</th><th>الحالة</th></tr></thead>
    <tbody>${products.map(p=>`<tr>
    <td style="font-weight:700;color:#f1f5f9;">${p.name}</td>
    <td><span class="badge b">${p.category||''}</span></td>
    <td><span class="badge ${p.stock<20?'r':'g'}">${p.stock}</span></td>
    <td style="color:#52b788;font-weight:600;">${(p.stock*p.buy_price).toLocaleString()} ر.س</td>
    <td><span class="badge ${p.stock===0?'r':p.stock<20?'y':'g'}">${p.stock===0?'نفد':p.stock<20?'منخفض':'متوفر'}</span></td></tr>`).join('')}
    </tbody></table></div>`;
  return '';
}

// كشف المورد
// دالة كشف المورد - تُستدعى مباشرة من onclick في الزر
window.doSupReport = async function(){
  const supSel = document.getElementById('srid');
  const fromEl = document.getElementById('srf');
  const toEl   = document.getElementById('srt');
  const resEl  = document.getElementById('srr');
  
  if(!supSel || !supSel.value){
    alert('يرجى اختيار المورد أولاً');
    if(supSel) supSel.focus();
    return;
  }
  
  const supId   = supSel.value;
  const dateFrom = fromEl ? fromEl.value : '2000-01-01';
  const dateTo   = toEl   ? toEl.value   : '2099-12-31';
  
  // إظهار مؤشر التحميل
  if(resEl){
    resEl.innerHTML = '<div style="text-align:center;padding:30px;">'
      + '<div class="spin"></div>'
      + '<div style="color:#64748b;margin-top:10px;font-size:13px;">جاري تحميل الكشف...</div>'
      + '</div>';
  }
  
  // تعطيل الزر مؤقتاً
  const btn = document.getElementById('srb');
  if(btn){ btn.disabled=true; btn.textContent='جاري التحميل...'; }
  
  try{
    const url = '/api/reports/supplier?supplier_id='+supId+'&date_from='+dateFrom+'&date_to='+dateTo;
    const data = await api('GET', url);
    
    if(resEl) resEl.innerHTML = supRepHTML(data);
    
    // تمرير للنتائج
    setTimeout(()=>{
      if(resEl) resEl.scrollIntoView({behavior:'smooth', block:'start'});
    }, 150);
  } catch(err){
    console.error('خطأ في كشف المورد:', err);
    if(resEl) resEl.innerHTML = '<div class="err">حدث خطأ: ' + err.message + '</div>';
  } finally {
    if(btn){ btn.disabled=false; btn.textContent='🔍 عرض كشف المورد'; }
  }
};
// alias قديم للتوافق
window.loadSupRep = window.doSupReport;

function supRepHTML(d){
  const {supplier:s,purchases:ps,total,count,date_from,date_to}=d;
  return `<div id="spa">
  <div class="card" style="padding:18px;margin-bottom:12px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
      <div><div style="font-size:17px;font-weight:900;color:#f1f5f9;">كشف حساب مورد</div>
        <div style="font-size:13px;color:#64748b;margin-top:3px;">الفترة: ${date_from} الى ${date_to}</div></div>
      <div style="text-align:left;"><div style="font-size:15px;font-weight:800;color:#52b788;">${s.name}</div>
        <div style="font-size:12px;color:#64748b;">${s.phone||''} ${s.city?'— '+s.city:''}</div></div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
      <div class="stat"><div style="font-size:12px;color:#64748b;">عدد الفواتير</div><div style="font-size:19px;font-weight:800;color:#60a5fa;margin-top:4px;">${count}</div></div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">اجمالي المشتريات</div><div style="font-size:19px;font-weight:800;color:#52b788;margin-top:4px;">${total.toLocaleString()} ر.س</div></div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">رصيد المورد</div><div style="font-size:19px;font-weight:800;color:#fbbf24;margin-top:4px;">${Math.abs(s.balance||0).toLocaleString()} ر.س</div></div>
    </div>
  </div>
  ${ps.map(p=>`
  <div class="card" style="margin-bottom:10px;overflow:hidden;">
    <div style="background:#1a1d27;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">
      <div style="display:flex;align-items:center;gap:12px;">
        <span style="color:#64748b;font-size:13px;">#${p.id}</span>
        <span style="font-weight:800;color:#f1f5f9;">📅 ${p.date}</span>
        <span class="badge ${p.status==='مدفوع'?'g':p.status==='معلق'?'y':'b'}">${p.status}</span>
      </div>
      <span style="font-weight:900;color:#52b788;font-size:15px;">${(p.total||0).toLocaleString()} ر.س</span>
    </div>
    <table><thead><tr>
      <th style="font-size:12px;">الباركود</th><th style="font-size:12px;">المنتج</th>
      <th style="font-size:12px;">الكمية</th><th style="font-size:12px;">سعر الوحدة</th><th style="font-size:12px;">الاجمالي</th>
    </tr></thead><tbody>
    ${(p.items&&p.items.length>0) ? p.items.map(item=>`<tr>
      <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${item.barcode||item.product_id||'—'}</td>
      <td style="font-weight:600;color:#f1f5f9;">${item.product_name||('منتج #'+item.product_id)||'—'}</td>
      <td style="color:#94a3b8;">${item.qty||0} ${item.unit||'قطعة'}</td>
      <td>${(item.price||0).toLocaleString()} ر.س</td>
      <td style="color:#52b788;font-weight:700;">${((item.qty||0)*(item.price||0)).toLocaleString()} ر.س</td>
    </tr>`).join('') : '<tr><td colspan="5" style="text-align:center;color:#fbbf24;padding:10px;">لا توجد أصناف مسجلة</td></tr>'}
    </tbody></table>
  </div>`).join('')||'<div class="card" style="padding:28px;text-align:center;color:#475569;">لا توجد مشتريات في هذه الفترة</div>'}
  ${ps.length?`<div class="card" style="padding:14px;background:linear-gradient(135deg,#1a2e22,#161923);">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span style="color:#94a3b8;font-size:14px;">الاجمالي من ${date_from} الى ${date_to}</span>
      <span style="font-size:22px;font-weight:900;color:#52b788;">${total.toLocaleString()} ر.س</span>
    </div>
  </div>`:''}
  </div>
  <div style="display:flex;gap:10px;margin-top:14px;">
    <button class="btn p" onclick="doPrint()">🖨️ طباعة</button>
    <button class="btn s" onclick="doPDF()">📄 تصدير PDF</button>
  </div>`;
}

function printWrap(html){
  return `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;800&display=swap" rel="stylesheet">
  <style>*{font-family:'Tajawal',sans-serif;box-sizing:border-box}body{background:#fff;color:#111;padding:20px;direction:rtl}
  table{width:100%;border-collapse:collapse;margin-bottom:10px}
  th{background:#d4edda;font-weight:700;padding:7px 9px;text-align:right;border:1px solid #aaa;font-size:12px}
  td{padding:6px 8px;border:1px solid #ddd;font-size:13px}
  .card{border:1px solid #ddd;border-radius:6px;margin-bottom:10px;overflow:hidden}
  .stat{border:1px solid #ddd;border-radius:6px;padding:10px}
  @page{size:A4;margin:12mm}
  </style></head><body>
  ${html.replace(/class="badge [^"]*"/g,'style="font-weight:bold"').replace(/onclick="[^"]*"/g,'').replace(/id="[^"]*"/g,'')}
  </body></html>`;
}
window.doPrint=function(){
  const a=document.getElementById('spa');if(!a)return;
  const w=window.open('','_blank','width=900,height=700');
  w.document.write(printWrap(a.innerHTML));
  w.document.close(); setTimeout(()=>w.print(),700);
};
window.doPDF=function(){
  const a=document.getElementById('spa');if(!a)return;
  const w=window.open('','_blank','width=900,height=700');
  const html=printWrap(a.innerHTML).replace('<body>','<body onload="window.print()">');
  w.document.write(html); w.document.close();
};

// ── MODAL ──────────────────────────────────────
let MS=null, cart=[];

function modalHTML(){
  if(!MS) return '';
  if(MS.type==='pform')    return prodModal(MS.data||{});
  if(MS.type==='eform')    return entModal(MS.data||{});
  if(MS.type==='purform')  return purModal();
  if(MS.type==='editpur')  return editPurModal(MS.data||{});
  if(MS.type==='retpur')   return returnPurModal(MS.data||{});
  if(MS?.type==='payform')  return payModal(MS.data||{});
  if(MS?.type==='payhist')  return payHistModal(MS.data||{});
  if(MS.type==='done')     return doneModal(MS.data);
  return '';
}

// ── مودال إضافة دفعة ──
function payModal(d){
  const today = new Date().toISOString().slice(0,10);
  const paidSoFar = d.paid || 0;
  const remaining = Math.max(0, Math.abs(d.total||0) - paidSoFar);
  return '<div class="overlay" id="mover"><div class="modal" style="max-width:520px;">'
  + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">'
    + '<div><div style="font-size:16px;font-weight:700;color:#f1f5f9;">💳 إضافة دفعة</div>'
    + '<div style="font-size:12px;color:#64748b;margin-top:2px;">'+(d.ref_type==='purchase'?'فاتورة شراء':'فاتورة بيع')+' #'+d.ref_id+' — '+(d.party_name||'')+'</div></div>'
    + '<button class="btn s" style="padding:4px 9px;" id="mc">✕</button>'
  + '</div>'
  + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px;">'
    + '<div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي الفاتورة</div><div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-top:4px;">'+Math.abs(d.total||0).toLocaleString()+' ر.س</div></div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">المدفوع</div><div style="font-size:15px;font-weight:800;color:#52b788;margin-top:4px;">'+paidSoFar.toLocaleString()+' ر.س</div></div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">المتبقي</div><div style="font-size:15px;font-weight:800;color:'+(remaining>0?'#f87171':'#52b788')+';margin-top:4px;">'+remaining.toLocaleString()+' ر.س</div></div>'
  + '</div>'
  + '<div id="merr"></div>'
  + '<div class="g2" style="margin-bottom:12px;">'
    + '<div><label class="lbl">طريقة الدفع <span style="color:#f87171;">*</span></label>'
      + '<select class="inp" id="pay-method" onchange="toggleCheque(this.value)">'
        + '<option value="نقدي">💵 نقدي</option>'
        + '<option value="شيك">🏦 شيك</option>'
        + '<option value="تحويل بنكي">🔄 تحويل بنكي</option>'
        + '<option value="بطاقة">💳 بطاقة</option>'
      + '</select></div>'
    + '<div><label class="lbl">المبلغ <span style="color:#f87171;">*</span></label>'
      + '<input class="inp" type="number" id="pay-amount" value="'+remaining+'" min="0.01" step="0.01"/></div>'
    + '<div><label class="lbl">التاريخ <span style="color:#f87171;">*</span></label>'
      + '<input class="inp" type="date" id="pay-date" value="'+today+'"/></div>'
    + '<div><label class="lbl">ملاحظات</label>'
      + '<input class="inp" id="pay-notes" placeholder="ملاحظات اختيارية..."/></div>'
  + '</div>'
  + '<div id="cheque-fields" style="display:none;background:#1a1d27;border-radius:8px;padding:14px;margin-bottom:14px;">'
    + '<div style="font-size:13px;font-weight:700;color:#60a5fa;margin-bottom:10px;">🏦 بيانات الشيك</div>'
    + '<div class="g2">'
      + '<div><label class="lbl">رقم الشيك</label><input class="inp" id="pay-cheque-no" placeholder="رقم الشيك..."/></div>'
      + '<div><label class="lbl">تاريخ الشيك</label><input class="inp" type="date" id="pay-cheque-date" value="'+today+'"/></div>'
      + '<div style="grid-column:span 2"><label class="lbl">اسم البنك</label><input class="inp" id="pay-cheque-bank" placeholder="اسم البنك..."/></div>'
    + '</div>'
  + '</div>'
  + '<div style="display:flex;gap:10px;">'
    + '<button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 حفظ الدفعة</button>'
    + '<button class="btn s" id="mc2">إلغاء</button>'
  + '</div></div></div>';
}

// ── مودال سجل الدفعات ──
function payHistModal(d){
  const payments = d.payments || [];
  const paidTotal = payments.reduce((s,p)=>s+p.amount,0);
  const remaining = Math.max(0, Math.abs(d.total||0) - paidTotal);
  const rows = payments.map(p=>'<tr>'
    + '<td style="font-weight:600;">'+p.date+'</td>'
    + '<td><span class="badge '+(p.method==='نقدي'?'g':p.method==='شيك'?'b':'y')+'">'+p.method+'</span></td>'
    + '<td style="font-weight:800;color:#52b788;">'+p.amount.toLocaleString()+' ر.س</td>'
    + '<td style="font-size:12px;color:#64748b;">'+(p.cheque_no?'#'+p.cheque_no+' '+p.cheque_bank:'')+'</td>'
    + '<td style="font-size:12px;color:#94a3b8;">'+(p.notes||'')+'</td>'
    + '<td><button class="btn d" style="padding:3px 7px;" onclick="deletePay('+p.id+')">🗑️</button></td>'
  + '</tr>').join('');
  return '<div class="overlay" id="mover"><div class="modal" style="max-width:640px;">'
  + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
    + '<div><div style="font-size:16px;font-weight:700;color:#f1f5f9;">📋 سجل الدفعات</div>'
    + '<div style="font-size:12px;color:#64748b;margin-top:2px;">'+(d.ref_type==='purchase'?'فاتورة شراء':'فاتورة بيع')+' #'+d.ref_id+' — '+(d.party_name||'')+'</div></div>'
    + '<button class="btn s" style="padding:4px 9px;" id="mc">✕</button>'
  + '</div>'
  + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px;">'
    + '<div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي الفاتورة</div><div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-top:4px;">'+Math.abs(d.total||0).toLocaleString()+' ر.س</div></div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي المدفوع</div><div style="font-size:15px;font-weight:800;color:#52b788;margin-top:4px;">'+paidTotal.toLocaleString()+' ر.س</div></div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">المتبقي</div><div style="font-size:15px;font-weight:800;color:'+(remaining>0?'#f87171':'#52b788')+';margin-top:4px;">'+remaining.toLocaleString()+' ر.س</div></div>'
  + '</div>'
  + (payments.length
    ? '<div class="card" style="margin-bottom:14px;"><table><thead><tr><th>التاريخ</th><th>الطريقة</th><th>المبلغ</th><th>الشيك</th><th>ملاحظات</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>'
    : '<div style="text-align:center;color:#64748b;padding:20px;">لا توجد دفعات مسجلة</div>')
  + '<div style="display:flex;gap:10px;">'
    + '<button class="btn p" onclick="addPayFromHist()" style="flex:1;justify-content:center;">+ إضافة دفعة جديدة</button>'
    + '<button class="btn s" id="mc2">إغلاق</button>'
  + '</div></div></div>';
}

window.toggleCheque = function(val){
  const el=document.getElementById('cheque-fields');
  if(el) el.style.display=val==='شيك'?'block':'none';
};
window.deletePay = async function(id){
  if(!confirm('حذف هذه الدفعة؟')) return;
  try{ await api('DELETE','/api/payments/'+id); await loadAll(); closeM(); }
  catch(e){ alert('خطأ: '+e.message); }
};
window.addPayFromHist = function(){
  const d=MS?.data; if(!d) return;
  MS={type:'payform',data:d}; render();
};

function prodModal(item){
  const sups=suppliers.map(s=>`<option value="${s.id}"${item.supplier_id===s.id?' selected':''}>${s.name}</option>`).join('');
  return `<div class="overlay" id="mover"><div class="modal">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">${item.id?'تعديل المنتج':'اضافة منتج جديد'}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2">
    ${[['barcode','الباركود *','text'],['serial','السيريال','text'],['name','اسم المنتج *','text'],
       ['category','الفئة','text'],['unit','الوحدة','text'],['stock','المخزون','number'],
       ['buy_price','سعر الشراء','number'],['sell_price','سعر البيع','number']].map(([k,l,t])=>`
    <div><label class="lbl">${l}</label><input class="inp" id="pf${k}" type="${t}" value="${item[k]??''}"/></div>`).join('')}
    <div><label class="lbl">المورد</label>
      <select class="inp" id="pfsupp"><option value="">بدون مورد</option>${sups}</select>
    </div>
  </div>
  <div style="display:flex;gap:10px;margin-top:18px;">
    <button class="btn p" id="ms">${item.id?'حفظ التعديل':'اضافة'}</button>
    <button class="btn s" id="mc2">الغاء</button>
  </div></div></div>`;
}

function entModal(item){
  return `<div class="overlay" id="mover"><div class="modal">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">${item.id?'تعديل':'اضافة جديد'}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2">
    ${[['name','الاسم *'],['contact','جهة الاتصال'],['phone','الهاتف'],
       ['email','البريد'],['city','المدينة'],['balance','الرصيد']].map(([k,l])=>`
    <div><label class="lbl">${l}</label>
      <input class="inp" id="ef${k}" type="${k==='balance'?'number':'text'}" value="${item[k]??''}"/>
    </div>`).join('')}
    <div style="grid-column:span 2"><label class="lbl">ملاحظات</label>
      <textarea class="inp" id="efnotes" style="min-height:60px;">${item.notes||''}</textarea>
    </div>
  </div>
  <div style="display:flex;gap:10px;margin-top:18px;">
    <button class="btn p" id="ms">حفظ</button>
    <button class="btn s" id="mc2">الغاء</button>
  </div></div></div>`;
}

function purModal(){
  const tot=cart.reduce((s,i)=>s+i.qty*i.price,0);
  const sups=suppliers.map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
  const prods=products.map(p=>`<option value="${p.id}" data-price="${p.buy_price}" data-name="${p.name}">${p.name} — ${p.barcode}</option>`).join('');
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:700px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">فاتورة شراء جديدة</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div class="g2" style="margin-bottom:12px;">
    <div><label class="lbl" style="display:flex;align-items:center;gap:4px;">المورد <span style="color:#f87171;font-size:16px;">*</span></label>
      <select class="inp" id="pus" onchange="this.style.border=''" style="border:1px solid #2d3349;">
        <option value="">-- اختر المورد (مطلوب) --</option>${sups}
      </select>
    </div>
    <div><label class="lbl">التاريخ</label>
      <input class="inp" type="date" id="pud" value="${new Date().toISOString().slice(0,10)}"/>
    </div>
    <div><label class="lbl">الحالة</label>
      <select class="inp" id="pust">${['معلق','مدفوع','مدفوع جزئياً'].map(s=>`<option>${s}</option>`).join('')}</select>
    </div>
  </div>

  <div style="background:#1a1d27;border:1px solid #2d3349;border-radius:10px;padding:14px;margin-bottom:12px;">
    <div style="font-size:13px;font-weight:700;color:#52b788;margin-bottom:10px;">اضافة منتج</div>
    <div class="g2" style="gap:10px;">
      <div style="grid-column:span 2;">
        <label class="lbl">ابحث عن المنتج</label>
        <div style="position:relative;">
          <input class="inp" id="puq" placeholder="اكتب اسم المنتج أو الباركود للبحث..." autocomplete="off"/>
          <div id="puq-list" style="display:none;position:absolute;top:100%;right:0;left:0;background:#1e2130;border:1px solid #2d6a4f;border-radius:0 0 8px 8px;max-height:200px;overflow-y:auto;z-index:100;"></div>
        </div>
      </div>
      <div>
        <label class="lbl">او اختر من القائمة</label>
        <select class="inp" id="pur-prod-select">
          <option value="">-- اختر منتج --</option>${prods}
        </select>
      </div>
      <div>
        <label class="lbl">الكمية</label>
        <input class="inp" type="number" id="pur-qty" value="1" min="1"/>
      </div>
      <div>
        <label class="lbl">سعر الشراء</label>
        <input class="inp" type="number" id="pur-price" value="" placeholder="0"/>
      </div>
      <div style="display:flex;align-items:flex-end;">
        <button class="btn p" id="puab" style="width:100%;justify-content:center;height:42px;">+ اضافة للفاتورة</button>
      </div>
    </div>
    <div id="pur-selected" style="margin-top:10px;display:none;">
      <div style="background:#161923;border:1px solid #2d6a4f;border-radius:8px;padding:10px;display:flex;justify-content:space-between;align-items:center;">
        <div>
          <div style="font-weight:700;color:#f1f5f9;font-size:14px;" id="pur-sel-name">—</div>
          <div style="font-size:12px;color:#64748b;" id="pur-sel-info">—</div>
        </div>
        <span class="badge g" id="pur-sel-stock">—</span>
      </div>
    </div>
  </div>

  ${cart.length?`<div class="card" style="margin-bottom:12px;">
  <div style="padding:10px 14px;background:#1a1d27;border-bottom:1px solid #1e2537;font-weight:700;color:#f1f5f9;font-size:13px;">
    اصناف الفاتورة (${cart.length} صنف)
  </div>
  <table><thead><tr><th>المنتج</th><th>الكمية</th><th>سعر الشراء</th><th>الاجمالي</th><th></th></tr></thead><tbody>
  ${cart.map(i=>`<tr>
    <td style="font-weight:600;color:#f1f5f9;">${i.name}</td>
    <td><input class="inp" type="number" style="width:70px;padding:4px 7px;" value="${i.qty}" min="1" onchange="updCart(${i.product_id},'qty',this.value)"/></td>
    <td><input class="inp" type="number" style="width:90px;padding:4px 7px;" value="${i.price}" onchange="updCart(${i.product_id},'price',this.value)"/></td>
    <td style="color:#52b788;font-weight:700;">${(i.qty*i.price).toLocaleString()} ر.س</td>
    <td><button class="btn d" style="padding:3px 7px;" onclick="remCart(${i.product_id})">🗑️</button></td>
  </tr>`).join('')}
  </tbody></table>
  <div style="text-align:left;padding:10px 16px;font-size:17px;font-weight:800;color:#52b788;border-top:1px solid #1e2537;">
    المجموع: ${tot.toLocaleString()} ر.س
  </div></div>`:'<div style="color:#64748b;text-align:center;padding:16px;font-size:13px;background:#1a1d27;border-radius:8px;margin-bottom:12px;">لم يتم اضافة اي صنف بعد</div>'}
  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms">💾 حفظ الفاتورة</button>
    <button class="btn s" id="mc2">الغاء</button>
  </div></div></div>`;
}

function showPurSelected(p) {
  const box = document.getElementById('pur-selected');
  if(!box) return;
  document.getElementById('pur-sel-name').textContent = p.name;
  document.getElementById('pur-sel-info').textContent = 'باركود: '+p.barcode+' | '+(p.category||'')+' | سعر الشراء: '+p.buy_price+' ر.س';
  document.getElementById('pur-sel-stock').textContent = 'مخزون: '+p.stock+' '+p.unit;
  box.style.display='block';
}

function doneModal(sale){
  return `<div class="overlay" id="mover"><div class="modal" style="text-align:center;max-width:340px;">
  <div style="font-size:54px;margin-bottom:10px;">✅</div>
  <div style="font-size:19px;font-weight:800;color:#52b788;margin-bottom:5px;">تمت عملية البيع!</div>
  <div style="color:#64748b;margin-bottom:14px;">فاتورة #${sale.id}</div>
  <div style="background:#1a1d27;border-radius:10px;padding:13px;margin-bottom:18px;">
    <div style="font-size:24px;font-weight:900;color:#f1f5f9;">${(sale.total||0).toLocaleString()} ر.س</div>
    <div style="color:#64748b;font-size:13px;margin-top:3px;">${sale.pay_method} — ${sale.date}</div>
  </div>
  <button class="btn s" id="mc" style="width:100%;justify-content:center;">اغلاق</button>
  </div></div>`;
}

// ── modal تعديل فاتورة الشراء ──
function editPurModal(p){
  const sups = suppliers.map(s=>'<option value="'+s.id+'"'+(parseInt(p.supplier_id)===s.id?' selected':'')+'>'+s.name+'</option>').join('');
  const prods = products.map(x=>'<option value="'+x.id+'" data-price="'+x.buy_price+'" data-name="'+x.name+'">'+x.name+' — '+x.barcode+'</option>').join('');
  const cartRows = (p.items||[]).map(item=>`
    <tr id="ei-row-${item.product_id}">
      <td style="font-weight:600;color:#f1f5f9;">${item.product_name||products.find(x=>x.id===item.product_id)?.name||'—'}</td>
      <td><input class="inp" type="number" style="width:70px;padding:4px 7px;" value="${item.qty}" id="eq-${item.product_id}" min="1"/></td>
      <td><input class="inp" type="number" style="width:85px;padding:4px 7px;" value="${item.price}" id="ep-${item.product_id}"/></td>
      <td style="color:#52b788;font-weight:700;" id="et-${item.product_id}">${(item.qty*item.price).toLocaleString()} ر.س</td>
      <td><button class="btn d" style="padding:3px 7px;" onclick="removeEditItem(${item.product_id})">🗑️</button></td>
    </tr>`).join('');
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:720px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">✏️ تعديل الفاتورة #${p.id}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div class="g2" style="margin-bottom:14px;">
    <div><label class="lbl">المورد</label>
      <select class="inp" id="edit-pus">${sups}</select>
    </div>
    <div><label class="lbl">التاريخ</label>
      <input class="inp" type="date" id="edit-pud" value="${p.date}"/>
    </div>
    <div><label class="lbl">الحالة</label>
      <select class="inp" id="edit-pust">
        ${['معلق','مدفوع','مدفوع جزئياً'].map(s=>'<option'+(p.status===s?' selected':'')+'>'+s+'</option>').join('')}
      </select>
    </div>
    <div><label class="lbl">ملاحظات</label>
      <input class="inp" id="edit-notes" value="${p.notes||''}"/>
    </div>
  </div>
  <div style="background:#1a1d27;border:1px solid #2d3349;border-radius:8px;padding:12px;margin-bottom:12px;">
    <div style="font-size:13px;font-weight:700;color:#52b788;margin-bottom:10px;">إضافة صنف جديد</div>
    <div style="display:flex;gap:8px;">
      <select class="inp" id="edit-prod-sel" style="flex:2;">
        <option value="">-- اختر منتج --</option>${prods}
      </select>
      <input class="inp" type="number" id="edit-add-qty" placeholder="الكمية" style="width:80px;" value="1" min="1"/>
      <input class="inp" type="number" id="edit-add-price" placeholder="السعر" style="width:90px;"/>
      <button class="btn p" id="edit-add-btn" style="white-space:nowrap;">+ إضافة</button>
    </div>
  </div>
  <div class="card" style="margin-bottom:14px;">
    <table id="edit-items-table">
      <thead><tr><th>المنتج</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th></th></tr></thead>
      <tbody id="edit-items-body">${cartRows}</tbody>
    </table>
    <div id="edit-total-row" style="text-align:left;padding:10px 16px;font-size:16px;font-weight:800;color:#52b788;border-top:1px solid #1e2537;"></div>
  </div>
  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms">💾 حفظ التعديلات</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

// ── modal مردود المشتريات ──
function returnPurModal(p){
  const items = p.items||[];
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:680px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div style="font-size:16px;font-weight:700;color:#fbbf24;">↩️ مردود مشتريات — فاتورة #${p.id}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div style="background:#1a1d27;border:1px solid #5c4a23;border-radius:8px;padding:12px;margin-bottom:14px;">
    <div style="font-size:13px;color:#fbbf24;margin-bottom:4px;">ℹ️ تفاصيل الفاتورة الأصلية</div>
    <div style="font-size:13px;color:#94a3b8;">المورد: ${suppliers.find(s=>parseInt(s.id)===parseInt(p.supplier_id))?.name||'—'} | التاريخ: ${p.date} | الإجمالي: ${(p.total||0).toLocaleString()} ر.س</div>
  </div>
  <div class="g2" style="margin-bottom:14px;">
    <div><label class="lbl">تاريخ المردود</label>
      <input class="inp" type="date" id="ret-date" value="${new Date().toISOString().slice(0,10)}"/>
    </div>
    <div><label class="lbl">ملاحظات</label>
      <input class="inp" id="ret-notes" placeholder="سبب المردود..."/>
    </div>
  </div>
  <div style="font-size:13px;font-weight:700;color:#f1f5f9;margin-bottom:10px;">اختر الأصناف المرتجعة والكمية:</div>
  <div class="card" style="margin-bottom:14px;">
    <table>
      <thead><tr><th>المنتج</th><th>الكمية المشتراة</th><th>كمية المردود</th><th>السعر</th></tr></thead>
      <tbody>
        ${items.map(item=>`<tr>
          <td style="font-weight:600;color:#f1f5f9;">${item.product_name||'—'}</td>
          <td style="color:#94a3b8;">${item.qty} ${item.unit||''}</td>
          <td><input class="inp" type="number" id="rq-${item.product_id}" value="0" min="0" max="${item.qty}" style="width:80px;padding:4px 8px;"/></td>
          <td style="color:#52b788;">${(item.price||0).toLocaleString()} ر.س</td>
        </tr>`).join('')}
      </tbody>
    </table>
  </div>
  <div style="display:flex;gap:10px;">
    <button class="btn p" style="background:linear-gradient(135deg,#b45309,#92400e);" id="ms">↩️ تأكيد المردود</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

function closeM(){MS=null; render();}

function bindModal(){
  document.getElementById('mover')?.addEventListener('click',e=>{if(e.target.id==='mover')closeM();});
  document.getElementById('mc')?.addEventListener('click',closeM);
  document.getElementById('mc2')?.addEventListener('click',closeM);

  if(MS?.type==='pform'){
    document.getElementById('ms').onclick=async()=>{
      const g=k=>document.getElementById('pf'+k)?.value||'';
      const item=MS.data||{};
      const d={barcode:g('barcode'),serial:g('serial'),name:g('name'),category:g('category'),
               unit:g('unit')||'قطعة',stock:+g('stock')||0,buy_price:+g('buy_price')||0,
               sell_price:+g('sell_price')||0,
               supplier_id:document.getElementById('pfsupp')?.value||null};
      if(!d.name||!d.barcode){document.getElementById('merr').innerHTML='<div class="err">الاسم والباركود مطلوبان</div>';return;}
      try{
        if(item.id) await api('PUT',`/api/products/${item.id}`,d);
        else await api('POST','/api/products',d);
        await loadAll(); closeM();
      }catch(e){document.getElementById('merr').innerHTML=`<div class="err">${e.message}</div>`;}
    };
  }

  if(MS?.type==='eform'){
    document.getElementById('ms').onclick=async()=>{
      const g=k=>document.getElementById('ef'+k)?.value||'';
      const t=MS.etype; const item=MS.data||{};
      const d={name:g('name'),contact:g('contact'),phone:g('phone'),email:g('email'),
               city:g('city'),balance:+g('balance')||0,notes:g('notes')};
      if(!d.name){document.getElementById('merr').innerHTML='<div class="err">الاسم مطلوب</div>';return;}
      try{
        if(item.id) await api('PUT',`/api/${t}/${item.id}`,d);
        else await api('POST',`/api/${t}`,d);
        await loadAll(); closeM();
      }catch(e){document.getElementById('merr').innerHTML=`<div class="err">${e.message}</div>`;}
    };
  }

  if(MS?.type==='purform'){
    // ── ربط حقل البحث بالأحداث ──
    const puqEl  = document.getElementById('puq');
    const purSel = document.getElementById('pur-prod-select');
    const puqBox = document.getElementById('puq-list');

    // تفعيل البحث التلقائي عند الكتابة
    if(puqEl){
      puqEl.addEventListener('input', function(){
        const q = this.value.trim();
        if(!q){ if(puqBox) puqBox.style.display='none'; return; }
        const found = products.filter(p=>
          p.name.includes(q)||p.barcode.includes(q)||(p.serial||'').includes(q)
        ).slice(0,8);
        if(!puqBox) return;
        if(!found.length){ puqBox.style.display='none'; return; }
        puqBox.innerHTML = found.map(p=>`
          <div class="pur-sug" data-id="${p.id}"
            style="padding:10px 14px;cursor:pointer;border-bottom:1px solid #2d3349;"
            onmouseover="this.style.background='#252839'"
            onmouseout="this.style.background=''">
            <div style="font-weight:700;color:#f1f5f9;font-size:13px;">${p.name}</div>
            <div style="font-size:11px;color:#64748b;margin-top:2px;">
              ${p.barcode}${p.serial?' | سيريال: '+p.serial:''} | مخزون: ${p.stock} ${p.unit} | سعر الشراء: ${p.buy_price} ر.س
            </div>
          </div>`).join('');
        puqBox.style.display = 'block';
        // ربط النقر على النتائج
        puqBox.querySelectorAll('.pur-sug').forEach(el=>{
          el.addEventListener('click', function(){
            const pid = parseInt(this.dataset.id);
            const p   = products.find(x=>x.id===pid);
            if(!p) return;
            puqEl.value = p.name;
            if(purSel) purSel.value = p.id;
            document.getElementById('pur-price').value = p.buy_price;
            puqBox.style.display = 'none';
            // عرض معلومات المنتج
            const box = document.getElementById('pur-selected');
            if(box){
              document.getElementById('pur-sel-name').textContent = p.name;
              document.getElementById('pur-sel-info').textContent = 'باركود: '+p.barcode+' | '+p.category+' | سعر الشراء: '+p.buy_price+' ر.س';
              document.getElementById('pur-sel-stock').textContent = 'مخزون: '+p.stock+' '+p.unit;
              box.style.display='block';
            }
            document.getElementById('pur-qty').focus();
          });
        });
      });
    }

    // ربط القائمة المنسدلة
    if(purSel){
      purSel.addEventListener('change', function(){
        const pid = parseInt(this.value);
        if(!pid) return;
        const p = products.find(x=>x.id===pid);
        if(!p) return;
        if(puqEl) puqEl.value = p.name;
        document.getElementById('pur-price').value = p.buy_price;
        const box = document.getElementById('pur-selected');
        if(box){
          document.getElementById('pur-sel-name').textContent = p.name;
          document.getElementById('pur-sel-info').textContent = 'باركود: '+p.barcode+' | '+p.category+' | سعر الشراء: '+p.buy_price+' ر.س';
          document.getElementById('pur-sel-stock').textContent = 'مخزون: '+p.stock+' '+p.unit;
          box.style.display='block';
        }
        document.getElementById('pur-qty').focus();
      });
    }

    const addItem=()=>{
      let p = null;
      // 1. من القائمة المنسدلة
      if(purSel && purSel.value) p = products.find(x=>x.id===parseInt(purSel.value));
      // 2. من حقل النص
      if(!p && puqEl?.value){
        const q=puqEl.value.trim();
        p=products.find(x=>x.barcode===q||x.serial===q||x.name===q||x.name.includes(q));
      }
      if(!p){ alert('يرجى اختيار منتج من القائمة أو البحث'); return; }

      const qty   = parseInt(document.getElementById('pur-qty')?.value)||1;
      const price = parseFloat(document.getElementById('pur-price')?.value)||p.buy_price;

      const ex=cart.find(i=>i.product_id===p.id);
      if(ex){ ex.qty+=qty; ex.price=price; }
      else cart.push({product_id:p.id, name:p.name, qty, price});

      // تنظيف الحقول
      if(puqEl)  puqEl.value='';
      if(purSel) purSel.value='';
      if(puqBox) puqBox.style.display='none';
      document.getElementById('pur-qty').value='1';
      document.getElementById('pur-price').value='';
      const selBox=document.getElementById('pur-selected');
      if(selBox) selBox.style.display='none';

      MS={type:'purform'}; render(); bindModal();
    };

    document.getElementById('puab')?.addEventListener('click', addItem);
    if(puqEl) puqEl.addEventListener('keydown', e=>{ if(e.key==='Enter'){e.preventDefault();addItem();} });
    document.getElementById('ms').onclick=async()=>{
      const sup    = document.getElementById('pus').value;
      const date   = document.getElementById('pud').value;
      const status = document.getElementById('pust').value;
      // التحقق من المورد
      if(!sup){
        document.getElementById('pus').style.border='2px solid #f87171';
        document.getElementById('pus').focus();
        alert('⚠️ يرجى تحديد المورد أولاً');
        return;
      }
      // التحقق من الأصناف
      if(!cart.length){
        alert('⚠️ يرجى إضافة منتج واحد على الأقل');
        return;
      }
      document.getElementById('pus').style.border='';
      const isEdit = MS.editId;
      try{
        const body = {
          supplier_id: parseInt(sup), date, status, notes:'',
          items: cart.map(i=>({product_id:i.product_id,qty:i.qty,price:i.price}))
        };
        if(isEdit){
          await api('PUT','/api/purchases/'+isEdit, body);
        } else {
          await api('POST','/api/purchases', body);
        }
        cart=[]; await loadAll(); closeM();
      }catch(e){alert('خطأ: '+e.message);}
    };
  }

  // ── تعديل فاتورة مشتريات ──
  if(MS?.type==='editpur'){
    document.getElementById('ms').onclick=async()=>{
      const sup    = document.getElementById('pus').value;
      const date   = document.getElementById('pud').value;
      const status = document.getElementById('pust').value;
      const eid    = MS.editId;
      if(!sup){
        document.getElementById('pus').style.border='2px solid #f87171';
        document.getElementById('pus').focus();
        alert('⚠️ يرجى تحديد المورد أولاً');
        return;
      }
      if(!cart.length){
        alert('⚠️ يرجى إضافة منتج واحد على الأقل');
        return;
      }
      document.getElementById('pus').style.border='';
      try{
        await api('PUT','/api/purchases/'+eid,{
          supplier_id: parseInt(sup), date, status, notes:'',
          items: cart.map(i=>({product_id:i.product_id,qty:i.qty,price:i.price}))
        });
        cart=[]; await loadAll(); closeM();
      }catch(e){alert('خطأ: '+e.message);}
    };

    // نفس منطق إضافة الأصناف كـ purform
    const addItemE=()=>{
      const selEl=document.getElementById('pur-prod-select');
      const qVal=document.getElementById('puq')?.value||'';
      let p=null;
      if(selEl&&selEl.value) p=products.find(x=>x.id===parseInt(selEl.value));
      if(!p&&qVal) p=products.find(x=>x.barcode===qVal||x.name===qVal||x.name.includes(qVal));
      if(!p){alert('اختر منتجا');return;}
      const qty=parseInt(document.getElementById('pur-qty')?.value)||1;
      const price=parseFloat(document.getElementById('pur-price')?.value)||p.buy_price;
      const ex=cart.find(i=>i.product_id===p.id);
      if(ex){ex.qty+=qty;ex.price=price;}
      else cart.push({product_id:p.id,name:p.name,qty,price});
      document.getElementById('puq').value='';
      if(selEl)selEl.value='';
      MS={type:'editpur',editId:MS.editId,editData:MS.editData};
      render(); bindModal();
    };
    document.getElementById('puab')?.addEventListener('click',addItemE);
    document.getElementById('puq')?.addEventListener('keydown',e=>e.key==='Enter'&&addItemE());
  }

  // ── دفعة جديدة ──
  if(MS?.type==='payform'){
    document.getElementById('ms').onclick = async()=>{
      const method  = document.getElementById('pay-method')?.value||'نقدي';
      const amount  = parseFloat(document.getElementById('pay-amount')?.value||0);
      const date    = document.getElementById('pay-date')?.value||'';
      const notes   = document.getElementById('pay-notes')?.value||'';
      const cheqNo  = document.getElementById('pay-cheque-no')?.value||'';
      const cheqDt  = document.getElementById('pay-cheque-date')?.value||'';
      const cheqBnk = document.getElementById('pay-cheque-bank')?.value||'';
      const d       = MS.data||{};
      const errEl   = document.getElementById('merr');

      if(!amount||amount<=0){
        if(errEl) errEl.innerHTML='<div class="err">⚠️ أدخل مبلغاً أكبر من صفر</div>';
        return;
      }
      if(!date){
        if(errEl) errEl.innerHTML='<div class="err">⚠️ حدد تاريخ الدفعة</div>';
        return;
      }
      if(method==='شيك'&&!cheqNo){
        if(errEl) errEl.innerHTML='<div class="err">⚠️ أدخل رقم الشيك</div>';
        return;
      }

      try{
        await api('POST','/api/payments',{
          ref_type:   d.ref_type,
          ref_id:     d.ref_id,
          party_type: d.party_type,
          party_id:   d.party_id,
          amount, method, date, notes,
          cheque_no:   cheqNo,
          cheque_date: cheqDt,
          cheque_bank: cheqBnk
        });
        await loadAll();
        closeM();
        alert('✅ تم حفظ الدفعة بنجاح');
      }catch(e){
        if(errEl) errEl.innerHTML='<div class="err">خطأ: '+e.message+'</div>';
      }
    };
  }

  // ── مردود مشتريات ──
  if(MS?.type==='retpur'){
    document.getElementById('ms').onclick=async()=>{
      const p     = MS.data||{};
      const date  = document.getElementById('ret-date')?.value||new Date().toISOString().slice(0,10);
      const notes = document.getElementById('ret-notes')?.value||'';
      const retItems=[];
      (p.items||[]).forEach(item=>{
        const qtyEl=document.getElementById('rq-'+item.product_id);
        const qty=parseInt(qtyEl?.value)||0;
        if(qty>0) retItems.push({product_id:item.product_id,qty,price:item.price});
      });
      if(!retItems.length){alert('حدد كمية مردود لصنف واحد على الأقل');return;}
      try{
        await api('POST','/api/purchase_return',{
          purchase_id:p.id, date, notes, items:retItems
        });
        await loadAll(); closeM();
        alert('تم تسجيل المردود بنجاح ✅');
      }catch(e){alert('خطأ: '+e.message);}
    };
  }
}

// ── فتح مودال إضافة دفعة ──
window.openPay = async function(ref_id, ref_type){
  // جلب الدفعات المسبقة لحساب المتبقي
  const inv = ref_type==='purchase'
    ? purchases.find(p=>p.id===ref_id)
    : sales.find(s=>s.id===ref_id);
  if(!inv){ alert('الفاتورة غير موجودة'); return; }

  let paidSoFar = 0;
  try{
    const pays = await api('GET', '/api/payments?ref_type='+ref_type+'&ref_id='+ref_id);
    paidSoFar = pays.reduce((s,p)=>s+p.amount, 0);
  }catch(e){}

  const party_id   = ref_type==='purchase' ? inv.supplier_id : inv.customer_id;
  const party_type = ref_type==='purchase' ? 'supplier' : 'customer';
  const party_name = ref_type==='purchase'
    ? suppliers.find(s=>s.id===parseInt(party_id))?.name||'—'
    : customers.find(c=>c.id===parseInt(party_id))?.name||'—';

  MS = {type:'payform', data:{
    ref_type, ref_id,
    party_type, party_id,
    party_name,
    total: inv.total,
    paid: paidSoFar
  }};
  render();
};

// ── عرض سجل الدفعات ──
window.viewPayHist = async function(ref_id, ref_type){
  const inv = ref_type==='purchase'
    ? purchases.find(p=>p.id===ref_id)
    : sales.find(s=>s.id===ref_id);
  if(!inv){ alert('الفاتورة غير موجودة'); return; }

  const party_id   = ref_type==='purchase' ? inv.supplier_id : inv.customer_id;
  const party_name = ref_type==='purchase'
    ? suppliers.find(s=>s.id===parseInt(party_id))?.name||'—'
    : customers.find(c=>c.id===parseInt(party_id))?.name||'—';

  let payments = [];
  try{
    payments = await api('GET', '/api/payments?ref_type='+ref_type+'&ref_id='+ref_id);
  }catch(e){}

  MS = {type:'payhist', data:{
    ref_type, ref_id,
    party_name,
    total: inv.total,
    payments,
    party_type: ref_type==='purchase'?'supplier':'customer',
    party_id
  }};
  render();
};

window.updCart=function(pid,f,v){const i=cart.find(x=>x.product_id===pid);if(i)i[f]=+v;};
window.remCart=function(pid){cart=cart.filter(x=>x.product_id!==pid);MS={type:'purform'};render();bindModal();};

// ── تعديل فاتورة مشتريات ──
window.editPur = function(id){
  const p = purchases.find(x=>x.id===id);
  if(!p){ alert('الفاتورة غير موجودة'); return; }
  cart = (p.items||[]).map(i=>({
    product_id: i.product_id,
    name: i.product_name || products.find(x=>x.id===i.product_id)?.name || '—',
    qty: i.qty,
    price: i.price
  }));
  MS = {type:'editpur', editId:id, editData:p};
  render();
};

// ── حذف فاتورة مشتريات ──
window.deletePur = async function(id){
  if(!confirm('هل تريد حذف هذه الفاتورة؟\nسيتم إرجاع المخزون تلقائياً')) return;
  try{
    await api('DELETE', '/api/purchases/'+id);
    await loadAll();
    alert('تم حذف الفاتورة ✅');
  }catch(e){ alert('خطأ: '+e.message); }
};

// ── مردود مشتريات ──
window.returnPur = function(id){
  const p = purchases.find(x=>x.id===id);
  if(!p){ alert('الفاتورة غير موجودة'); return; }
  if((p.items||[]).length===0){ alert('لا توجد أصناف في هذه الفاتورة'); return; }
  MS = {type:'retpur', data:p};
  render();
};

// ── PAGE BINDINGS ──────────────────────────────
function bindPage(){
  // Products
  const pa=document.getElementById('pa');
  if(pa){
    pa.onclick=()=>{MS={type:'pform',data:{}};render();};
    renderProds();
    const pq=document.getElementById('pq');
    if(pq) pq.oninput=()=>renderProds(pq.value);
  }

  // Purchases
  const pura=document.getElementById('pur-add');
  if(pura) pura.onclick=()=>{cart=[];MS={type:'purform'};render();};

  const pfb=document.getElementById('pfb');
  if(pfb){
    pfb.onclick=()=>{
      const f=document.getElementById('pff').value, t=document.getElementById('pft').value;
      const fl=purchases.filter(p=>p.date>=f&&p.date<=t);
      document.getElementById('pur-tb').innerHTML=purRows(fl);
      document.getElementById('pur-sum').innerHTML=purSum(fl);
      document.getElementById('pur-grand').textContent='الاجمالي: '+fl.reduce((s,p)=>s+p.total,0).toLocaleString()+' ر.س';
    };
    document.getElementById('pfc').onclick=()=>{
      document.getElementById('pur-tb').innerHTML=purRows(purchases);
      document.getElementById('pur-sum').innerHTML=purSum(purchases);
      document.getElementById('pur-grand').textContent='الاجمالي: '+purchases.reduce((s,p)=>s+p.total,0).toLocaleString()+' ر.س';
    };
  }

  // Entity
  const ea=document.getElementById('ea');
  if(ea){
    ea.onclick=()=>{MS={type:'eform',etype:ea.dataset.type,data:{}};render();};
    renderEntity(ea.dataset.type||page);
    const eq=document.getElementById('eq');
    if(eq) eq.oninput=()=>renderEntity(ea.dataset.type||page,eq.value);
  }

  // Reports
  document.querySelectorAll('[data-rep]').forEach(btn=>{
    btn.onclick=()=>{
      document.querySelectorAll('[data-rep]').forEach(b=>b.className='btn s');
      btn.className='btn p';
      document.getElementById('rc').innerHTML=repContent(btn.dataset.rep);
    };
  });

  bindPOS();
}

// ── POS ────────────────────────────────────────
let pCart=[];
function bindPOS(){
  const inp=document.getElementById('pi');
  if(!inp) return;

  // ربط البحث التلقائي
  inp.addEventListener('input', function(){
    posSuggest(this.value);
  });

  // ربط التنقل بالكيبورد
  inp.addEventListener('keydown', function(e){
    posKeyNav(e);
  });

  // زر الإضافة
  const po = document.getElementById('po');
  if(po) po.addEventListener('click', posAdd);

  // زر إتمام البيع
  const pco = document.getElementById('pco');
  if(pco) pco.addEventListener('click', posCheckout);

  // زر مسح السلة
  const pcl = document.getElementById('pcl');
  if(pcl) pcl.addEventListener('click', ()=>{ pCart=[]; renderCart(); });

  // إغلاق قائمة البحث عند الضغط خارجها
  setTimeout(()=>{
    document.addEventListener('click', function closeSug(e){
      const box = document.getElementById('pos-suggest');
      if(!box) return;
      if(!inp.contains(e.target) && !box.contains(e.target)){
        box.style.display='none';
        posSugIdx=-1;
      }
    });
  }, 100);

  inp.focus();
  renderCart();
}
window.addCart=function(id){
  const p=products.find(x=>x.id===id); if(!p)return;
  const ex=pCart.find(i=>i.id===p.id);
  if(ex) ex.qty++; else pCart.push({...p,qty:1});
  renderCart();
};

// ── بحث ذكي في نقطة البيع ──
let posSugIdx = -1;

window.posSuggest = function(q){
  const box = document.getElementById('pos-suggest');
  if(!box) return;
  posSugIdx = -1;

  if(!q || q.trim().length === 0){
    box.style.display = 'none';
    return;
  }

  const ql = q.toLowerCase();
  const found = products.filter(p =>
    p.name.toLowerCase().includes(ql) ||
    p.barcode.includes(q) ||
    (p.serial||'').includes(q) ||
    (p.category||'').toLowerCase().includes(ql)
  ).slice(0, 8);

  if(!found.length){
    box.innerHTML = '<div style="padding:14px;color:#64748b;text-align:center;font-size:13px;">لا توجد نتائج</div>';
    box.style.display = 'block';
    return;
  }

  box.innerHTML = found.map((p,i) => `
    <div class="pos-sug-item" data-id="${p.id}" data-idx="${i}"
      onclick="posPickSug(${p.id})"
      onmouseover="posHover(${i})"
      style="display:flex;justify-content:space-between;align-items:center;
             padding:10px 14px;cursor:pointer;border-bottom:1px solid #2d3349;
             transition:background .15s;">
      <div>
        <div style="font-weight:700;color:#f1f5f9;font-size:14px;">${p.name}</div>
        <div style="font-size:11px;color:#64748b;margin-top:2px;">
          ${p.barcode}${p.serial?' | '+p.serial:''} | ${p.category||''}
        </div>
      </div>
      <div style="text-align:left;margin-right:10px;">
        <div style="font-weight:800;color:#52b788;font-size:14px;">${p.sell_price.toLocaleString()} ر.س</div>
        <div class="badge ${p.stock===0?'r':p.stock<5?'y':'g'}" style="font-size:11px;margin-top:3px;">
          ${p.stock===0?'نفد المخزون':'مخزون: '+p.stock+' '+p.unit}
        </div>
      </div>
    </div>`).join('');

  box.style.display = 'block';
};

window.posHover = function(idx){
  posSugIdx = idx;
  document.querySelectorAll('.pos-sug-item').forEach((el,i)=>{
    el.style.background = i===idx ? '#252839' : '';
  });
};

window.posPickSug = function(id){
  const p = products.find(x=>x.id===id);
  if(!p) return;
  // إضافة للسلة
  const ex = pCart.find(i=>i.id===p.id);
  if(ex) ex.qty++; else pCart.push({...p,qty:1});
  // إغلاق القائمة وتنظيف الحقل
  const box = document.getElementById('pos-suggest');
  const inp = document.getElementById('pi');
  if(box) box.style.display = 'none';
  if(inp){ inp.value = ''; inp.focus(); }
  posSugIdx = -1;
  renderCart();
};

window.posKeyNav = function(e){
  const box  = document.getElementById('pos-suggest');
  const items = document.querySelectorAll('.pos-sug-item');

  if(e.key === 'ArrowDown'){
    e.preventDefault();
    posSugIdx = Math.min(posSugIdx+1, items.length-1);
    items.forEach((el,i)=>el.style.background = i===posSugIdx?'#252839':'');
  } else if(e.key === 'ArrowUp'){
    e.preventDefault();
    posSugIdx = Math.max(posSugIdx-1, 0);
    items.forEach((el,i)=>el.style.background = i===posSugIdx?'#252839':'');
  } else if(e.key === 'Enter'){
    e.preventDefault();
    if(posSugIdx >= 0 && items[posSugIdx]){
      const id = parseInt(items[posSugIdx].dataset.id);
      posPickSug(id);
    } else {
      // إذا لا يوجد اختيار — استخدم نص الحقل مباشرة
      posAdd();
    }
  } else if(e.key === 'Escape'){
    if(box) box.style.display = 'none';
    posSugIdx = -1;
  }
};

// إغلاق القائمة عند الضغط خارجها
document.addEventListener('click', function(e){
  const box = document.getElementById('pos-suggest');
  const inp = document.getElementById('pi');
  if(box && inp && !inp.contains(e.target) && !box.contains(e.target)){
    box.style.display = 'none';
    posSugIdx = -1;
  }
});
function posAdd(){
  const inp = document.getElementById('pi');
  const q   = inp?.value?.trim()||'';
  if(!q) return;

  // إغلاق قائمة الاقتراحات
  const box = document.getElementById('pos-suggest');
  if(box) box.style.display = 'none';

  const p = products.find(x=>
    x.barcode===q || x.serial===q ||
    x.name===q    || x.name.toLowerCase().includes(q.toLowerCase())
  );
  if(!p){
    // تلوين الحقل بالأحمر مؤقتاً
    if(inp){ inp.style.borderColor='#f87171'; setTimeout(()=>inp.style.borderColor='',1500); }
    alert('المنتج غير موجود — جرب البحث بالاسم أو الباركود');
    return;
  }
  if(p.stock===0){
    if(!confirm('تحذير: المخزون نفد! هل تريد الإضافة للسلة؟')) return;
  }
  const ex=pCart.find(i=>i.id===p.id);
  if(ex) ex.qty++; else pCart.push({...p,qty:1});
  if(inp){ inp.value=''; inp.focus(); }
  posSugIdx=-1;
  renderCart();
}
function renderCart(){
  const ci=document.getElementById('ci'), ct=document.getElementById('ct'), cc=document.getElementById('cc');
  if(!ci)return;
  const tot=pCart.reduce((s,i)=>s+i.qty*i.sell_price,0);
  if(ct) ct.innerHTML=`${tot.toLocaleString()} <span style="font-size:13px;">ر.س</span>`;
  if(cc){cc.textContent=pCart.length;cc.style.display=pCart.length?'inline-block':'none';}
  if(!pCart.length){ci.innerHTML='<div style="color:#475569;text-align:center;padding:28px;font-size:13px;">امسح منتجا لاضافته</div>';return;}
  ci.innerHTML=pCart.map(i=>`<div style="display:flex;align-items:center;gap:6px;padding:7px 0;border-bottom:1px solid #1e2537;">
    <div style="flex:1;overflow:hidden;">
      <div style="font-size:12px;font-weight:600;color:#f1f5f9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${i.name}</div>
      <div style="font-size:11px;color:#52b788;">${i.sell_price}×${i.qty}=${(i.sell_price*i.qty).toLocaleString()}</div>
    </div>
    <button class="btn s" style="padding:2px 7px;font-size:14px;" onclick="pCQ(${i.id},-1)">−</button>
    <span style="min-width:18px;text-align:center;font-weight:700;font-size:13px;">${i.qty}</span>
    <button class="btn s" style="padding:2px 7px;font-size:14px;" onclick="pCQ(${i.id},1)">+</button>
  </div>`).join('');
}
window.pCQ=function(id,d){
  const i=pCart.find(x=>x.id===id); if(!i)return;
  i.qty+=d; if(i.qty<=0) pCart=pCart.filter(x=>x.id!==id);
  renderCart();
};
async function posCheckout(){
  if(!pCart.length){alert('السلة فارغة');return;}
  const cust=document.getElementById('pc')?.value||null;
  const pay=document.getElementById('pm')?.value||'نقدي';
  try{
    const res=await api('POST','/api/sales',{
      customer_id:cust?+cust:null,
      date:new Date().toISOString().slice(0,10),
      status:pay==='آجل'?'معلق':'مدفوع',
      pay_method:pay, notes:'',
      items:pCart.map(i=>({product_id:i.id,qty:i.qty,price:i.sell_price}))
    });
    pCart=[]; await loadAll(); MS={type:'done',data:res}; render();
  }catch(e){alert(e.message);}
}

// ── GLOBAL ──────────────────────────────────────
window.openEdit=function(type,id){
  if(type==='products'){MS={type:'pform',data:products.find(p=>p.id===id)||{}};render();}
  else{const data=type==='suppliers'?suppliers:customers;MS={type:'eform',etype:type,data:data.find(x=>x.id===id)||{}};render();}
};
window.delItem=async function(type,id){
  if(!confirm('هل تريد الحذف؟'))return;
  try{await api('DELETE',`/api/${type}/${id}`);await loadAll();}catch(e){alert(e.message);}
};

// ── START ────────────────────────────────────────
render();
if(TOKEN){
  api('GET','/api/auth/me')
    .then(u=>{USER=u; loadAll();})
    .catch(()=>{TOKEN=null;localStorage.removeItem('token');render();});
}
</script>
</body>
</html>"""

# ══════════════════════════════════════════════
#  HTTP Server
# ══════════════════════════════════════════════
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type,Authorization")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/api/"):
            try:
                code, data = handle_api("GET", self.path, {}, self)
                self.send_json(code, data)
            except Exception as e:
                self.send_json(500, {"detail": str(e)})
        else:
            self.send_json(404, {"detail":"not found"})

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:    return json.loads(raw.decode("utf-8"))
        except: return {}

    def do_POST(self):
        try:
            code, data = handle_api("POST", self.path, self.read_body(), self)
            self.send_json(code, data)
        except Exception as e:
            self.send_json(500, {"detail": str(e)})

    def do_PUT(self):
        try:
            code, data = handle_api("PUT", self.path, self.read_body(), self)
            self.send_json(code, data)
        except Exception as e:
            self.send_json(500, {"detail": str(e)})

    def do_DELETE(self):
        try:
            code, data = handle_api("DELETE", self.path, {}, self)
            self.send_json(code, data)
        except Exception as e:
            self.send_json(500, {"detail": str(e)})

# ══════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 48)
    print("   نظام ادارة المخازن والمحاسبة")
    print("=" * 48)
    init_db()
    print(f"\n السيرفر يعمل على المنفذ: {PORT}")
    print(f" افتح المتصفح على: http://localhost:{PORT}")
    print(f"\n المستخدم:    admin")
    print(f" كلمة المرور: admin123")
    print(f"\n لايقاف البرنامج: اضغط Ctrl+C")
    print("=" * 48)

    # Railway deployment
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"✅ Server running on port {PORT}")
    
    def shutdown(sig, frame):
        print("\n⛔ Shutting down...")
        server.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    server.serve_forever()

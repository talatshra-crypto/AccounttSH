# -*- coding: utf-8 -*-
"""
نظام ادارة المخازن والمحاسبة
يعمل بـ Python فقط - بدون اي مكتبات خارجية
"""
import sqlite3, json, os, sys, hashlib, time, webbrowser, threading, signal, shutil, base64, secrets
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

PORT = int(os.environ.get('PORT', 8080))
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60  # صلاحية الجلسة: 12 ساعة
_base = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.path.dirname(os.path.abspath(__file__)))
DB_PATH      = os.path.join(_base, "inventory.db")
BACKUP_DIR   = os.path.join(_base, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

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
        role TEXT DEFAULT 'user',
        is_active INTEGER DEFAULT 1,
        salt TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        token TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
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
    CREATE TABLE IF NOT EXISTS sales(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER REFERENCES customers(id),
        date TEXT NOT NULL,
        total REAL DEFAULT 0,
        discount REAL DEFAULT 0,
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
        price REAL DEFAULT 0,
        discount REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS product_units(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
        serial TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'in_stock',
        purchase_id INTEGER,
        sale_id INTEGER,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
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
        cheque_status TEXT DEFAULT '',
        cheque_image TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        date TEXT NOT NULL,
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS expense_categories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        icon TEXT DEFAULT '📦',
        is_default INTEGER DEFAULT 0,
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS employees(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        position TEXT DEFAULT '',
        base_salary REAL DEFAULT 0,
        hire_date TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS salary_advances(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
        amount REAL NOT NULL,
        date TEXT NOT NULL,
        notes TEXT DEFAULT '',
        payroll_id INTEGER,
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS payroll(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL REFERENCES employees(id),
        month TEXT NOT NULL,
        base_salary REAL DEFAULT 0,
        total_advances REAL DEFAULT 0,
        adjustment REAL DEFAULT 0,
        adjustment_notes TEXT DEFAULT '',
        net_paid REAL DEFAULT 0,
        date_paid TEXT NOT NULL,
        payment_method TEXT DEFAULT 'نقدي',
        notes TEXT DEFAULT '',
        expense_id INTEGER,
        created_at TEXT DEFAULT(datetime('now')),
        UNIQUE(employee_id, month)
    );
    CREATE TABLE IF NOT EXISTS recurring_expenses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER REFERENCES expense_categories(id),
        description TEXT NOT NULL,
        amount REAL DEFAULT 0,
        day_of_month INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS expenses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER REFERENCES expense_categories(id),
        description TEXT NOT NULL,
        amount REAL NOT NULL,
        date TEXT NOT NULL,
        payment_method TEXT DEFAULT 'نقدي',
        cheque_no TEXT DEFAULT '',
        cheque_date TEXT DEFAULT '',
        cheque_bank TEXT DEFAULT '',
        cheque_image TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        employee_id INTEGER,
        payroll_id INTEGER,
        recurring_id INTEGER,
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS service_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER REFERENCES customers(id),
        service_type TEXT DEFAULT 'تركيب',
        device_desc TEXT DEFAULT '',
        product_id INTEGER REFERENCES products(id),
        issue_desc TEXT DEFAULT '',
        technician_id INTEGER REFERENCES employees(id),
        status TEXT DEFAULT 'قيد الانتظار',
        payment_status TEXT DEFAULT 'معلق',
        received_date TEXT NOT NULL,
        expected_date TEXT DEFAULT '',
        completed_date TEXT DEFAULT '',
        service_fee REAL DEFAULT 0,
        parts_cost REAL DEFAULT 0,
        warranty_days INTEGER DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT(datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS service_order_parts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_order_id INTEGER REFERENCES service_orders(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id),
        qty INTEGER DEFAULT 1,
        price REAL DEFAULT 0
    );
    """)
    # إضافة عمود الصورة إن لم يكن موجوداً (للقواعد القديمة)
    try:
        c.execute("ALTER TABLE payments ADD COLUMN cheque_image TEXT DEFAULT ''")
        c.commit()
    except: pass
    # إضافة عمود تتبع السيريال الفريد للمنتجات (للقواعد القديمة)
    try:
        c.execute("ALTER TABLE products ADD COLUMN track_serial INTEGER DEFAULT 0")
        c.commit()
    except: pass
    # إضافة عمود سبب المردود (للقواعد القديمة التي أُنشئت قبل توحيد الجدول)
    try:
        c.execute("ALTER TABLE purchase_returns ADD COLUMN reason TEXT DEFAULT ''")
        c.commit()
    except: pass
    # إضافة عمود تاريخ الصلاحية الاختياري للمنتجات
    try:
        c.execute("ALTER TABLE products ADD COLUMN expiry_date TEXT DEFAULT ''")
        c.commit()
    except: pass
    # إضافة عمود salt للمستخدمين (للتشفير الجديد)
    try:
        c.execute("ALTER TABLE users ADD COLUMN salt TEXT DEFAULT ''")
        c.commit()
    except: pass
    # إضافة أعمدة الخصم لفواتير البيع وأصنافها (للقواعد القديمة)
    try:
        c.execute("ALTER TABLE sales ADD COLUMN discount REAL DEFAULT 0")
        c.commit()
    except: pass
    try:
        c.execute("ALTER TABLE sale_items ADD COLUMN discount REAL DEFAULT 0")
        c.commit()
    except: pass
    if not row1(c.execute("SELECT id FROM users WHERE username='admin'")):
        c.execute("INSERT INTO users(username,password,full_name,role,is_active,salt) VALUES(?,?,?,?,?,?)",
                  ("admin", hashlib.sha256("admin123".encode()).hexdigest(), "المدير العام", "admin", 1, ""))
    # إعدادات افتراضية
    defaults = [
        ("currency", "₪"),
        ("currency_name", "شيكل"),
        ("system_name", "نظام ادارة المخازن"),
        ("low_stock_threshold", "20"),
        ("vip_customer_threshold", "5000"),
        ("overdue_days_threshold", "30"),
        ("supplier_payable_alert_threshold", "5000"),
    ]
    for k,v in defaults:
        if not row1(c.execute("SELECT key FROM settings WHERE key=?", (k,))):
            c.execute("INSERT INTO settings(key,value) VALUES(?,?)", (k,v))
    # تصنيفات مصاريف افتراضية (تُنشأ مرة واحدة فقط إن لم توجد أي تصنيفات بعد)
    if not row1(c.execute("SELECT id FROM expense_categories LIMIT 1")):
        default_categories = [
            ("رواتب وأجور", "👤"),
            ("وقود ومواصلات", "⛽"),
            ("صيانة وإصلاحات", "🔧"),
            ("ضرائب ورسوم", "🏛️"),
            ("إيجار", "🏠"),
            ("فواتير (كهرباء/ماء/انترنت)", "💡"),
            ("أخرى", "📦"),
        ]
        for name, icon in default_categories:
            c.execute("INSERT INTO expense_categories(name,icon,is_default) VALUES(?,?,1)", (name, icon))
    c.commit()
    c.close()
    print("قاعدة البيانات جاهزة")

def hash_password(password, salt=None):
    """تشفير كلمة المرور باستخدام pbkdf2_hmac مع salt عشوائي"""
    if salt is None:
        salt = secrets.token_hex(16)
    if isinstance(salt, str):
        salt = salt.encode()
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return salt.decode() if isinstance(salt, bytes) else salt, key.hex()

def verify_password(password, salt, stored_hash):
    """التحقق من كلمة المرور مع دعم التوافق العكسي لـ SHA256 القديم"""
    if salt and salt.strip():
        salt_bytes = salt.encode() if isinstance(salt, str) else salt
        key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt_bytes, 100000)
        return key.hex() == stored_hash
    else:
        return hashlib.sha256(password.encode()).hexdigest() == stored_hash

def check_auth(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "): return None
    token = auth[7:]
    c = get_db()
    u = row1(c.execute("""
        SELECT u.id, u.username, u.full_name, u.role, u.is_active, u.password, u.salt,
               s.created_at AS session_created_at
        FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?
    """, (token,)))
    if u:
        # انتهاء صلاحية الجلسة بعد 12 ساعة من إنشائها
        try:
            created = datetime.strptime(u["session_created_at"], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - created).total_seconds() > SESSION_MAX_AGE_SECONDS:
                c.execute("DELETE FROM sessions WHERE token=?", (token,))
                c.commit()
                c.close()
                return None
        except Exception:
            pass
    c.close()
    if u and not u.get("is_active", 1):
        return None
    return u

# ══════════════════════════════════════════════
#  DAO Classes (Data Access Objects)
# ══════════════════════════════════════════════
class BaseDAO:
    @staticmethod
    def rows(cur): return [dict(r) for r in cur.fetchall()]
    @staticmethod
    def row1(cur):
        r = cur.fetchone()
        return dict(r) if r else None

class UsersDAO(BaseDAO):
    @staticmethod
    def list(c):
        return BaseDAO.rows(c.execute("SELECT id,username,full_name,role,is_active,created_at FROM users ORDER BY id"))
    @staticmethod
    def get_by_id(c, uid):
        return BaseDAO.row1(c.execute("SELECT id,username,full_name,role,is_active,created_at FROM users WHERE id=?", (uid,)))
    @staticmethod
    def get_full(c, uid):
        return BaseDAO.row1(c.execute("SELECT * FROM users WHERE id=?", (uid,)))
    @staticmethod
    def get_by_username(c, uname):
        return BaseDAO.row1(c.execute("SELECT * FROM users WHERE username=?", (uname,)))
    @staticmethod
    def create(c, username, pw_hash, full_name, role, salt):
        cur = c.execute("INSERT INTO users(username,password,full_name,role,is_active,salt) VALUES(?,?,?,?,1,?)",
                        (username, pw_hash, full_name, role, salt))
        return cur.lastrowid
    @staticmethod
    def update(c, uid, full_name, role, is_active):
        c.execute("UPDATE users SET full_name=?,role=?,is_active=? WHERE id=?", (full_name, role, is_active, uid))
    @staticmethod
    def update_password(c, uid, pw_hash, salt):
        c.execute("UPDATE users SET password=?,salt=? WHERE id=?", (pw_hash, salt, uid))
    @staticmethod
    def update_with_password(c, uid, full_name, role, is_active, pw_hash, salt):
        c.execute("UPDATE users SET full_name=?,role=?,is_active=?,password=?,salt=? WHERE id=?",
                  (full_name, role, is_active, pw_hash, salt, uid))
    @staticmethod
    def delete(c, uid):
        c.execute("DELETE FROM users WHERE id=?", (uid,))
    @staticmethod
    def count_admins(c):
        return c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    @staticmethod
    def get_role(c, uid):
        return BaseDAO.row1(c.execute("SELECT role FROM users WHERE id=?", (uid,)))

class SessionsDAO(BaseDAO):
    @staticmethod
    def get_user_by_token(c, token):
        return BaseDAO.row1(c.execute("""
            SELECT u.id, u.username, u.full_name, u.role, u.is_active, u.password, u.salt
            FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?
        """, (token,)))
    @staticmethod
    def create(c, user_id, token):
        c.execute("INSERT INTO sessions(user_id,token) VALUES(?,?)", (user_id, token))
    @staticmethod
    def delete_by_user(c, user_id):
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    @staticmethod
    def delete_by_token(c, token):
        c.execute("DELETE FROM sessions WHERE token=?", (token,))

class SuppliersDAO(BaseDAO):
    @staticmethod
    def list(c):
        return BaseDAO.rows(c.execute("SELECT * FROM suppliers ORDER BY id DESC"))
    @staticmethod
    def get_by_id(c, sid):
        return BaseDAO.row1(c.execute("SELECT * FROM suppliers WHERE id=?", (sid,)))
    @staticmethod
    def create(c, data):
        cur = c.execute("INSERT INTO suppliers(name,contact,phone,email,city,balance,notes) VALUES(?,?,?,?,?,?,?)",
            (data.get("name",""), data.get("contact",""), data.get("phone",""),
             data.get("email",""), data.get("city",""), data.get("balance",0), data.get("notes","")))
        return cur.lastrowid
    @staticmethod
    def update(c, sid, data):
        c.execute("UPDATE suppliers SET name=?,contact=?,phone=?,email=?,city=?,balance=?,notes=? WHERE id=?",
            (data.get("name",""), data.get("contact",""), data.get("phone",""),
             data.get("email",""), data.get("city",""), data.get("balance",0), data.get("notes",""), sid))
    @staticmethod
    def delete(c, sid):
        c.execute("DELETE FROM suppliers WHERE id=?", (sid,))

class CustomersDAO(BaseDAO):
    @staticmethod
    def list(c):
        return BaseDAO.rows(c.execute("SELECT * FROM customers ORDER BY id DESC"))
    @staticmethod
    def get_by_id(c, cid):
        return BaseDAO.row1(c.execute("SELECT * FROM customers WHERE id=?", (cid,)))
    @staticmethod
    def create(c, data):
        cur = c.execute("INSERT INTO customers(name,contact,phone,email,city,balance,notes) VALUES(?,?,?,?,?,?,?)",
            (data.get("name",""), data.get("contact",""), data.get("phone",""),
             data.get("email",""), data.get("city",""), data.get("balance",0), data.get("notes","")))
        return cur.lastrowid
    @staticmethod
    def update(c, cid, data):
        c.execute("UPDATE customers SET name=?,contact=?,phone=?,email=?,city=?,balance=?,notes=? WHERE id=?",
            (data.get("name",""), data.get("contact",""), data.get("phone",""),
             data.get("email",""), data.get("city",""), data.get("balance",0), data.get("notes",""), cid))
    @staticmethod
    def delete(c, cid):
        c.execute("DELETE FROM customers WHERE id=?", (cid,))

class ProductsDAO(BaseDAO):
    @staticmethod
    def list(c):
        return BaseDAO.rows(c.execute("SELECT * FROM products ORDER BY id DESC"))
    @staticmethod
    def get_by_id(c, pid):
        return BaseDAO.row1(c.execute("SELECT * FROM products WHERE id=?", (pid,)))
    @staticmethod
    def get_by_barcode(c, code):
        return BaseDAO.row1(c.execute("SELECT * FROM products WHERE barcode=? OR serial=?", (code, code)))
    @staticmethod
    def search(c, q):
        return BaseDAO.rows(c.execute("SELECT * FROM products WHERE name LIKE ? OR barcode LIKE ? OR serial LIKE ?",
                                       (f"%{q}%", f"%{q}%", f"%{q}%")))
    @staticmethod
    def next_barcode(c):
        maxid = c.execute("SELECT COALESCE(MAX(id),0) FROM products").fetchone()[0]
        n = maxid + 1
        code = f"PRD-{n:06d}"
        while BaseDAO.row1(c.execute("SELECT id FROM products WHERE barcode=?", (code,))):
            n += 1; code = f"PRD-{n:06d}"
        return code
    @staticmethod
    def create(c, data):
        cur = c.execute(
            "INSERT INTO products(barcode,serial,name,category,unit,buy_price,sell_price,stock,supplier_id,track_serial,expiry_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (data.get("barcode",""), data.get("serial",""), data.get("name",""),
             data.get("category",""), data.get("unit","قطعة"), data.get("buy_price",0),
             data.get("sell_price",0), data.get("stock",0), data.get("supplier_id"),
             1 if data.get("track_serial") else 0, data.get("expiry_date","")))
        return cur.lastrowid
    @staticmethod
    def update(c, pid, data):
        c.execute(
            "UPDATE products SET barcode=?,serial=?,name=?,category=?,unit=?,buy_price=?,sell_price=?,stock=?,supplier_id=?,track_serial=?,expiry_date=? WHERE id=?",
            (data.get("barcode",""), data.get("serial",""), data.get("name",""),
             data.get("category",""), data.get("unit","قطعة"), data.get("buy_price",0),
             data.get("sell_price",0), data.get("stock",0), data.get("supplier_id"),
             1 if data.get("track_serial") else 0, data.get("expiry_date",""), pid))
    @staticmethod
    def delete(c, pid):
        c.execute("DELETE FROM products WHERE id=?", (pid,))
    @staticmethod
    def update_stock(c, pid, delta):
        if delta >= 0:
            c.execute("UPDATE products SET stock=stock+? WHERE id=?", (delta, pid))
        else:
            c.execute("UPDATE products SET stock=MAX(0,stock-?) WHERE id=?", (abs(delta), pid))

class ProductUnitsDAO(BaseDAO):
    @staticmethod
    def list(c, product_id=None, status=None):
        sql = "SELECT * FROM product_units WHERE 1=1"
        params = []
        if product_id: sql += " AND product_id=?"; params.append(int(product_id))
        if status:     sql += " AND status=?"; params.append(status)
        sql += " ORDER BY id DESC"
        return BaseDAO.rows(c.execute(sql, params))
    @staticmethod
    def get_by_serial(c, serial):
        return BaseDAO.row1(c.execute("SELECT * FROM product_units WHERE serial=?", (serial,)))
    @staticmethod
    def create(c, product_id, serial, status="in_stock", purchase_id=None):
        c.execute("INSERT INTO product_units(product_id,serial,status,purchase_id) VALUES(?,?,?,?)",
                  (product_id, serial, status, purchase_id))
    @staticmethod
    def delete(c, uid):
        c.execute("DELETE FROM product_units WHERE id=?", (uid,))
    @staticmethod
    def mark_sold(c, uid, sale_id):
        c.execute("UPDATE product_units SET status='sold', sale_id=? WHERE id=?", (sale_id, uid))
    @staticmethod
    def mark_in_stock(c, uid):
        c.execute("UPDATE product_units SET status='in_stock', sale_id=NULL WHERE id=?", (uid,))
    @staticmethod
    def mark_sold_by_serial(c, serial, product_id, sale_id):
        c.execute("UPDATE product_units SET status='sold', sale_id=? WHERE serial=? AND product_id=?",
                  (sale_id, serial, product_id))
    @staticmethod
    def unsold_by_sale(c, sale_id):
        c.execute("UPDATE product_units SET status='in_stock', sale_id=NULL WHERE sale_id=?", (sale_id,))
    @staticmethod
    def delete_by_purchase(c, pid, status="in_stock"):
        c.execute("DELETE FROM product_units WHERE purchase_id=? AND status=?", (pid, status))
    @staticmethod
    def unpin_purchase(c, pid):
        c.execute("UPDATE product_units SET purchase_id=NULL WHERE purchase_id=?", (pid,))

class PurchasesDAO(BaseDAO):
    @staticmethod
    def list(c):
        ps = BaseDAO.rows(c.execute("SELECT * FROM purchases ORDER BY id DESC"))
        for p in ps:
            p["items"] = PurchasesDAO.get_items(c, p["id"])
        return ps
    @staticmethod
    def get_by_id(c, pid):
        return BaseDAO.row1(c.execute("SELECT * FROM purchases WHERE id=?", (pid,)))
    @staticmethod
    def get_items(c, pid):
        return BaseDAO.rows(c.execute(
            "SELECT pi.*, pr.name as product_name, pr.barcode, pr.unit, pr.track_serial, "
            "(SELECT GROUP_CONCAT(pu.serial) FROM product_units pu WHERE pu.purchase_id=pi.purchase_id AND pu.product_id=pi.product_id) AS serials_str "
            "FROM purchase_items pi LEFT JOIN products pr ON pr.id=pi.product_id "
            "WHERE pi.purchase_id=?", (pid,)))
    @staticmethod
    def create(c, supplier_id, date, status, notes, total):
        cur = c.execute(
            "INSERT INTO purchases(supplier_id,date,status,notes,total) VALUES(?,?,?,?,?)",
            (supplier_id, date, status, notes, total))
        return cur.lastrowid
    @staticmethod
    def update(c, pid, supplier_id, date, status, notes, total):
        c.execute("UPDATE purchases SET supplier_id=?,date=?,status=?,notes=?,total=? WHERE id=?",
                  (supplier_id, date, status, notes, total, pid))
    @staticmethod
    def delete(c, pid):
        c.execute("DELETE FROM purchases WHERE id=?", (pid,))
    @staticmethod
    def create_item(c, pid, product_id, qty, price):
        c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,price) VALUES(?,?,?,?)",
                  (pid, product_id, qty, price))
    @staticmethod
    def delete_items(c, pid):
        c.execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))
    @staticmethod
    def get_supplier_id(c, pid):
        r = BaseDAO.row1(c.execute("SELECT supplier_id FROM purchases WHERE id=?", (pid,)))
        return r["supplier_id"] if r else None

class SalesDAO(BaseDAO):
    @staticmethod
    def list(c):
        ss = BaseDAO.rows(c.execute("SELECT * FROM sales ORDER BY id DESC"))
        for s in ss:
            s["items"] = SalesDAO.get_items(c, s["id"])
        return ss
    @staticmethod
    def get_by_id(c, sid):
        s = BaseDAO.row1(c.execute("SELECT * FROM sales WHERE id=?", (sid,)))
        if s:
            s["items"] = SalesDAO.get_items(c, sid)
        return s
    @staticmethod
    def get_items(c, sid):
        return BaseDAO.rows(c.execute(
            "SELECT si.*, pr.name as product_name, pr.barcode, pr.unit, pr.track_serial, "
            "(SELECT GROUP_CONCAT(pu.serial) FROM product_units pu WHERE pu.sale_id=si.sale_id AND pu.product_id=si.product_id) AS serials_str "
            "FROM sale_items si LEFT JOIN products pr ON pr.id=si.product_id "
            "WHERE si.sale_id=?", (sid,)))
    @staticmethod
    def create(c, customer_id, date, status, pay_method, notes, total, discount=0):
        cur = c.execute(
            "INSERT INTO sales(customer_id,date,status,pay_method,notes,total,discount) VALUES(?,?,?,?,?,?,?)",
            (customer_id, date, status, pay_method, notes, total, discount))
        return cur.lastrowid
    @staticmethod
    def update(c, sid, customer_id, date, status, pay_method, notes, total, discount=0):
        c.execute("UPDATE sales SET customer_id=?,date=?,status=?,pay_method=?,notes=?,total=?,discount=? WHERE id=?",
                  (customer_id, date, status, pay_method, notes, total, discount, sid))
    @staticmethod
    def delete(c, sid):
        c.execute("DELETE FROM sales WHERE id=?", (sid,))
    @staticmethod
    def create_item(c, sid, product_id, qty, price, discount=0):
        c.execute("INSERT INTO sale_items(sale_id,product_id,qty,price,discount) VALUES(?,?,?,?,?)",
                  (sid, product_id, qty, price, discount))
    @staticmethod
    def delete_items(c, sid):
        c.execute("DELETE FROM sale_items WHERE sale_id=?", (sid,))
    @staticmethod
    def get_old_items(c, sid):
        return BaseDAO.rows(c.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)))

class PurchaseReturnsDAO(BaseDAO):
    @staticmethod
    def list(c):
        rs = BaseDAO.rows(c.execute("SELECT * FROM purchase_returns ORDER BY id DESC"))
        for r in rs:
            r["items"] = BaseDAO.rows(c.execute(
                "SELECT pri.*, pr.name as product_name, pr.barcode, pr.unit "
                "FROM purchase_return_items pri LEFT JOIN products pr ON pr.id=pri.product_id "
                "WHERE pri.return_id=?", (r["id"],)))
        return rs
    @staticmethod
    def create(c, purchase_id, supplier_id, date, total, reason, notes):
        cur = c.execute(
            "INSERT INTO purchase_returns(purchase_id,supplier_id,date,total,reason,notes) VALUES(?,?,?,?,?,?)",
            (purchase_id, supplier_id, date, total, reason, notes))
        return cur.lastrowid
    @staticmethod
    def create_item(c, rid, product_id, qty, price):
        c.execute("INSERT INTO purchase_return_items(return_id,product_id,qty,price) VALUES(?,?,?,?)",
                  (rid, product_id, qty, price))

class PaymentsDAO(BaseDAO):
    @staticmethod
    def get_by_ref(c, ref_type, ref_id):
        return BaseDAO.rows(c.execute(
            "SELECT * FROM payments WHERE ref_type=? AND ref_id=? ORDER BY date DESC",
            (ref_type, int(ref_id))))
    @staticmethod
    def get_by_party(c, party_type, party_id):
        return BaseDAO.rows(c.execute(
            "SELECT * FROM payments WHERE party_type=? AND party_id=? ORDER BY date DESC",
            (party_type, int(party_id))))
    @staticmethod
    def list_recent(c, limit=100):
        return BaseDAO.rows(c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT ?", (limit,)))
    @staticmethod
    def get_by_id(c, pid):
        return BaseDAO.row1(c.execute("SELECT * FROM payments WHERE id=?", (pid,)))
    @staticmethod
    def create(c, ref_type, ref_id, party_type, party_id, amount, method, date,
               cheque_no="", cheque_date="", cheque_bank="", cheque_image="", notes=""):
        cheque_status = "قيد التحصيل" if method == "شيك" else ""
        cur = c.execute(
            "INSERT INTO payments(ref_type,ref_id,party_type,party_id,amount,method,cheque_no,cheque_date,cheque_bank,cheque_status,cheque_image,notes,date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ref_type, int(ref_id), party_type, int(party_id), amount, method,
             cheque_no, cheque_date, cheque_bank, cheque_status,
             cheque_image, notes, date))
        return cur.lastrowid
    @staticmethod
    def update(c, pid, amount=None, method=None, date=None, notes=None,
               cheque_no=None, cheque_date=None, cheque_bank=None, cheque_image=None,
               cheque_status=None):
        old = PaymentsDAO.get_by_id(c, pid)
        if not old: return None
        amount   = float(amount) if amount is not None else old["amount"]
        method_v = method or old["method"]
        date_v   = date or old["date"]
        notes_v  = notes if notes is not None else old["notes"]
        cheq_no  = cheque_no if cheque_no is not None else old["cheque_no"]
        cheq_dt  = cheque_date if cheque_date is not None else old["cheque_date"]
        cheq_bk  = cheque_bank if cheque_bank is not None else old["cheque_bank"]
        cheq_img = cheque_image if cheque_image is not None else old.get("cheque_image", "")
        cheq_st  = cheque_status if cheque_status is not None else old.get("cheque_status", "")
        c.execute(
            "UPDATE payments SET amount=?,method=?,date=?,notes=?,cheque_no=?,cheque_date=?,cheque_bank=?,cheque_image=?,cheque_status=? WHERE id=?",
            (amount, method_v, date_v, notes_v, cheq_no, cheq_dt, cheq_bk, cheq_img, cheq_st, pid))
        return old
    @staticmethod
    def delete(c, pid):
        c.execute("DELETE FROM payments WHERE id=?", (pid,))
    @staticmethod
    def total_by_ref(c, ref_type, ref_id):
        return c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE ref_type=? AND ref_id=?",
                         (ref_type, ref_id)).fetchone()[0]
    @staticmethod
    def total_by_party_account(c, party_type, party_id):
        return c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE ref_type='account' AND party_type=? AND party_id=?",
                         (party_type, party_id)).fetchone()[0]
    @staticmethod
    def update_invoice_status(c, ref_type, ref_id):
        if ref_type not in ("purchase", "sale", "service"): return
        table = "purchases" if ref_type == "purchase" else "sales" if ref_type == "sale" else "service_orders"
        status_col = "status" if ref_type in ("purchase","sale") else "payment_status"
        inv = BaseDAO.row1(c.execute(f"SELECT * FROM {table} WHERE id=?", (ref_id,)))
        if not inv: return
        paid = PaymentsDAO.total_by_ref(c, ref_type, ref_id)
        inv_total = abs(inv["total"] if ref_type!="service" else inv["service_fee"])
        if paid >= inv_total and inv_total > 0:
            new_status = "مدفوع"
        elif paid > 0:
            new_status = "مدفوع جزئياً"
        else:
            new_status = "معلق"
        c.execute(f"UPDATE {table} SET {status_col}=? WHERE id=?", (new_status, ref_id))

class ExpenseCategoriesDAO(BaseDAO):
    @staticmethod
    def list(c):
        return BaseDAO.rows(c.execute("SELECT * FROM expense_categories ORDER BY is_default DESC, id"))
    @staticmethod
    def get_by_id(c, cid):
        return BaseDAO.row1(c.execute("SELECT * FROM expense_categories WHERE id=?", (cid,)))
    @staticmethod
    def get_by_name(c, name):
        return BaseDAO.row1(c.execute("SELECT * FROM expense_categories WHERE name=?", (name,)))
    @staticmethod
    def create(c, name, icon="📦"):
        cur = c.execute("INSERT INTO expense_categories(name,icon) VALUES(?,?)", (name, icon))
        return cur.lastrowid
    @staticmethod
    def update(c, cid, name, icon):
        c.execute("UPDATE expense_categories SET name=?,icon=? WHERE id=?", (name, icon, cid))
    @staticmethod
    def delete(c, cid):
        c.execute("DELETE FROM expense_categories WHERE id=?", (cid,))

class ExpensesDAO(BaseDAO):
    @staticmethod
    def list(c, date_from=None, date_to=None, category_id=None):
        sql = """SELECT e.*, ec.name AS category_name, ec.icon AS category_icon
                 FROM expenses e LEFT JOIN expense_categories ec ON ec.id=e.category_id WHERE 1=1"""
        params = []
        if date_from: sql += " AND e.date>=?"; params.append(date_from)
        if date_to:   sql += " AND e.date<=?"; params.append(date_to)
        if category_id: sql += " AND e.category_id=?"; params.append(category_id)
        sql += " ORDER BY e.date DESC, e.id DESC"
        return BaseDAO.rows(c.execute(sql, params))
    @staticmethod
    def get_by_id(c, eid):
        return BaseDAO.row1(c.execute("SELECT * FROM expenses WHERE id=?", (eid,)))
    @staticmethod
    def create(c, data):
        cur = c.execute(
            "INSERT INTO expenses(category_id,description,amount,date,payment_method,cheque_no,cheque_date,cheque_bank,cheque_image,notes,employee_id,payroll_id,recurring_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.get("category_id"), data.get("description",""), float(data.get("amount",0) or 0),
             data.get("date",""), data.get("payment_method","نقدي"), data.get("cheque_no",""),
             data.get("cheque_date",""), data.get("cheque_bank",""), data.get("cheque_image",""),
             data.get("notes",""), data.get("employee_id"), data.get("payroll_id"), data.get("recurring_id")))
        return cur.lastrowid
    @staticmethod
    def update(c, eid, data):
        c.execute(
            "UPDATE expenses SET category_id=?,description=?,amount=?,date=?,payment_method=?,cheque_no=?,cheque_date=?,cheque_bank=?,cheque_image=?,notes=? WHERE id=?",
            (data.get("category_id"), data.get("description",""), float(data.get("amount",0) or 0),
             data.get("date",""), data.get("payment_method","نقدي"), data.get("cheque_no",""),
             data.get("cheque_date",""), data.get("cheque_bank",""), data.get("cheque_image",""),
             data.get("notes",""), eid))
    @staticmethod
    def delete(c, eid):
        c.execute("DELETE FROM expenses WHERE id=?", (eid,))
    @staticmethod
    def total_between(c, date_from=None, date_to=None):
        sql = "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE 1=1"
        params = []
        if date_from: sql += " AND date>=?"; params.append(date_from)
        if date_to:   sql += " AND date<=?"; params.append(date_to)
        return c.execute(sql, params).fetchone()[0]

class EmployeesDAO(BaseDAO):
    @staticmethod
    def list(c):
        return BaseDAO.rows(c.execute("SELECT * FROM employees ORDER BY is_active DESC, id DESC"))
    @staticmethod
    def get_by_id(c, eid):
        return BaseDAO.row1(c.execute("SELECT * FROM employees WHERE id=?", (eid,)))
    @staticmethod
    def create(c, data):
        cur = c.execute(
            "INSERT INTO employees(name,phone,position,base_salary,hire_date,is_active,notes) VALUES(?,?,?,?,?,?,?)",
            (data.get("name",""), data.get("phone",""), data.get("position",""),
             float(data.get("base_salary",0) or 0), data.get("hire_date",""),
             1 if data.get("is_active",1) else 0, data.get("notes","")))
        return cur.lastrowid
    @staticmethod
    def update(c, eid, data):
        c.execute(
            "UPDATE employees SET name=?,phone=?,position=?,base_salary=?,hire_date=?,is_active=?,notes=? WHERE id=?",
            (data.get("name",""), data.get("phone",""), data.get("position",""),
             float(data.get("base_salary",0) or 0), data.get("hire_date",""),
             1 if data.get("is_active",1) else 0, data.get("notes",""), eid))
    @staticmethod
    def delete(c, eid):
        c.execute("DELETE FROM employees WHERE id=?", (eid,))

class SalaryAdvancesDAO(BaseDAO):
    @staticmethod
    def list_by_employee(c, employee_id):
        return BaseDAO.rows(c.execute("SELECT * FROM salary_advances WHERE employee_id=? ORDER BY date DESC, id DESC", (employee_id,)))
    @staticmethod
    def list_unconsumed(c, employee_id):
        return BaseDAO.rows(c.execute("SELECT * FROM salary_advances WHERE employee_id=? AND payroll_id IS NULL ORDER BY date", (employee_id,)))
    @staticmethod
    def create(c, employee_id, amount, date, notes=""):
        cur = c.execute("INSERT INTO salary_advances(employee_id,amount,date,notes) VALUES(?,?,?,?)",
                        (employee_id, float(amount), date, notes))
        return cur.lastrowid
    @staticmethod
    def delete(c, aid):
        c.execute("DELETE FROM salary_advances WHERE id=?", (aid,))
    @staticmethod
    def mark_consumed(c, ids, payroll_id):
        for aid in ids:
            c.execute("UPDATE salary_advances SET payroll_id=? WHERE id=?", (payroll_id, aid))
    @staticmethod
    def unmark_by_payroll(c, payroll_id):
        c.execute("UPDATE salary_advances SET payroll_id=NULL WHERE payroll_id=?", (payroll_id,))

class PayrollDAO(BaseDAO):
    @staticmethod
    def list(c, employee_id=None):
        sql = "SELECT p.*, e.name AS employee_name FROM payroll p LEFT JOIN employees e ON e.id=p.employee_id WHERE 1=1"
        params = []
        if employee_id: sql += " AND p.employee_id=?"; params.append(employee_id)
        sql += " ORDER BY p.month DESC, p.id DESC"
        return BaseDAO.rows(c.execute(sql, params))
    @staticmethod
    def get_by_id(c, pid):
        return BaseDAO.row1(c.execute("SELECT * FROM payroll WHERE id=?", (pid,)))
    @staticmethod
    def get_by_employee_month(c, employee_id, month):
        return BaseDAO.row1(c.execute("SELECT * FROM payroll WHERE employee_id=? AND month=?", (employee_id, month)))
    @staticmethod
    def create(c, employee_id, month, base_salary, total_advances, adjustment, adjustment_notes,
               net_paid, date_paid, payment_method, notes, expense_id):
        cur = c.execute(
            "INSERT INTO payroll(employee_id,month,base_salary,total_advances,adjustment,adjustment_notes,net_paid,date_paid,payment_method,notes,expense_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (employee_id, month, base_salary, total_advances, adjustment, adjustment_notes,
             net_paid, date_paid, payment_method, notes, expense_id))
        return cur.lastrowid
    @staticmethod
    def delete(c, pid):
        c.execute("DELETE FROM payroll WHERE id=?", (pid,))

class RecurringExpensesDAO(BaseDAO):
    @staticmethod
    def list(c):
        return BaseDAO.rows(c.execute(
            "SELECT r.*, ec.name AS category_name, ec.icon AS category_icon "
            "FROM recurring_expenses r LEFT JOIN expense_categories ec ON ec.id=r.category_id "
            "ORDER BY r.is_active DESC, r.id DESC"))
    @staticmethod
    def get_by_id(c, rid):
        return BaseDAO.row1(c.execute("SELECT * FROM recurring_expenses WHERE id=?", (rid,)))
    @staticmethod
    def create(c, data):
        cur = c.execute(
            "INSERT INTO recurring_expenses(category_id,description,amount,day_of_month,is_active,notes) VALUES(?,?,?,?,?,?)",
            (data.get("category_id"), data.get("description",""), float(data.get("amount",0) or 0),
             int(data.get("day_of_month",1) or 1), 1 if data.get("is_active",1) else 0, data.get("notes","")))
        return cur.lastrowid
    @staticmethod
    def update(c, rid, data):
        c.execute(
            "UPDATE recurring_expenses SET category_id=?,description=?,amount=?,day_of_month=?,is_active=?,notes=? WHERE id=?",
            (data.get("category_id"), data.get("description",""), float(data.get("amount",0) or 0),
             int(data.get("day_of_month",1) or 1), 1 if data.get("is_active",1) else 0, data.get("notes",""), rid))
    @staticmethod
    def delete(c, rid):
        c.execute("DELETE FROM recurring_expenses WHERE id=?", (rid,))
    @staticmethod
    def paid_this_month(c, recurring_id, month):
        return BaseDAO.row1(c.execute(
            "SELECT id FROM expenses WHERE recurring_id=? AND substr(date,1,7)=?", (recurring_id, month)))

class ServiceOrdersDAO(BaseDAO):
    @staticmethod
    def list(c):
        rows_s = BaseDAO.rows(c.execute(
            "SELECT so.*, c.name AS customer_name, c.phone AS customer_phone, "
            "e.name AS technician_name, pr.name AS product_name "
            "FROM service_orders so "
            "LEFT JOIN customers c ON c.id=so.customer_id "
            "LEFT JOIN employees e ON e.id=so.technician_id "
            "LEFT JOIN products pr ON pr.id=so.product_id "
            "ORDER BY so.id DESC"))
        for r in rows_s:
            r["parts"] = ServiceOrdersDAO.get_parts(c, r["id"])
        return rows_s
    @staticmethod
    def get_by_id(c, sid):
        r = BaseDAO.row1(c.execute(
            "SELECT so.*, c.name AS customer_name, c.phone AS customer_phone, "
            "e.name AS technician_name, pr.name AS product_name "
            "FROM service_orders so "
            "LEFT JOIN customers c ON c.id=so.customer_id "
            "LEFT JOIN employees e ON e.id=so.technician_id "
            "LEFT JOIN products pr ON pr.id=so.product_id "
            "WHERE so.id=?", (sid,)))
        if r: r["parts"] = ServiceOrdersDAO.get_parts(c, sid)
        return r
    @staticmethod
    def get_parts(c, sid):
        return BaseDAO.rows(c.execute(
            "SELECT sop.*, p.name AS product_name, p.barcode, p.unit "
            "FROM service_order_parts sop LEFT JOIN products p ON p.id=sop.product_id "
            "WHERE sop.service_order_id=?", (sid,)))
    @staticmethod
    def create(c, data):
        cur = c.execute(
            "INSERT INTO service_orders(customer_id,service_type,device_desc,product_id,issue_desc,"
            "technician_id,status,received_date,expected_date,service_fee,warranty_days,notes) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.get("customer_id"), data.get("service_type","تركيب"), data.get("device_desc",""),
             data.get("product_id"), data.get("issue_desc",""), data.get("technician_id"),
             data.get("status","قيد الانتظار"), data.get("received_date",""), data.get("expected_date",""),
             float(data.get("service_fee",0) or 0), int(data.get("warranty_days",0) or 0), data.get("notes","")))
        return cur.lastrowid
    @staticmethod
    def update(c, sid, data):
        c.execute(
            "UPDATE service_orders SET customer_id=?,service_type=?,device_desc=?,product_id=?,issue_desc=?,"
            "technician_id=?,status=?,received_date=?,expected_date=?,completed_date=?,service_fee=?,"
            "parts_cost=?,warranty_days=?,notes=? WHERE id=?",
            (data.get("customer_id"), data.get("service_type","تركيب"), data.get("device_desc",""),
             data.get("product_id"), data.get("issue_desc",""), data.get("technician_id"),
             data.get("status","قيد الانتظار"), data.get("received_date",""), data.get("expected_date",""),
             data.get("completed_date",""), float(data.get("service_fee",0) or 0),
             float(data.get("parts_cost",0) or 0), int(data.get("warranty_days",0) or 0),
             data.get("notes",""), sid))
    @staticmethod
    def delete(c, sid):
        c.execute("DELETE FROM service_orders WHERE id=?", (sid,))
    @staticmethod
    def add_part(c, sid, product_id, qty, price):
        c.execute("INSERT INTO service_order_parts(service_order_id,product_id,qty,price) VALUES(?,?,?,?)",
                  (sid, product_id, qty, price))
    @staticmethod
    def delete_parts(c, sid):
        c.execute("DELETE FROM service_order_parts WHERE service_order_id=?", (sid,))
    @staticmethod
    def set_parts_cost(c, sid, cost):
        c.execute("UPDATE service_orders SET parts_cost=? WHERE id=?", (cost, sid))

class SettingsDAO(BaseDAO):
    @staticmethod
    def get_all(c):
        rows_s = BaseDAO.rows(c.execute("SELECT key,value FROM settings"))
        return {r["key"]: r["value"] for r in rows_s}
    @staticmethod
    def set(c, key, value):
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (str(key), str(value)))
    @staticmethod
    def set_many(c, items):
        for k, v in items.items():
            SettingsDAO.set(c, k, v)

class DashboardDAO(BaseDAO):
    @staticmethod
    def stats(c):
        try:
            threshold = int(float(SettingsDAO.get_all(c).get("low_stock_threshold", 20)))
        except (TypeError, ValueError):
            threshold = 20
        ts = c.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
        tp = c.execute("SELECT COALESCE(SUM(total),0) FROM purchases").fetchone()[0]
        te = ExpensesDAO.total_between(c)
        tsf = c.execute("SELECT COALESCE(SUM(service_fee),0) FROM service_orders").fetchone()[0]
        tspc = c.execute("SELECT COALESCE(SUM(parts_cost),0) FROM service_orders").fetchone()[0]
        lw = c.execute("SELECT COUNT(*) FROM products WHERE stock<?", (threshold,)).fetchone()[0]
        rs = BaseDAO.rows(c.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 6"))
        lp = BaseDAO.rows(c.execute("SELECT * FROM products WHERE stock<? ORDER BY stock LIMIT 7", (threshold,)))
        return {"total_sales": ts, "total_purchases": tp, "total_expenses": te,
                "total_services": tsf, "total_services_cost": tspc,
                "profit": ts - tp - te + tsf - tspc,
                "low_stock_count": lw, "recent_sales": rs, "low_products": lp}

class BackupDAO(BaseDAO):
    @staticmethod
    def list(c):
        files = []
        for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if f.endswith(".db"):
                fp = os.path.join(BACKUP_DIR, f)
                size = os.path.getsize(fp)
                files.append({"name": f, "size": size, "size_kb": round(size/1024, 1),
                              "date": datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")})
        return files
    @staticmethod
    def create():
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"backup_{now}.db"
        fpath = os.path.join(BACKUP_DIR, fname)
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(fpath)
        src.backup(dst); dst.close(); src.close()
        size = os.path.getsize(fpath)
        with open(fpath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        # حذف النسخ القديمة إن تجاوزت 10
        all_bk = sorted([x for x in os.listdir(BACKUP_DIR) if x.endswith(".db")])
        while len(all_bk) > 10:
            try: os.remove(os.path.join(BACKUP_DIR, all_bk.pop(0)))
            except: pass
        return {"name": fname, "size_kb": round(size/1024, 1),
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "data": b64}
    @staticmethod
    def download(fname):
        fname = os.path.basename(fname)
        fpath = os.path.join(BACKUP_DIR, fname)
        if not os.path.exists(fpath): return None
        size = os.path.getsize(fpath)
        with open(fpath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return {"name": fname, "size_kb": round(size/1024, 1), "data": b64}
    @staticmethod
    def delete(fname):
        fname = os.path.basename(fname)
        if not fname.endswith(".db"): return False
        fpath = os.path.join(BACKUP_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
        return True
    @staticmethod
    def restore_from_file(fname):
        fname = os.path.basename(fname)
        fpath = os.path.join(BACKUP_DIR, fname)
        if not os.path.exists(fpath): return None
        # نسخة احتياطية تلقائية قبل الاستعادة
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        auto = os.path.join(BACKUP_DIR, f"before_restore_{now}.db")
        src_c = sqlite3.connect(DB_PATH)
        dst_c = sqlite3.connect(auto)
        src_c.backup(dst_c); dst_c.close(); src_c.close()
        # تطبيق الاستعادة
        src_c = sqlite3.connect(fpath)
        dst_c = sqlite3.connect(DB_PATH)
        src_c.backup(dst_c); dst_c.close(); src_c.close()
        return os.path.basename(auto)
    @staticmethod
    def restore_from_data(b64_data):
        try:
            db_bytes = base64.b64decode(b64_data)
        except Exception:
            return None
        tmp = os.path.join(BACKUP_DIR, "_tmp_restore.db")
        with open(tmp, "wb") as f: f.write(db_bytes)
        try:
            chk = sqlite3.connect(tmp)
            chk.execute("SELECT name FROM sqlite_master LIMIT 1")
            chk.close()
        except Exception:
            try: os.remove(tmp)
            except: pass
            return None
        # نسخة احتياطية تلقائية
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        auto = os.path.join(BACKUP_DIR, f"before_restore_{now}.db")
        src_c = sqlite3.connect(DB_PATH)
        dst_c = sqlite3.connect(auto)
        src_c.backup(dst_c); dst_c.close(); src_c.close()
        # تطبيق الاستعادة
        src_c = sqlite3.connect(tmp)
        dst_c = sqlite3.connect(DB_PATH)
        src_c.backup(dst_c); dst_c.close(); src_c.close()
        try: os.remove(tmp)
        except: pass
        return os.path.basename(auto)

class ReportsDAO(BaseDAO):
    @staticmethod
    def supplier_report(c, sup_id, date_from, date_to):
        sup = SuppliersDAO.get_by_id(c, sup_id)
        if not sup: return None
        ps = BaseDAO.rows(c.execute(
            "SELECT * FROM purchases WHERE (CAST(supplier_id AS INTEGER)=? OR supplier_id=?) AND date>=? AND date<=? ORDER BY date",
            (sup_id, str(sup_id), date_from, date_to)))
        for p in ps:
            p["items"] = PurchasesDAO.get_items(c, p["id"])
            p["payments"] = PaymentsDAO.get_by_ref(c, "purchase", p["id"])
            p["paid"] = sum(pay["amount"] for pay in p["payments"])
            p["remaining"] = max(0, abs(p["total"]) - p["paid"])
        total_sup = sum(p["total"] for p in ps)
        total_paid = sum(p["paid"] for p in ps)
        total_remain_inv = sum(p["remaining"] for p in ps)
        account_paid = PaymentsDAO.total_by_party_account(c, "supplier", sup_id)
        total_paid_final = total_paid + account_paid
        total_remain = max(0, total_remain_inv - account_paid)
        all_payments = PaymentsDAO.get_by_party(c, "supplier", sup_id)
        return {"supplier": sup, "purchases": ps, "total": total_sup,
                "total_paid": total_paid_final, "total_remaining": total_remain,
                "account_paid": account_paid, "all_payments": all_payments,
                "date_from": date_from, "date_to": date_to, "count": len(ps)}

    @staticmethod
    def customer_report(c, cust_id, date_from, date_to):
        cust = CustomersDAO.get_by_id(c, cust_id)
        if not cust: return None
        ss = BaseDAO.rows(c.execute(
            "SELECT * FROM sales WHERE CAST(customer_id AS INTEGER)=? AND date>=? AND date<=? ORDER BY date",
            (cust_id, date_from, date_to)))
        for s in ss:
            s["items"] = SalesDAO.get_items(c, s["id"])
            s["payments"] = PaymentsDAO.get_by_ref(c, "sale", s["id"])
            s["paid"] = sum(pay["amount"] for pay in s["payments"])
            s["remaining"] = max(0, abs(s["total"]) - s["paid"])
        sos = BaseDAO.rows(c.execute(
            "SELECT * FROM service_orders WHERE CAST(customer_id AS INTEGER)=? AND received_date>=? AND received_date<=? ORDER BY received_date",
            (cust_id, date_from, date_to)))
        for so in sos:
            so["parts"] = ServiceOrdersDAO.get_parts(c, so["id"])
            so["payments"] = PaymentsDAO.get_by_ref(c, "service", so["id"])
            so["paid"] = sum(pay["amount"] for pay in so["payments"])
            so["remaining"] = max(0, abs(so["service_fee"]) - so["paid"])
        # قائمة موحدة تجمع فواتير البيع وطلبات الخدمة مرتبة زمنياً — بدل عرضهم منفصلين
        transactions = []
        for s in ss:
            transactions.append({
                "kind": "sale", "id": s["id"], "date": s["date"], "total": s["total"],
                "paid": s["paid"], "remaining": s["remaining"], "status": s["status"],
                "pay_method": s.get("pay_method",""), "items": s["items"], "payments": s["payments"],
                "notes": s.get("notes",""),
            })
        for so in sos:
            transactions.append({
                "kind": "service", "id": so["id"], "date": so["received_date"], "total": so["service_fee"],
                "paid": so["paid"], "remaining": so["remaining"], "status": so["payment_status"],
                "workflow_status": so["status"], "service_type": so["service_type"],
                "device_desc": so["device_desc"], "parts": so["parts"], "payments": so["payments"],
                "notes": so.get("notes",""),
            })
        transactions.sort(key=lambda t: (t["date"] or "", t["kind"]))
        total_s = sum(s["total"] for s in ss) + sum(so["service_fee"] for so in sos)
        total_paid = sum(s["paid"] for s in ss) + sum(so["paid"] for so in sos)
        total_remain_inv = sum(s["remaining"] for s in ss) + sum(so["remaining"] for so in sos)
        account_paid = PaymentsDAO.total_by_party_account(c, "customer", cust_id)
        total_paid_final = total_paid + account_paid
        total_remain = max(0, total_remain_inv - account_paid)
        all_payments = PaymentsDAO.get_by_party(c, "customer", cust_id)
        return {"customer": cust, "sales": ss, "services": sos, "transactions": transactions, "total": total_s,
                "total_paid": total_paid_final, "total_remaining": total_remain,
                "account_paid": account_paid, "all_payments": all_payments,
                "date_from": date_from, "date_to": date_to, "count": len(transactions)}

    @staticmethod
    def cheques_report(c, direction, status, date_from, date_to):
        if not date_from: date_from = "2000-01-01"
        if not date_to:   date_to   = "2099-12-31"
        conds = ["method='شيك'", "cheque_no!=''", "cheque_date>=?", "cheque_date<=?"]
        params = [date_from, date_to]
        if direction == "outgoing":
            conds.append("party_type='supplier'")
        elif direction == "incoming":
            conds.append("party_type='customer'")
        if status != "all":
            conds.append("(cheque_status=? OR (cheque_status='' AND ?='pending'))")
            params += [status, status]
        sql = "SELECT * FROM payments WHERE " + " AND ".join(conds) + " ORDER BY cheque_date"
        pays = BaseDAO.rows(c.execute(sql, params))
        for p in pays:
            if p["party_type"] == "supplier":
                sup = SuppliersDAO.get_by_id(c, p["party_id"])
                p["party_name"] = sup["name"] if sup else "—"
                p["party_phone"] = sup["phone"] if sup else ""
                p["direction"] = "صادر"
            else:
                cust = CustomersDAO.get_by_id(c, p["party_id"])
                p["party_name"] = cust["name"] if cust else "—"
                p["party_phone"] = cust["phone"] if cust else ""
                p["direction"] = "وارد"
            p["cheque_status"] = p["cheque_status"] or "قيد التحصيل"
        total_out = sum(p["amount"] for p in pays if p["party_type"] == "supplier")
        total_in = sum(p["amount"] for p in pays if p["party_type"] == "customer")
        return {"cheques": pays, "total_outgoing": total_out,
                "total_incoming": total_in, "count": len(pays),
                "date_from": date_from, "date_to": date_to}

    @staticmethod
    def payments_summary(c, party_type, party_id):
        result = []
        total_inv = 0; total_paid_invoices = 0
        if party_type == "supplier":
            invs = BaseDAO.rows(c.execute(
                "SELECT * FROM purchases WHERE CAST(supplier_id AS INTEGER)=? AND status!='مردود'", (party_id,)))
            for inv in invs:
                paid = PaymentsDAO.total_by_ref(c, "purchase", inv["id"])
                remaining = abs(inv["total"]) - paid
                total_inv += abs(inv["total"]); total_paid_invoices += paid
                result.append({**inv, "paid": paid, "remaining": remaining, "ref_type": "purchase"})
        else:
            invs = BaseDAO.rows(c.execute(
                "SELECT * FROM sales WHERE CAST(customer_id AS INTEGER)=?", (party_id,)))
            for inv in invs:
                paid = PaymentsDAO.total_by_ref(c, "sale", inv["id"])
                remaining = abs(inv["total"]) - paid
                total_inv += abs(inv["total"]); total_paid_invoices += paid
                result.append({**inv, "paid": paid, "remaining": remaining, "ref_type": "sale"})
            svcs = BaseDAO.rows(c.execute(
                "SELECT * FROM service_orders WHERE CAST(customer_id AS INTEGER)=?", (party_id,)))
            for so in svcs:
                paid = PaymentsDAO.total_by_ref(c, "service", so["id"])
                fee = abs(so["service_fee"])
                remaining = fee - paid
                total_inv += fee; total_paid_invoices += paid
                result.append({**so, "total": fee, "date": so["received_date"], "status": so["payment_status"],
                                "paid": paid, "remaining": remaining, "ref_type": "service"})
            result.sort(key=lambda x: x.get("date") or "")
        account_paid = PaymentsDAO.total_by_party_account(c, party_type, party_id)
        total_paid = total_paid_invoices + account_paid
        return {"invoices": result, "total_invoices": total_inv,
                "total_paid": total_paid, "total_paid_invoices": total_paid_invoices,
                "account_paid": account_paid,
                "total_remaining": max(0, total_inv - total_paid)}

# ══════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════
def handle_api(method, path, body, req):
    parsed = urlparse(path)
    parts  = parsed.path.strip("/").split("/")
    qs     = parse_qs(parsed.query)

    # AUTH login
    if len(parts) >= 3 and parts[1] == "auth" and parts[2] == "login":
        uname = body.get("username",""); p = body.get("password","")
        c = get_db()
        user = UsersDAO.get_by_username(c, uname)
        if not user or not verify_password(p, user.get("salt",""), user["password"]):
            c.close()
            return 401, {"detail": "اسم المستخدم او كلمة المرور غير صحيحة"}
        if not user.get("is_active", 1):
            c.close()
            return 401, {"detail": "الحساب موقف — تواصل مع المدير"}
        # ترحيل المستخدمين القدامى (salt فارغ) إلى التشفير الجديد
        if not user.get("salt",""):
            salt, new_hash = hash_password(p)
            UsersDAO.update_password(c, user["id"], new_hash, salt)
            user["password"] = new_hash
            user["salt"] = salt
            c.commit()
        # إنشاء token جلسة عشوائي مع حذف القديمة
        token = secrets.token_hex(32)
        SessionsDAO.delete_by_user(c, user["id"])
        SessionsDAO.create(c, user["id"], token)
        c.commit(); c.close()
        return 200, {"access_token": token, "token_type": "bearer",
                     "user": {"id":user["id"],"username":user["username"],
                              "full_name":user["full_name"],"role":user["role"],"is_active":1}}

    if len(parts) >= 3 and parts[1] == "auth" and parts[2] == "logout":
        auth = req.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            c = get_db()
            SessionsDAO.delete_by_token(c, auth[7:])
            c.commit(); c.close()
        return 200, {"ok": True}

    if len(parts) >= 3 and parts[1] == "auth" and parts[2] == "me":
        u = check_auth(req)
        if not u: return 401, {"detail":"غير مصرح"}
        return 200, {"id":u["id"],"username":u["username"],
                     "full_name":u["full_name"],"role":u["role"],"is_active":1}

    # ── AUTH change-password (self) ──
    if len(parts) >= 3 and parts[1] == "auth" and parts[2] == "change-password":
        u = check_auth(req)
        if not u: return 401, {"detail":"غير مصرح"}
        old_pw  = body.get("old_password","")
        new_pw  = body.get("new_password","")
        if not new_pw or len(new_pw) < 4:
            return 400, {"detail":"كلمة المرور يجب أن تكون 4 أحرف على الأقل"}
        if not verify_password(old_pw, u.get("salt",""), u["password"]):
            return 400, {"detail":"كلمة المرور الحالية غير صحيحة"}
        c = get_db()
        salt, new_hash = hash_password(new_pw)
        UsersDAO.update_password(c, u["id"], new_hash, salt)
        SessionsDAO.delete_by_user(c, u["id"])
        c.commit(); c.close()
        return 200, {"detail":"تم تغيير كلمة المرور بنجاح — سيتم تسجيل الخروج، يرجى تسجيل الدخول مرة أخرى"}

    u = check_auth(req)
    if not u: return 401, {"detail":"غير مصرح"}
    c = get_db()
    ep = parts[1] if len(parts) > 1 else ""

    # ── USERS (admin only) ──
    if ep == "users":
        if u["role"] != "admin":
            c.close(); return 403, {"detail":"غير مصرح — فقط للمدير"}
        if method == "GET" and len(parts) == 2:
            r = UsersDAO.list(c); c.close(); return 200, r
        if method == "POST":
            uname = body.get("username","").strip()
            pw    = body.get("password","").strip()
            fname = body.get("full_name","").strip()
            role  = body.get("role","user")
            if not uname or not pw:
                c.close(); return 400, {"detail":"اسم المستخدم وكلمة المرور مطلوبان"}
            if len(pw) < 4:
                c.close(); return 400, {"detail":"كلمة المرور 4 أحرف على الأقل"}
            if role not in ("admin","user","cashier"):
                role = "user"
            try:
                salt, pw_hash = hash_password(pw)
                uid = UsersDAO.create(c, uname, pw_hash, fname, role, salt)
                c.commit()
                r = UsersDAO.get_by_id(c, uid)
                c.close(); return 201, r
            except Exception as ex:
                c.close(); return 400, {"detail":"اسم المستخدم موجود مسبقاً"}
        if method == "PUT" and len(parts) == 3:
            uid   = int(parts[2])
            fname = body.get("full_name","").strip()
            role  = body.get("role","user")
            active= int(body.get("is_active", 1))
            if role not in ("admin","user","cashier"): role = "user"
            new_pw = body.get("password","").strip()
            if new_pw:
                if len(new_pw) < 4:
                    c.close(); return 400, {"detail":"كلمة المرور 4 أحرف على الأقل"}
                salt, new_hash = hash_password(new_pw)
                UsersDAO.update_with_password(c, uid, fname, role, active, new_hash, salt)
                SessionsDAO.delete_by_user(c, uid)
            else:
                UsersDAO.update(c, uid, fname, role, active)
            c.commit()
            r = UsersDAO.get_by_id(c, uid)
            c.close(); return 200, r
        if method == "DELETE" and len(parts) == 3:
            uid = int(parts[2])
            if uid == u["id"]:
                c.close(); return 400, {"detail":"لا يمكن حذف حسابك الحالي"}
            admins = UsersDAO.count_admins(c)
            target = UsersDAO.get_role(c, uid)
            if target and target["role"] == "admin" and admins <= 1:
                c.close(); return 400, {"detail":"لا يمكن حذف المدير الوحيد"}
            SessionsDAO.delete_by_user(c, uid)
            UsersDAO.delete(c, uid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── SETTINGS ──
    if ep == "settings":
        if method == "GET":
            cfg = SettingsDAO.get_all(c); c.close(); return 200, cfg
        if method == "POST":
            if u["role"] != "admin":
                c.close(); return 403, {"detail":"غير مصرح"}
            SettingsDAO.set_many(c, body)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── BACKUP ──
    if ep == "backup":
        if u["role"] != "admin":
            c.close(); return 403, {"detail":"غير مصرح — فقط للمدير"}
        if method == "GET" and len(parts) == 2:
            files = BackupDAO.list(c)
            c.close(); return 200, {"backups": files, "backup_dir": BACKUP_DIR}
        if method == "POST" and len(parts) == 2:
            c.close()
            download_name = body.get("download","")
            if download_name:
                result = BackupDAO.download(download_name)
                if not result:
                    return 404, {"detail":"الملف غير موجود"}
                return 200, result
            else:
                result = BackupDAO.create()
                return 201, result
        if method == "DELETE" and len(parts) == 3:
            BackupDAO.delete(parts[2])
            c.close(); return 200, {"ok": True}
        c.close(); return 404, {"detail": "not found"}

    # ── RESTORE ──
    if ep == "restore" and method == "POST":
        if u["role"] != "admin":
            c.close(); return 403, {"detail":"غير مصرح — فقط للمدير"}
        c.close()
        fname = body.get("name","")
        b64   = body.get("data","")
        if fname:
            auto = BackupDAO.restore_from_file(fname)
            if not auto:
                return 404, {"detail":"الملف غير موجود"}
            return 200, {"ok": True, "auto_backup": auto}
        elif b64:
            auto = BackupDAO.restore_from_data(b64)
            if not auto:
                return 400, {"detail":"ملف غير صالح"}
            return 200, {"ok": True, "auto_backup": auto}
        else:
            return 400, {"detail":"لم يُحدد ملف"}

    # ── SUPPLIERS ──
    if ep == "suppliers":
        if method=="GET" and len(parts)==2:
            r = SuppliersDAO.list(c); c.close(); return 200,r
        if method=="POST":
            sid = SuppliersDAO.create(c, body); c.commit()
            r = SuppliersDAO.get_by_id(c, sid); c.close(); return 201,r
        if method=="PUT" and len(parts)==3:
            SuppliersDAO.update(c, int(parts[2]), body); c.commit()
            r = SuppliersDAO.get_by_id(c, int(parts[2])); c.close(); return 200,r
        if method=="DELETE" and len(parts)==3:
            SuppliersDAO.delete(c, int(parts[2])); c.commit(); c.close(); return 200,{"ok":True}

    # ── CUSTOMERS ──
    if ep == "customers":
        if method=="GET" and len(parts)==2:
            r = CustomersDAO.list(c); c.close(); return 200,r
        if method=="POST":
            cid = CustomersDAO.create(c, body); c.commit()
            r = CustomersDAO.get_by_id(c, cid); c.close(); return 201,r
        if method=="PUT" and len(parts)==3:
            CustomersDAO.update(c, int(parts[2]), body); c.commit()
            r = CustomersDAO.get_by_id(c, int(parts[2])); c.close(); return 200,r
        if method=="DELETE" and len(parts)==3:
            CustomersDAO.delete(c, int(parts[2])); c.commit(); c.close(); return 200,{"ok":True}

    # ── PRODUCTS ──
    if ep == "products":
        if method=="GET" and len(parts)==2:
            r = ProductsDAO.list(c); c.close(); return 200,r
        if method=="GET" and len(parts)==3 and parts[2]=="next_barcode":
            code = ProductsDAO.next_barcode(c); c.close(); return 200, {"barcode": code}
        if method=="GET" and len(parts)==4 and parts[2]=="barcode":
            code = parts[3]
            r = ProductsDAO.get_by_barcode(c, code)
            matched_unit = None
            if not r:
                u = ProductUnitsDAO.get_by_serial(c, code)
                if u:
                    r = ProductsDAO.get_by_id(c, u["product_id"])
                    matched_unit = u
            c.close()
            if not r: return 404,{"detail":"غير موجود"}
            if matched_unit: r["matched_unit"] = matched_unit
            return 200,r
        if method=="GET" and len(parts)==4 and parts[2]=="search":
            q = parts[3]
            r = ProductsDAO.search(c, q); c.close(); return 200,r
        if method=="POST":
            try:
                pid = ProductsDAO.create(c, body); c.commit()
                r = ProductsDAO.get_by_id(c, pid); c.close(); return 201,r
            except sqlite3.IntegrityError:
                c.close(); return 400,{"detail":"الباركود موجود مسبقاً"}
        if method=="PUT" and len(parts)==3:
            ProductsDAO.update(c, int(parts[2]), body); c.commit()
            r = ProductsDAO.get_by_id(c, int(parts[2])); c.close(); return 200,r
        if method=="DELETE" and len(parts)==3:
            ProductsDAO.delete(c, int(parts[2])); c.commit(); c.close(); return 200,{"ok":True}

    # ── PRODUCT UNITS (سيريال فريد لكل قطعة) ──
    if ep == "units":
        if method == "GET" and len(parts) == 2:
            product_id = qs.get("product_id",[""])[0]
            status_f   = qs.get("status",[""])[0]
            r = ProductUnitsDAO.list(c, product_id, status_f); c.close(); return 200, r
        if method == "GET" and len(parts) == 4 and parts[2] == "serial":
            serial = parts[3]
            u = ProductUnitsDAO.get_by_serial(c, serial)
            if not u: c.close(); return 404, {"detail":"السيريال غير موجود"}
            prod = ProductsDAO.get_by_id(c, u["product_id"])
            u["product"] = prod
            c.close(); return 200, u
        if method == "POST":
            product_id = body.get("product_id")
            serials    = [s.strip() for s in body.get("serials",[]) if s.strip()]
            if not product_id or not serials:
                c.close(); return 400, {"detail":"المنتج والسيريالات مطلوبة"}
            added, dup = [], []
            for s in serials:
                try:
                    ProductUnitsDAO.create(c, product_id, s)
                    added.append(s)
                except sqlite3.IntegrityError:
                    dup.append(s)
            if added:
                ProductsDAO.update_stock(c, product_id, len(added))
            c.commit(); c.close()
            return 201, {"added": added, "duplicated": dup}
        if method == "DELETE" and len(parts) == 3:
            uid = int(parts[2])
            u = ProductUnitsDAO.get_by_serial(c, uid) or ProductsDAO.get_by_id(c, uid)
            if not u: c.close(); return 404, {"detail":"غير موجود"}
            u_row = BaseDAO.row1(c.execute("SELECT * FROM product_units WHERE id=?", (uid,)))
            if not u_row: c.close(); return 404, {"detail":"غير موجود"}
            if u_row["status"] == "sold":
                c.close(); return 400, {"detail":"لا يمكن حذف وحدة تم بيعها"}
            ProductUnitsDAO.delete(c, uid)
            ProductsDAO.update_stock(c, u_row["product_id"], -1)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── PURCHASES ──
    if ep == "purchases":
        if method=="GET" and len(parts)==2:
            ps = PurchasesDAO.list(c); c.close(); return 200,ps
        if method=="GET" and len(parts)==3:
            pid = int(parts[2])
            p = PurchasesDAO.get_by_id(c, pid)
            if not p: c.close(); return 404,{"detail":"غير موجود"}
            p["items"] = PurchasesDAO.get_items(c, pid)
            c.close(); return 200,p
        if method=="POST":
            if not body.get("supplier_id"):
                c.close(); return 400,{"detail":"يجب تحديد المورد"}
            items = body.get("items",[])
            if not items:
                c.close(); return 400,{"detail":"يجب إضافة صنف واحد على الأقل"}
            total = sum(i["qty"]*i["price"] for i in items)
            supplier_id = int(body.get("supplier_id")) if body.get("supplier_id") else None
            pid = PurchasesDAO.create(c, supplier_id, body.get("date",""), body.get("status","معلق"), body.get("notes",""), total)
            for i in items:
                PurchasesDAO.create_item(c, pid, i["product_id"], i["qty"], i["price"])
                ProductsDAO.update_stock(c, i["product_id"], i["qty"])
                serials = [s.strip() for s in i.get("serials",[]) if str(s).strip()]
                for s in serials:
                    try:
                        ProductUnitsDAO.create(c, i["product_id"], s, "in_stock", pid)
                    except sqlite3.IntegrityError:
                        pass
            c.commit()
            p = PurchasesDAO.get_by_id(c, pid)
            p["items"] = PurchasesDAO.get_items(c, pid)
            c.close(); return 201,p
        if method=="PUT" and len(parts)==3:
            pid = int(parts[2])
            items = body.get("items", [])
            total = sum(i["qty"] * i["price"] for i in items)
            old_items = PurchasesDAO.get_items(c, pid)
            for oi in old_items:
                # لا نطرح أكثر من المخزون المتاح فعلياً حتى لا نأثر على مخزون آتٍ من فواتير أخرى
                cur_p = ProductsDAO.get_by_id(c, oi["product_id"])
                avail = cur_p["stock"] if cur_p else 0
                reverse_qty = min(oi["qty"], avail)
                if reverse_qty > 0:
                    ProductsDAO.update_stock(c, oi["product_id"], -reverse_qty)
            PurchasesDAO.delete_items(c, pid)
            # إزالة الوحدات المسلسلة القديمة لهذه الفاتورة التي لم تُبَع بعد؛ الوحدات المباعة تبقى بالسجل التاريخي
            ProductUnitsDAO.delete_by_purchase(c, pid, "in_stock")
            ProductUnitsDAO.unpin_purchase(c, pid)
            supplier_id = int(body.get("supplier_id")) if body.get("supplier_id") else None
            PurchasesDAO.update(c, pid, supplier_id, body.get("date",""), body.get("status","معلق"), body.get("notes",""), total)
            for i in items:
                PurchasesDAO.create_item(c, pid, i["product_id"], i["qty"], i["price"])
                ProductsDAO.update_stock(c, i["product_id"], i["qty"])
                serials = [s.strip() for s in i.get("serials",[]) if str(s).strip()]
                for s in serials:
                    try:
                        ProductUnitsDAO.create(c, i["product_id"], s, "in_stock", pid)
                    except sqlite3.IntegrityError:
                        pass
            c.commit()
            p = PurchasesDAO.get_by_id(c, pid)
            p["items"] = PurchasesDAO.get_items(c, pid)
            c.close(); return 200, p
        if method=="DELETE" and len(parts)==3:
            pid = int(parts[2])
            old_items = PurchasesDAO.get_items(c, pid)
            for oi in old_items:
                cur_p = ProductsDAO.get_by_id(c, oi["product_id"])
                avail = cur_p["stock"] if cur_p else 0
                reverse_qty = min(oi["qty"], avail)
                if reverse_qty > 0:
                    ProductsDAO.update_stock(c, oi["product_id"], -reverse_qty)
            ProductUnitsDAO.delete_by_purchase(c, pid, "in_stock")
            ProductUnitsDAO.unpin_purchase(c, pid)
            PurchasesDAO.delete(c, pid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── PURCHASE RETURNS ──
    if ep == "purchase_returns":
        if method == "GET" and len(parts) == 2:
            rs = PurchaseReturnsDAO.list(c); c.close(); return 200, rs
        if method == "POST":
            items = body.get("items", [])
            total = sum(i["qty"] * i["price"] for i in items)
            rid = PurchaseReturnsDAO.create(c, body.get("purchase_id"),
                  int(body.get("supplier_id")) if body.get("supplier_id") else None,
                  body.get("date",""), total, body.get("reason",""), body.get("notes",""))
            for i in items:
                PurchaseReturnsDAO.create_item(c, rid, i["product_id"], i["qty"], i["price"])
                ProductsDAO.update_stock(c, i["product_id"], -i["qty"])
            c.commit()
            r = BaseDAO.row1(c.execute("SELECT * FROM purchase_returns WHERE id=?", (rid,)))
            r["items"] = BaseDAO.rows(c.execute(
                "SELECT pri.*, pr.name as product_name, pr.barcode, pr.unit "
                "FROM purchase_return_items pri LEFT JOIN products pr ON pr.id=pri.product_id "
                "WHERE pri.return_id=?", (rid,)))
            c.close(); return 201, r

    # ── SALES ──
    if ep == "sales":
        if method=="GET" and len(parts)==2:
            ss = SalesDAO.list(c); c.close(); return 200,ss
        if method=="GET" and len(parts)==3:
            sid = int(parts[2])
            s = SalesDAO.get_by_id(c, sid)
            if not s: c.close(); return 404,{"detail":"غير موجود"}
            c.close(); return 200,s
        if method=="POST":
            items = body.get("items",[])
            item_discount_sum = sum(float(i.get("discount",0) or 0) for i in items)
            raw_total = sum(i["qty"]*i["price"] for i in items)
            invoice_discount = max(0.0, float(body.get("discount",0) or 0))
            total = max(0.0, raw_total - item_discount_sum - invoice_discount)
            for i in items:
                serials = [s.strip() for s in i.get("serials",[]) if str(s).strip()]
                if not serials: continue
                if len(serials) != i["qty"]:
                    c.close(); return 400, {"detail": f"عدد السيريالات لا يطابق الكمية للمنتج #{i['product_id']}"}
                for s in serials:
                    u = ProductUnitsDAO.get_by_serial(c, s)
                    if not u or str(u.get("product_id")) != str(i["product_id"]) or u["status"] != "in_stock":
                        c.close(); return 400, {"detail": f"السيريال {s} غير متاح للبيع"}
            sid = SalesDAO.create(c, body.get("customer_id"), body.get("date",""), body.get("status","مدفوع"),
                                  body.get("pay_method","نقدي"), body.get("notes",""), total, invoice_discount)
            for i in items:
                SalesDAO.create_item(c, sid, i["product_id"], i["qty"], i["price"], float(i.get("discount",0) or 0))
                ProductsDAO.update_stock(c, i["product_id"], -i["qty"])
                serials = [s.strip() for s in i.get("serials",[]) if str(s).strip()]
                for s in serials:
                    ProductUnitsDAO.mark_sold_by_serial(c, s, i["product_id"], sid)
            c.commit()
            s = SalesDAO.get_by_id(c, sid)
            c.close(); return 201,s
        if method=="PUT" and len(parts)==3:
            sid   = int(parts[2])
            items = body.get("items",[])
            item_discount_sum = sum(float(i.get("discount",0) or 0) for i in items)
            raw_total = sum(i["qty"]*i["price"] for i in items)
            invoice_discount = max(0.0, float(body.get("discount",0) or 0))
            total = max(0.0, raw_total - item_discount_sum - invoice_discount)
            old_items = SalesDAO.get_old_items(c, sid)
            for oi in old_items:
                ProductsDAO.update_stock(c, oi["product_id"], oi["qty"])
            ProductUnitsDAO.unsold_by_sale(c, sid)
            SalesDAO.delete_items(c, sid)
            SalesDAO.update(c, sid, body.get("customer_id"), body.get("date",""), body.get("status","مدفوع"),
                            body.get("pay_method","نقدي"), body.get("notes",""), total, invoice_discount)
            for i in items:
                SalesDAO.create_item(c, sid, i["product_id"], i["qty"], i["price"], float(i.get("discount",0) or 0))
                ProductsDAO.update_stock(c, i["product_id"], -i["qty"])
                serials = [s2.strip() for s2 in i.get("serials",[]) if str(s2).strip()]
                for s2 in serials:
                    ProductUnitsDAO.mark_sold_by_serial(c, s2, i["product_id"], sid)
            c.commit()
            s = SalesDAO.get_by_id(c, sid)
            c.close(); return 200,s
        if method=="DELETE" and len(parts)==3:
            sid = int(parts[2])
            old_items = SalesDAO.get_old_items(c, sid)
            for oi in old_items:
                ProductsDAO.update_stock(c, oi["product_id"], oi["qty"])
            ProductUnitsDAO.unsold_by_sale(c, sid)
            SalesDAO.delete_items(c, sid)
            SalesDAO.delete(c, sid)
            c.commit(); c.close(); return 200,{"ok":True}

    # ── EXPENSE CATEGORIES ──
    if ep == "expense_categories":
        if method == "GET" and len(parts) == 2:
            r = ExpenseCategoriesDAO.list(c); c.close(); return 200, r
        if method == "POST":
            name = body.get("name","").strip()
            if not name:
                c.close(); return 400, {"detail":"اسم التصنيف مطلوب"}
            try:
                cid = ExpenseCategoriesDAO.create(c, name, body.get("icon","📦"))
                c.commit()
                r = ExpenseCategoriesDAO.get_by_id(c, cid); c.close(); return 201, r
            except sqlite3.IntegrityError:
                c.close(); return 400, {"detail":"هذا التصنيف موجود مسبقاً"}
        if method == "PUT" and len(parts) == 3:
            cid = int(parts[2])
            ExpenseCategoriesDAO.update(c, cid, body.get("name",""), body.get("icon","📦"))
            c.commit()
            r = ExpenseCategoriesDAO.get_by_id(c, cid); c.close(); return 200, r
        if method == "DELETE" and len(parts) == 3:
            cid = int(parts[2])
            cat = ExpenseCategoriesDAO.get_by_id(c, cid)
            if cat and cat.get("is_default"):
                c.close(); return 400, {"detail":"لا يمكن حذف تصنيف افتراضي"}
            ExpenseCategoriesDAO.delete(c, cid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── EXPENSES ──
    if ep == "expenses":
        if method == "GET" and len(parts) == 2:
            date_from = qs.get("date_from",[None])[0]
            date_to   = qs.get("date_to",[None])[0]
            category_id = qs.get("category_id",[None])[0]
            r = ExpensesDAO.list(c, date_from, date_to, category_id)
            c.close(); return 200, r
        if method == "POST":
            amount = float(body.get("amount",0) or 0)
            if amount <= 0:
                c.close(); return 400, {"detail":"المبلغ يجب أن يكون أكبر من صفر"}
            if not body.get("description","").strip():
                c.close(); return 400, {"detail":"الوصف مطلوب"}
            eid = ExpensesDAO.create(c, body)
            c.commit()
            r = ExpensesDAO.get_by_id(c, eid); c.close(); return 201, r
        if method == "PUT" and len(parts) == 3:
            eid = int(parts[2])
            if not ExpensesDAO.get_by_id(c, eid):
                c.close(); return 404, {"detail":"المصروف غير موجود"}
            ExpensesDAO.update(c, eid, body)
            c.commit()
            r = ExpensesDAO.get_by_id(c, eid); c.close(); return 200, r
        if method == "DELETE" and len(parts) == 3:
            eid = int(parts[2])
            exp = ExpensesDAO.get_by_id(c, eid)
            if not exp:
                c.close(); return 404, {"detail":"المصروف غير موجود"}
            if exp.get("payroll_id"):
                c.close(); return 400, {"detail":"هذا المصروف مرتبط بكشف راتب — احذف كشف الراتب من صفحة الموظفين بدلاً من ذلك"}
            ExpensesDAO.delete(c, eid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── EMPLOYEES ──
    if ep == "employees":
        if method == "GET" and len(parts) == 2:
            r = EmployeesDAO.list(c); c.close(); return 200, r
        if method == "POST":
            if not body.get("name","").strip():
                c.close(); return 400, {"detail":"اسم الموظف مطلوب"}
            eid = EmployeesDAO.create(c, body)
            c.commit()
            r = EmployeesDAO.get_by_id(c, eid); c.close(); return 201, r
        if method == "PUT" and len(parts) == 3:
            eid = int(parts[2])
            if not EmployeesDAO.get_by_id(c, eid):
                c.close(); return 404, {"detail":"الموظف غير موجود"}
            EmployeesDAO.update(c, eid, body)
            c.commit()
            r = EmployeesDAO.get_by_id(c, eid); c.close(); return 200, r
        if method == "DELETE" and len(parts) == 3:
            eid = int(parts[2])
            EmployeesDAO.delete(c, eid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── SALARY ADVANCES (سلف الموظفين) ──
    if ep == "salary_advances":
        if method == "GET" and len(parts) == 2:
            employee_id = qs.get("employee_id",[None])[0]
            if not employee_id:
                c.close(); return 400, {"detail":"يجب تحديد الموظف"}
            r = SalaryAdvancesDAO.list_by_employee(c, employee_id)
            c.close(); return 200, r
        if method == "POST":
            employee_id = body.get("employee_id")
            amount = float(body.get("amount",0) or 0)
            if not employee_id or amount <= 0:
                c.close(); return 400, {"detail":"الموظف والمبلغ مطلوبان"}
            aid = SalaryAdvancesDAO.create(c, employee_id, amount, body.get("date",""), body.get("notes",""))
            c.commit()
            r = BaseDAO.row1(c.execute("SELECT * FROM salary_advances WHERE id=?", (aid,)))
            c.close(); return 201, r
        if method == "DELETE" and len(parts) == 3:
            aid = int(parts[2])
            adv = BaseDAO.row1(c.execute("SELECT * FROM salary_advances WHERE id=?", (aid,)))
            if not adv:
                c.close(); return 404, {"detail":"السلفة غير موجودة"}
            if adv.get("payroll_id"):
                c.close(); return 400, {"detail":"لا يمكن حذف سلفة تم خصمها ضمن كشف راتب سابق"}
            SalaryAdvancesDAO.delete(c, aid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── PAYROLL (كشوف الرواتب الشهرية) ──
    if ep == "payroll":
        if method == "GET" and len(parts) == 2:
            employee_id = qs.get("employee_id",[None])[0]
            r = PayrollDAO.list(c, employee_id)
            c.close(); return 200, r
        if method == "POST":
            employee_id = body.get("employee_id")
            month = body.get("month","")
            emp = EmployeesDAO.get_by_id(c, employee_id) if employee_id else None
            if not emp:
                c.close(); return 400, {"detail":"الموظف غير موجود"}
            if not month:
                c.close(); return 400, {"detail":"يجب تحديد الشهر (YYYY-MM)"}
            if PayrollDAO.get_by_employee_month(c, employee_id, month):
                c.close(); return 400, {"detail":"تم دفع راتب هذا الموظف لهذا الشهر مسبقاً"}
            unconsumed = SalaryAdvancesDAO.list_unconsumed(c, employee_id)
            total_advances = sum(a["amount"] for a in unconsumed)
            base_salary = float(emp.get("base_salary",0) or 0)
            adjustment = float(body.get("adjustment",0) or 0)
            net_paid = max(0.0, base_salary + adjustment - total_advances)
            date_paid = body.get("date_paid","")
            payment_method = body.get("payment_method","نقدي")
            cat = ExpenseCategoriesDAO.get_by_name(c, "رواتب وأجور")
            exp_data = {
                "category_id": cat["id"] if cat else None,
                "description": f"راتب شهر {month} — {emp['name']}",
                "amount": net_paid, "date": date_paid, "payment_method": payment_method,
                "cheque_no": body.get("cheque_no",""), "cheque_date": body.get("cheque_date",""),
                "cheque_bank": body.get("cheque_bank",""), "cheque_image": body.get("cheque_image",""),
                "notes": body.get("notes",""), "employee_id": employee_id,
            }
            exp_id = ExpensesDAO.create(c, exp_data)
            pid = PayrollDAO.create(c, employee_id, month, base_salary, total_advances, adjustment,
                                    body.get("adjustment_notes",""), net_paid, date_paid, payment_method,
                                    body.get("notes",""), exp_id)
            c.execute("UPDATE expenses SET payroll_id=? WHERE id=?", (pid, exp_id))
            SalaryAdvancesDAO.mark_consumed(c, [a["id"] for a in unconsumed], pid)
            c.commit()
            r = PayrollDAO.get_by_id(c, pid); c.close(); return 201, r
        if method == "DELETE" and len(parts) == 3:
            pid = int(parts[2])
            pr = PayrollDAO.get_by_id(c, pid)
            if not pr:
                c.close(); return 404, {"detail":"كشف الراتب غير موجود"}
            if pr.get("expense_id"):
                ExpensesDAO.delete(c, pr["expense_id"])
            SalaryAdvancesDAO.unmark_by_payroll(c, pid)
            PayrollDAO.delete(c, pid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── RECURRING EXPENSES (المصاريف المتكررة) ──
    if ep == "recurring_expenses":
        if method == "GET" and len(parts) == 2:
            r = RecurringExpensesDAO.list(c); c.close(); return 200, r
        if method == "POST" and len(parts) == 2:
            if not body.get("description","").strip():
                c.close(); return 400, {"detail":"الوصف مطلوب"}
            rid = RecurringExpensesDAO.create(c, body)
            c.commit()
            r = RecurringExpensesDAO.get_by_id(c, rid); c.close(); return 201, r
        if method == "PUT" and len(parts) == 3:
            rid = int(parts[2])
            if not RecurringExpensesDAO.get_by_id(c, rid):
                c.close(); return 404, {"detail":"غير موجود"}
            RecurringExpensesDAO.update(c, rid, body)
            c.commit()
            r = RecurringExpensesDAO.get_by_id(c, rid); c.close(); return 200, r
        if method == "DELETE" and len(parts) == 3:
            rid = int(parts[2])
            RecurringExpensesDAO.delete(c, rid)
            c.commit(); c.close(); return 200, {"ok": True}
        if method == "POST" and len(parts) == 4 and parts[3] == "pay":
            rid = int(parts[2])
            rec = RecurringExpensesDAO.get_by_id(c, rid)
            if not rec:
                c.close(); return 404, {"detail":"غير موجود"}
            month = body.get("date","")[:7]
            if RecurringExpensesDAO.paid_this_month(c, rid, month):
                c.close(); return 400, {"detail":"تم تسجيل دفعة هذا المصروف لهذا الشهر مسبقاً"}
            exp_data = {
                "category_id": rec["category_id"],
                "description": f"{rec['description']} — {month}",
                "amount": float(body.get("amount", rec["amount"]) or 0),
                "date": body.get("date",""), "payment_method": body.get("payment_method","نقدي"),
                "cheque_no": body.get("cheque_no",""), "cheque_date": body.get("cheque_date",""),
                "cheque_bank": body.get("cheque_bank",""), "cheque_image": body.get("cheque_image",""),
                "notes": body.get("notes",""), "recurring_id": rid,
            }
            eid = ExpensesDAO.create(c, exp_data)
            c.commit()
            r = ExpensesDAO.get_by_id(c, eid); c.close(); return 201, r

    # ── SERVICE ORDERS (طلبات التركيب والصيانة) ──
    if ep == "service_orders":
        if method == "GET" and len(parts) == 2:
            r = ServiceOrdersDAO.list(c); c.close(); return 200, r
        if method == "GET" and len(parts) == 3:
            r = ServiceOrdersDAO.get_by_id(c, int(parts[2]))
            if not r: c.close(); return 404, {"detail":"طلب الخدمة غير موجود"}
            c.close(); return 200, r
        if method == "POST":
            if not body.get("customer_id"):
                c.close(); return 400, {"detail":"يجب اختيار الزبون"}
            if not body.get("received_date"):
                c.close(); return 400, {"detail":"يجب تحديد تاريخ الاستلام"}
            sid = ServiceOrdersDAO.create(c, body)
            parts_list = body.get("parts", [])
            parts_cost = 0
            for pt in parts_list:
                qty = int(pt.get("qty",1)); price = float(pt.get("price",0) or 0)
                ServiceOrdersDAO.add_part(c, sid, pt["product_id"], qty, price)
                ProductsDAO.update_stock(c, pt["product_id"], -qty)
                parts_cost += qty*price
            ServiceOrdersDAO.set_parts_cost(c, sid, parts_cost)
            c.commit()
            r = ServiceOrdersDAO.get_by_id(c, sid); c.close(); return 201, r
        if method == "PUT" and len(parts) == 3:
            sid = int(parts[2])
            old = ServiceOrdersDAO.get_by_id(c, sid)
            if not old: c.close(); return 404, {"detail":"طلب الخدمة غير موجود"}
            # إن أُرسلت قطع جديدة، نُرجع مخزون القطع القديمة أولاً ثم نطبّق الجديدة
            if "parts" in body:
                for op in old.get("parts", []):
                    ProductsDAO.update_stock(c, op["product_id"], op["qty"])
                ServiceOrdersDAO.delete_parts(c, sid)
                parts_cost = 0
                for pt in body.get("parts", []):
                    qty = int(pt.get("qty",1)); price = float(pt.get("price",0) or 0)
                    ServiceOrdersDAO.add_part(c, sid, pt["product_id"], qty, price)
                    ProductsDAO.update_stock(c, pt["product_id"], -qty)
                    parts_cost += qty*price
                body["parts_cost"] = parts_cost
            else:
                body["parts_cost"] = old.get("parts_cost", 0)
            # تعيين تاريخ التسليم تلقائياً عند إتمام الطلب إن لم يُحدَّد
            if body.get("status") == "مكتمل" and not body.get("completed_date"):
                body["completed_date"] = datetime.now().strftime("%Y-%m-%d")
            ServiceOrdersDAO.update(c, sid, body)
            c.commit()
            r = ServiceOrdersDAO.get_by_id(c, sid); c.close(); return 200, r
        if method == "DELETE" and len(parts) == 3:
            sid = int(parts[2])
            old = ServiceOrdersDAO.get_by_id(c, sid)
            if not old: c.close(); return 404, {"detail":"طلب الخدمة غير موجود"}
            for op in old.get("parts", []):
                ProductsDAO.update_stock(c, op["product_id"], op["qty"])
            ServiceOrdersDAO.delete(c, sid)
            c.commit(); c.close(); return 200, {"ok": True}

    # ── DASHBOARD ──
    if ep == "dashboard":
        r = DashboardDAO.stats(c); c.close(); return 200, r

    # ── CHEQUE IMAGE UPLOAD ──
    if ep == "payments" and len(parts) == 4 and parts[3] == "image":
        pid = int(parts[2])
        pay = PaymentsDAO.get_by_id(c, pid)
        if not pay:
            c.close(); return 404, {"detail":"الدفعة غير موجودة"}
        if method == "POST":
            img = body.get("image", "")
            if not img:
                c.close(); return 400, {"detail": "لم تُرفع صورة"}
            if not img.startswith("data:image"):
                c.close(); return 400, {"detail": "صيغة الصورة غير صالحة"}
            c.execute("UPDATE payments SET cheque_image=? WHERE id=?", (img, pid))
            c.commit(); c.close(); return 200, {"ok": True, "id": pid}
        if method == "DELETE":
            c.execute("UPDATE payments SET cheque_image='' WHERE id=?", (pid,))
            c.commit(); c.close(); return 200, {"ok": True}

    # ── CHEQUES REPORT ──
    if ep == "reports" and len(parts) >= 3 and parts[2] == "cheques":
        direction = qs.get("direction",["all"])[0]
        status    = qs.get("status",["all"])[0]
        date_from = qs.get("date_from",[""])[0]
        date_to   = qs.get("date_to",  [""])[0]
        result = ReportsDAO.cheques_report(c, direction, status, date_from, date_to)
        c.close(); return 200, result

    # ── SUPPLIER REPORT ──
    if ep == "reports" and len(parts) >= 3 and parts[2] == "supplier":
        try:
            sup_id = int(qs.get("supplier_id",[0])[0])
        except:
            c.close(); return 400,{"detail":"رقم المورد غير صحيح"}
        date_from = qs.get("date_from",[""])[0]
        date_to   = qs.get("date_to",  [""])[0]
        if not date_from: date_from = "2000-01-01"
        if not date_to:   date_to   = "2099-12-31"
        result = ReportsDAO.supplier_report(c, sup_id, date_from, date_to)
        if not result:
            c.close(); return 404,{"detail":"المورد غير موجود"}
        c.close(); return 200, result

    # ── CUSTOMER REPORT ──
    if ep == "reports" and len(parts) >= 3 and parts[2] == "customer":
        try:
            cust_id = int(qs.get("customer_id",[0])[0])
        except:
            c.close(); return 400,{"detail":"رقم الزبون غير صحيح"}
        date_from = qs.get("date_from",[""])[0]
        date_to   = qs.get("date_to",  [""])[0]
        if not date_from: date_from = "2000-01-01"
        if not date_to:   date_to   = "2099-12-31"
        result = ReportsDAO.customer_report(c, cust_id, date_from, date_to)
        if not result:
            c.close(); return 404,{"detail":"الزبون غير موجود"}
        c.close(); return 200, result

    # ── PAYMENTS ──
    if ep == "payments":
        if method == "GET":
            ref_type = qs.get("ref_type",[""])[0]
            ref_id   = qs.get("ref_id",[""])[0]
            party_type = qs.get("party_type",[""])[0]
            party_id   = qs.get("party_id",[""])[0]
            if ref_type and ref_id:
                ps = PaymentsDAO.get_by_ref(c, ref_type, ref_id)
            elif party_type and party_id:
                ps = PaymentsDAO.get_by_party(c, party_type, party_id)
            else:
                ps = PaymentsDAO.list_recent(c)
            c.close(); return 200, ps
        if method == "POST":
            amount = float(body.get("amount", 0))
            if amount <= 0:
                c.close(); return 400, {"detail": "المبلغ يجب أن يكون أكبر من صفر"}
            pay_id = PaymentsDAO.create(c,
                body.get("ref_type",""), body.get("ref_id",0), body.get("party_type",""), body.get("party_id",0),
                amount, body.get("method","نقدي"), body.get("date",""),
                body.get("cheque_no",""), body.get("cheque_date",""), body.get("cheque_bank",""),
                body.get("cheque_image",""), body.get("notes",""))
            c.commit()
            PaymentsDAO.update_invoice_status(c, body.get("ref_type",""), int(body.get("ref_id",0)))
            c.commit()
            pay = PaymentsDAO.get_by_id(c, pay_id)
            c.close(); return 201, pay
        if method == "DELETE" and len(parts)==3:
            pid = int(parts[2])
            pay = PaymentsDAO.get_by_id(c, pid)
            if not pay:
                c.close(); return 404, {"detail":"الدفعة غير موجودة"}
            PaymentsDAO.delete(c, pid)
            c.commit()
            PaymentsDAO.update_invoice_status(c, pay["ref_type"], pay["ref_id"])
            c.commit()
            c.close(); return 200, {"ok": True}
        if method == "PUT" and len(parts)==3:
            pid = int(parts[2])
            old = PaymentsDAO.update(c, pid,
                amount=body.get("amount"), method=body.get("method"),
                date=body.get("date"), notes=body.get("notes"),
                cheque_no=body.get("cheque_no"), cheque_date=body.get("cheque_date"),
                cheque_bank=body.get("cheque_bank"), cheque_image=body.get("cheque_image"),
                cheque_status=body.get("cheque_status"))
            if not old:
                c.close(); return 404, {"detail":"الدفعة غير موجودة"}
            c.commit()
            PaymentsDAO.update_invoice_status(c, old["ref_type"], old["ref_id"])
            c.commit()
            r = PaymentsDAO.get_by_id(c, pid)
            c.close(); return 200, r

    # ── PAYMENTS SUMMARY ──
    if ep == "payments_summary":
        party_type = qs.get("party_type",[""])[0]
        party_id   = int(qs.get("party_id",[0])[0])
        result = ReportsDAO.payments_summary(c, party_type, party_id)
        c.close(); return 200, result

    # ── ACCOUNT-LEVEL PAYMENT (دفعة على الحساب كله) ──
    if ep == "pay_account" and method == "POST":
        amount = float(body.get("amount",0))
        if amount <= 0:
            c.close(); return 400,{"detail":"المبلغ يجب أن يكون أكبر من صفر"}
        pay_id = PaymentsDAO.create(c, "account", 0,
            body.get("party_type",""), int(body.get("party_id",0)),
            amount, body.get("method","نقدي"), body.get("date",""),
            body.get("cheque_no",""), body.get("cheque_date",""),
            body.get("cheque_bank",""), body.get("cheque_image",""), body.get("notes",""))
        c.commit(); c.close()
        return 201, {"ok": True, "payment_id": pay_id, "total_paid": amount}

    # ── PURCHASE RETURN (مردود) ──
    if ep == "purchase_return" and method == "POST":
        pid   = body.get("purchase_id")
        items = body.get("items", [])
        notes = body.get("notes", "")
        date  = body.get("date", "")
        total = sum(i["qty"] * i["price"] for i in items)
        sup_id = PurchasesDAO.get_supplier_id(c, pid)
        ret_id = PurchasesDAO.create(c, sup_id, date, "مردود", f"مردود من فاتورة #{pid} - {notes}", -total)
        for i in items:
            PurchasesDAO.create_item(c, ret_id, i["product_id"], i["qty"], i["price"])
            ProductsDAO.update_stock(c, i["product_id"], -i["qty"])
        c.commit()
        ret = PurchasesDAO.get_by_id(c, ret_id)
        ret["items"] = PurchasesDAO.get_items(c, ret_id)
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
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
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

// معالج الأخطاء العام - يمنع توقف الصفحة
window.onerror = function(msg, src, line, col, err){
  console.error('JS Error:', msg, 'line:', line);
  const el = document.getElementById('app');
  if(el && !TOKEN){
    el.innerHTML = '<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;">'
    + '<div style="width:360px;padding:36px;background:#161923;border-radius:18px;border:1px solid #1e2537;text-align:center;">'
    + '<div style="font-size:48px;margin-bottom:16px;">⚠️</div>'
    + '<div style="font-size:18px;font-weight:700;color:#f87171;margin-bottom:8px;">خطأ في التحميل</div>'
    + '<div style="color:#64748b;font-size:13px;margin-bottom:20px;">' + msg + '</div>'
    + '<button onclick="location.reload()" style="background:linear-gradient(135deg,#2d6a4f,#1b4332);color:#fff;border:none;padding:10px 24px;border-radius:8px;cursor:pointer;font-size:15px;">🔄 إعادة المحاولة</button>'
    + '</div></div>';
  }
  return false;
};

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
let MS = null;          // حالة النافذة المنبثقة الحالية (Modal State)
let cart = [];          // سلة فاتورة الشراء الجارية
let supStats = [], custStats = [];   // إحصاءات صفحة الحسابات
let _purDraftStash = null;           // حفظ مؤقت لحالة فاتورة الشراء عند فتح نموذج منتج جديد من داخلها
let _pendingPurDraftFields = null;   // حفظ حقول المورد/التاريخ/الحالة مؤقتاً
let _pendingSelectProductId = null;  // تحديد المنتج الذي أُنشئ للتو ليُختار تلقائياً
let products=[], suppliers=[], customers=[], purchases=[], sales=[], stats=null, loading=false;
let expenseCategories=[], expenses=[], employees=[], payrollRecords=[], recurringExpenses=[];
let serviceOrders=[];
let sysUsers=[], sysSettings={currency:'₪', currency_name:'شيكل', system_name:'نظام ادارة المخازن', low_stock_threshold:'20', vip_customer_threshold:'5000', overdue_days_threshold:'30', supplier_payable_alert_threshold:'5000'};

// دالة مساعدة لعرض العملة
function cur(){ return sysSettings.currency||'₪'; }
function lowStockLimit(){ return parseInt(sysSettings.low_stock_threshold)||20; }
// تحويل أي نص مُدخل من المستخدم (اسم منتج/مورد/زبون/ملاحظة...) لنص آمن قبل حقنه بـ innerHTML
function esc(s){
  if(s===null||s===undefined) return '';
  return String(s).replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

// تجميع أصناف الفاتورة: يدمج الأسطر المتكررة لنفس المنتج (بنفس السعر) بسطر واحد،
// ويجمع كل السيريالات المرتبطة بها (للمنتجات المتتبَّعة بسيريال فريد) بقائمة واحدة تحت السطر
function groupInvoiceItems(items){
  const map = new Map();
  const order = [];
  (items||[]).forEach(it=>{
    const key = it.product_id+'|'+it.price;
    if(!map.has(key)){
      map.set(key, {...it, qty:0, _serials:new Set()});
      order.push(key);
    }
    const g = map.get(key);
    g.qty += (it.qty||0);
    if(it.serials_str){
      String(it.serials_str).split(',').filter(Boolean).forEach(s=>g._serials.add(s));
    }
  });
  return order.map(k=>{
    const g = map.get(k);
    const serials = Array.from(g._serials);
    delete g._serials;
    return {...g, serials};
  });
}

// تصنيف الزبون حسب إجمالي مشترياته مقارنة بحد "الزبون المميز" من الإعدادات
function customerTier(custId){
  const total = sales.filter(s=>parseInt(s.customer_id)===parseInt(custId)).reduce((t,s)=>t+(s.total||0),0);
  const threshold = parseFloat(sysSettings.vip_customer_threshold||5000);
  return total >= threshold ? 'vip' : 'regular';
}

// اكتشاف تأخر الزبون بالسداد: أقدم فاتورة غير مسددة بالكامل وعمرها بالأيام يتجاوز الحد المحدد بالإعدادات
function customerOverdueInfo(custId){
  const days = parseInt(sysSettings.overdue_days_threshold||30);
  const unpaidSales = sales.filter(s=>parseInt(s.customer_id)===parseInt(custId) && (s.remaining||0) > 0)
    .map(s=>({date:s.date, remaining:s.remaining}));
  const unpaidServices = serviceOrders.filter(o=>parseInt(o.customer_id)===parseInt(custId) && (o.remaining||0) > 0)
    .map(o=>({date:o.received_date, remaining:o.remaining}));
  const unpaid = [...unpaidSales, ...unpaidServices];
  if(!unpaid.length) return null;
  const oldest = unpaid.reduce((a,b)=> (a.date < b.date ? a : b));
  const ageDays = Math.floor((new Date() - new Date(oldest.date)) / 86400000);
  if(ageDays < days) return null;
  const totalDue = unpaid.reduce((t,s)=>t+(s.remaining||0),0);
  return {ageDays, totalDue, oldestDate: oldest.date, invoiceCount: unpaid.length};
}

// كل الزبائن المتأخرين حالياً (للاستخدام بلوحة التحكم وصفحة الحسابات)
function getOverdueCustomers(){
  return customers
    .map(c=>({customer:c, info:customerOverdueInfo(c.id)}))
    .filter(x=>x.info);
}

// إجمالي المستحق (غير المسدد) لمورد معيّن من جميع فواتير الشراء غير المردودة
function supplierPayable(supId){
  const purs = purchases.filter(p=>parseInt(p.supplier_id)===parseInt(supId) && p.status!=='مردود');
  return purs.reduce((t,p)=>t + Math.max(0, (p.total||0)-(p.paid||0)), 0);
}

// الموردون الذين تجاوزت مستحقاتهم حد التنبيه المحدد بالإعدادات
function getSuppliersOverAlertThreshold(){
  const threshold = parseFloat(sysSettings.supplier_payable_alert_threshold||5000);
  return suppliers
    .map(s=>({supplier:s, payable:supplierPayable(s.id)}))
    .filter(x=>x.payable >= threshold && x.payable > 0)
    .sort((a,b)=>b.payable-a.payable);
}

// عرض آخر 3 أسعار شراء سابقة لنفس المنتج من نفس المورد — لمساعدة المستخدم على المقارنة عند إدخال فاتورة جديدة
function showPriceHistory(productId, supplierId, targetDivId){
  const el = document.getElementById(targetDivId);
  if(!el) return;
  if(!productId || !supplierId){ el.innerHTML=''; return; }
  const rowsFound = [];
  purchases
    .filter(p=>parseInt(p.supplier_id)===parseInt(supplierId))
    .sort((a,b)=> (b.date||'').localeCompare(a.date||''))
    .forEach(p=>{
      (p.items||[]).forEach(it=>{
        if(parseInt(it.product_id)===parseInt(productId)) rowsFound.push({price:it.price, date:p.date});
      });
    });
  if(!rowsFound.length){ el.innerHTML = '<span style="color:#475569;">لا يوجد سجل شراء سابق لهذا المنتج من هذا المورد</span>'; return; }
  const last3 = rowsFound.slice(0,3);
  el.innerHTML = '📊 آخر أسعار شراء من هذا المورد: ' + last3.map(r=>`<span style="color:#52b788;font-weight:700;">${r.price.toLocaleString()} ${cur()}</span> <span style="color:#475569;">(${r.date})</span>`).join('، ');
}

// شارة تنبيه لتاريخ صلاحية المنتج (منتهي / قريب الانتهاء خلال 30 يوم)
function expiryBadge(p){
  if(!p.expiry_date) return '';
  const days = Math.ceil((new Date(p.expiry_date) - new Date()) / 86400000);
  if(days < 0)  return `<span class="badge r" style="font-size:10px;">⏰ منتهي الصلاحية</span>`;
  if(days <= 30) return `<span class="badge y" style="font-size:10px;">⏰ ينتهي خلال ${days} يوم</span>`;
  return '';
}

async function loadAll(){
  loading=true; render();
  try{
    const [p,s,cu,pu,sl,st,pays,cfg,expCats,exps,emps,payr,recExp,svcOrd] = await Promise.all([
      api('GET','/api/products'), api('GET','/api/suppliers'), api('GET','/api/customers'),
      api('GET','/api/purchases'), api('GET','/api/sales'), api('GET','/api/dashboard'),
      api('GET','/api/payments'), api('GET','/api/settings'),
      api('GET','/api/expense_categories'), api('GET','/api/expenses'),
      api('GET','/api/employees'), api('GET','/api/payroll'), api('GET','/api/recurring_expenses'),
      api('GET','/api/service_orders')
    ]);
    products=p; suppliers=s; customers=cu; purchases=pu; sales=sl; stats=st;
    expenseCategories=expCats; expenses=exps; employees=emps; payrollRecords=payr; recurringExpenses=recExp;
    serviceOrders=svcOrd;
    sysSettings = {...sysSettings, ...cfg};
    // جلب المستخدمين إن كان أدمن
    if(USER?.role==='admin'){
      try{ sysUsers = await api('GET','/api/users'); }catch(e){}
    }
    // إضافة المدفوع والمتبقي لكل فاتورة شراء
    purchases.forEach(pur=>{
      const purPays = pays.filter(x=>x.ref_type==='purchase'&&x.ref_id===pur.id);
      pur.paid      = purPays.reduce((t,x)=>t+x.amount,0);
      pur.remaining = Math.max(0, (pur.total||0) - pur.paid);
    });
    // إضافة المدفوع والمتبقي لكل فاتورة بيع
    sales.forEach(sale=>{
      const salePays = pays.filter(x=>x.ref_type==='sale'&&x.ref_id===sale.id);
      sale.paid      = salePays.reduce((t,x)=>t+x.amount,0);
      sale.remaining = Math.max(0, (sale.total||0) - sale.paid);
    });
    // إضافة المدفوع والمتبقي لكل طلب خدمة
    serviceOrders.forEach(so=>{
      const soPays = pays.filter(x=>x.ref_type==='service'&&x.ref_id===so.id);
      so.paid      = soPays.reduce((t,x)=>t+x.amount,0);
      so.remaining = Math.max(0, (so.service_fee||0) - so.paid);
    });
  }catch(e){console.error(e);}
  loading=false; render();
}

function render(){
  try{
    const el=document.getElementById('app');
    if(!el) return;
    if(!TOKEN){el.innerHTML=loginHTML(); bindLogin(); return;}
    el.innerHTML=appHTML(); bindApp();
  }catch(err){
    console.error('Render error:', err);
    const el=document.getElementById('app');
    if(el) el.innerHTML='<div style="padding:40px;text-align:center;color:#f87171;">'
      +'<div style="font-size:48px;margin-bottom:16px;">⚠️</div>'
      +'<div style="font-size:18px;font-weight:700;margin-bottom:8px;">خطأ في التحميل</div>'
      +'<div style="color:#64748b;margin-bottom:20px;">'+err.message+'</div>'
      +'<button class="btn p" onclick="location.reload()">🔄 إعادة التحميل</button>'
      +'</div>';
  }
}

// ── LOGIN ──────────────────────────────────────
function loginHTML(){
  return `<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1117;">
  <div style="width:380px;padding:40px;background:#161923;border-radius:18px;border:1px solid #1e2537;box-shadow:0 24px 64px rgba(0,0,0,.5);">
    <div style="text-align:center;margin-bottom:28px;">
      <div style="width:56px;height:56px;background:linear-gradient(135deg,#2d6a4f,#1b4332);border-radius:14px;display:flex;align-items:center;justify-content:center;margin:0 auto 14px;">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
      </div>
      <div style="font-size:22px;font-weight:900;color:#f1f5f9;">نظام ادارة المخازن</div>
      <div style="color:#52b788;font-size:13px;margin-top:4px;">ادارة متكاملة للمخازن والمحاسبة</div>
    </div>
    <div id="lerr"></div>
    <div style="margin-bottom:14px;">
      <label class="lbl">اسم المستخدم</label>
      <input class="inp" id="lu" type="text" autocomplete="off" spellcheck="false"
        style="height:44px;font-size:15px;" placeholder="admin"/>
    </div>
    <div style="margin-bottom:22px;">
      <label class="lbl">كلمة المرور</label>
      <div style="position:relative;">
        <input class="inp" id="lp" type="text" autocomplete="off" spellcheck="false"
          id="lp"
          style="height:44px;font-size:15px;padding-left:44px;-webkit-text-security:disc;text-security:disc;"
          placeholder="••••••••"/>
        <button type="button" id="lp-eye"
          style="position:absolute;left:10px;top:50%;transform:translateY(-50%);
                 background:none;border:none;color:#64748b;cursor:pointer;padding:4px;"
          onclick="togglePwVis()">
          <svg id="eye-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
          </svg>
        </button>
      </div>
    </div>
    <button class="btn p" id="lbtn" style="width:100%;justify-content:center;height:46px;font-size:16px;font-weight:800;">
      دخول
    </button>
    <div style="text-align:center;margin-top:14px;font-size:12px;color:#475569;">
      افتراضي: <span style="color:#52b788;font-family:monospace;">admin</span> /
      <span style="color:#52b788;font-family:monospace;">admin123</span>
    </div>
  </div></div>`;
}

window.togglePwVis = function(){
  const inp = document.getElementById('lp');
  const ico = document.getElementById('eye-icon');
  if(!inp) return;
  const hidden = inp.style.webkitTextSecurity === 'disc' || inp.style.textSecurity === 'disc';
  if(hidden){
    inp.style.webkitTextSecurity = 'none';
    inp.style.textSecurity = 'none';
    if(ico) ico.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
  } else {
    inp.style.webkitTextSecurity = 'disc';
    inp.style.textSecurity = 'disc';
    if(ico) ico.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
  }
  inp.focus();
};

function bindLogin(){
  const lu = document.getElementById('lu');
  const lp = document.getElementById('lp');
  // القيم الافتراضية
  if(lu) lu.value = 'admin';
  if(lp) lp.value = 'admin123';

  const go = async()=>{
    const u   = lu?.value?.trim()||'';
    const p   = lp?.value||'';
    const btn = document.getElementById('lbtn');
    const err = document.getElementById('lerr');
    if(!u){ if(err) err.innerHTML='<div class="err">أدخل اسم المستخدم</div>'; lu?.focus(); return; }
    if(!p){ if(err) err.innerHTML='<div class="err">أدخل كلمة المرور</div>'; lp?.focus(); return; }
    btn.disabled = true; btn.textContent = '⏳ جاري الدخول...';
    if(err) err.innerHTML = '';
    try{
      const r    = await fetch('/api/auth/login',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({username:u, password:p})});
      const data = await r.json();
      if(!r.ok) throw new Error(data.detail||'خطأ في تسجيل الدخول');
      TOKEN = data.access_token;
      USER  = data.user;
      localStorage.setItem('token', TOKEN);
      await loadAll();
    }catch(e){
      if(err) err.innerHTML = `<div class="err">❌ ${e.message}</div>`;
      btn.disabled    = false;
      btn.textContent = 'دخول';
      lp?.focus();
      lp?.select();
    }
  };

  document.getElementById('lbtn').onclick = go;
  lp?.addEventListener('keydown', e=>{ if(e.key==='Enter') go(); });
  lu?.addEventListener('keydown', e=>{ if(e.key==='Enter') lp?.focus(); });
  // تركيز على كلمة المرور لأن الاسم محدد مسبقاً
  setTimeout(()=>lp?.focus(), 50);
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
  {id:'expenses',label:'المصاريف',ic:'M17 9V7a5 5 0 00-10 0v2M5 9h14l1 12H4z'},
  {id:'services',label:'التركيب والصيانة',ic:'M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z'},
  {id:'reports',label:'التقارير',ic:'M18 20V10M12 20V4M6 20v-6'},
  {id:'settings',label:'الإعدادات',ic:'M12 2a10 10 0 100 20A10 10 0 0012 2zM12 8v4l3 3'},
];

function ic(d,s=18){
  return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  ${d.split('M').filter(Boolean).map(p=>`<path d="M${p}"/>`).join('')}</svg>`;
}

function appHTML(){
  const w=sideOpen?224:58;
  const role = USER?.role||'user';
  // الصفحات المسموح بها لكل دور
  const allowed = role==='admin'
    ? ['dashboard','products','warehouse','purchases','pos','suppliers','customers','accounting','expenses','services','reports','settings']
    : role==='cashier'
    ? ['pos','products']
    : ['dashboard','products','warehouse','purchases','pos','suppliers','customers','accounting','expenses','services','reports'];
  const visibleNav = NAV.filter(n=>allowed.includes(n.id));
  // إعادة توجيه إذا الصفحة الحالية غير مسموح بها
  if(!allowed.includes(page)) page = allowed[0];
  return `<div style="display:flex;height:100vh;overflow:hidden;">
  <aside style="width:${w}px;min-width:${w}px;background:#0d1018;border-left:1px solid #1e2537;transition:all .25s;display:flex;flex-direction:column;overflow:hidden;">
    <div style="padding:16px 12px;border-bottom:1px solid #1e2537;display:flex;align-items:center;gap:10px;">
      <div style="width:32px;height:32px;min-width:32px;background:linear-gradient(135deg,#2d6a4f,#1b4332);border-radius:8px;display:flex;align-items:center;justify-content:center;">
        ${ic('M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2zM9 22V12h6v10',15)}
      </div>
      ${sideOpen?`<div><div style="font-size:13px;font-weight:800;color:#f1f5f9;">${sysSettings.system_name||'نظام المخازن'}</div><div style="font-size:11px;color:#52b788;">${USER?.full_name||'مرحبا'}</div></div>`:''}
    </div>
    <div style="flex:1;padding:8px 6px;overflow-y:auto;display:flex;flex-direction:column;gap:2px;">
      ${visibleNav.map(n=>`<div class="nav${page===n.id?' on':''}" data-page="${n.id}" title="${!sideOpen?n.label:''}">${ic(n.ic,17)}${sideOpen?`<span>${n.label}</span>`:''}</div>`).join('')}
    </div>
    <div style="padding:8px 6px;border-top:1px solid #1e2537;display:flex;flex-direction:column;gap:4px;">
      ${sideOpen?`<div style="padding:6px 10px;font-size:11px;color:#475569;display:flex;align-items:center;gap:6px;">
        <span class="badge ${role==='admin'?'r':role==='cashier'?'b':'g'}" style="font-size:10px;">${{admin:'مدير',user:'مستخدم',cashier:'كاشير'}[role]||role}</span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">@${USER?.username||''}</span>
      </div>`:''}
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
  document.getElementById('lout').onclick=async()=>{
    try{ await api('POST','/api/auth/logout'); }catch(e){}
    TOKEN=null;USER=null;localStorage.removeItem('token');render();
  };
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
  if(page==='expenses')   return expensesHTML();
  if(page==='services')   return servicesHTML();
  if(page==='reports')    return reportsHTML();
  if(page==='settings')   return settingsHTML();
  return '';
}

// DASHBOARD
function dashHTML(){
  if(!stats) return '<div class="spin"></div>';
  return `<div class="ti">لوحة التحكم</div><div class="sub">نظرة عامة على النظام</div>
  <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:20px;">
    ${[['المبيعات',stats.total_sales,'#52b788'],['المشتريات',stats.total_purchases,'#60a5fa'],
       ['المصاريف',stats.total_expenses||0,'#f87171'],['إيراد الخدمات',stats.total_services||0,'#a78bfa'],
       ['الربح الصافي',stats.profit,stats.profit>=0?'#fbbf24':'#f87171'],['مخزون منخفض',stats.low_stock_count,'#f87171']
    ].map(([l,v,c])=>`<div class="stat"><div style="font-size:13px;color:#64748b;">${l}</div>
    <div style="font-size:19px;font-weight:800;color:${c};margin-top:7px;">${Number(v).toLocaleString()} ${l==='مخزون منخفض'?'منتج':cur()}</div></div>`).join('')}
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    <div class="card" style="padding:16px;">
      <div style="font-weight:700;color:#f1f5f9;margin-bottom:12px;">اخر المبيعات</div>
      <table><thead><tr><th>التاريخ</th><th>الاجمالي</th><th>الحالة</th></tr></thead><tbody>
      ${(stats.recent_sales||[]).map(s=>`<tr><td>${s.date}</td>
      <td>${(s.total||0).toLocaleString()} ${cur()}</td>
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
  </div>
  ${dashOverdueCard()}
  ${dashSupplierAlertCard()}
  ${dashExpensesDueCard()}
  ${svcWarrantyAlertsHTML()}`;
}

function dashOverdueCard(){
  const overdue = getOverdueCustomers();
  if(!overdue.length) return '';
  return `<div class="card" style="padding:16px;margin-top:16px;border:1px solid #5c2323;">
    <div style="font-weight:700;color:#f87171;margin-bottom:12px;">⏰ زبائن متأخرون بالسداد (${overdue.length})</div>
    ${overdue.map(({customer,info})=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e2537;">
      <div>
        <span style="font-size:13px;color:#f1f5f9;font-weight:700;">${customer.name}</span>
        <span style="font-size:11px;color:#64748b;margin-right:6px;">${info.invoiceCount} فاتورة متأخرة — منذ ${info.ageDays} يوم</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span class="badge r">${info.totalDue.toLocaleString()} ${cur()}</span>
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="copyCustomerStatement(${customer.id})">📋 نسخ كشف الحساب</button>
      </div>
    </div>`).join('')}
  </div>`;
}

// الشهر الحالي بصيغة YYYY-MM
function currentMonth(){ return new Date().toISOString().slice(0,7); }

// الموظفون النشطون اللي لسا ما انسجّل راتبهم لهذا الشهر
function getEmployeesDuePayroll(){
  const month = currentMonth();
  return employees.filter(e=>e.is_active && !payrollRecords.some(p=>parseInt(p.employee_id)===e.id && p.month===month));
}

// المصاريف المتكررة النشطة اللي لسا ما انسجّلت لهذا الشهر (بعد يوم استحقاقها)
function getRecurringExpensesDue(){
  const month = currentMonth();
  const today = new Date().getDate();
  return recurringExpenses.filter(r=>{
    if(!r.is_active) return false;
    if(today < (r.day_of_month||1)) return false;
    return !expenses.some(e=>parseInt(e.recurring_id)===r.id && (e.date||'').slice(0,7)===month);
  });
}

function dashExpensesDueCard(){
  const duePayroll = getEmployeesDuePayroll();
  const dueRecurring = getRecurringExpensesDue();
  if(!duePayroll.length && !dueRecurring.length) return '';
  const month = currentMonth();
  return `<div class="card" style="padding:16px;margin-top:16px;border:1px solid #5c2323;">
    <div style="font-weight:700;color:#f87171;margin-bottom:12px;">💸 مصاريف مستحقة لشهر ${month} (${duePayroll.length+dueRecurring.length})</div>
    ${duePayroll.map(e=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e2537;">
      <span style="font-size:13px;color:#f1f5f9;font-weight:700;">👤 راتب: ${esc(e.name)}</span>
      <div style="display:flex;align-items:center;gap:8px;">
        <span class="badge r">${(e.base_salary||0).toLocaleString()} ${cur()}</span>
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="page='expenses';render();setTimeout(()=>expTab('employees'),0)">💳 دفع الراتب</button>
      </div>
    </div>`).join('')}
    ${dueRecurring.map(r=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e2537;">
      <span style="font-size:13px;color:#f1f5f9;font-weight:700;">${r.category_icon||'📦'} ${esc(r.description)}</span>
      <div style="display:flex;align-items:center;gap:8px;">
        <span class="badge y">${(r.amount||0).toLocaleString()} ${cur()}</span>
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="page='expenses';render();setTimeout(()=>expTab('recurring'),0)">💳 تسجيل الدفعة</button>
      </div>
    </div>`).join('')}
  </div>`;
}

function dashSupplierAlertCard(){
  const list = getSuppliersOverAlertThreshold();
  if(!list.length) return '';
  return `<div class="card" style="padding:16px;margin-top:16px;border:1px solid #5c4a23;">
    <div style="font-weight:700;color:#fbbf24;margin-bottom:12px;">⚠️ موردون تجاوزت مستحقاتهم الحد المحدد (${list.length})</div>
    ${list.map(({supplier,payable})=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e2537;">
      <span style="font-size:13px;color:#f1f5f9;font-weight:700;">${supplier.name}</span>
      <div style="display:flex;align-items:center;gap:8px;">
        <span class="badge y">${payable.toLocaleString()} ${cur()}</span>
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="openAccountPay('suppliers',${supplier.id},'${supplier.name.replace(/'/g,"\\'")}')">💳 تسديد</button>
      </div>
    </div>`).join('')}
  </div>`;
}
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
    <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${esc(p.barcode)}</td>
    <td style="font-family:monospace;font-size:12px;color:#94a3b8;">${esc(p.serial)||''}</td>
    <td style="font-weight:600;color:#f1f5f9;">${esc(p.name)}${p.track_serial?' <span class="badge g" style="font-size:10px;">📟 سيريال</span>':''} ${expiryBadge(p)}</td>
    <td><span class="badge b">${esc(p.category)||''}</span></td>
    <td>${(p.buy_price||0).toLocaleString()} ${cur()}</td>
    <td style="color:#52b788;">${(p.sell_price||0).toLocaleString()} ${cur()}</td>
    <td><span class="badge ${p.stock<lowStockLimit()?'r':'g'}">${p.stock} ${esc(p.unit)}</span></td>
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
    <div class="stat"><div style="font-size:13px;color:#64748b;">قيمة المخزون</div><div style="font-size:18px;font-weight:800;color:#fbbf24;margin-top:7px;">${tv.toLocaleString()} ${cur()}</div></div>
  </div>
  ${cats.map(cat=>{const ps=products.filter(p=>(p.category||'غير مصنف')===cat); return `
  <div class="card" style="margin-bottom:12px;padding:14px;">
    <div style="font-weight:700;color:#52b788;margin-bottom:10px;">${cat}</div>
    <table><thead><tr><th>المنتج</th><th>الباركود</th><th>الكمية</th><th>التكلفة</th><th>القيمة</th><th>الحالة</th></tr></thead><tbody>
    ${ps.map(p=>`<tr>
      <td style="font-weight:600;">${p.name} ${expiryBadge(p)}</td>
      <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${p.barcode}</td>
      <td>${p.stock} ${p.unit}</td>
      <td>${(p.buy_price||0).toLocaleString()} ${cur()}</td>
      <td style="color:#52b788;font-weight:600;">${(p.stock*p.buy_price).toLocaleString()} ${cur()}</td>
      <td><span class="badge ${p.stock===0?'r':p.stock<lowStockLimit()?'y':'g'}">${p.stock===0?'نفد':p.stock<lowStockLimit()?'منخفض':'جيد'}</span></td>
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
      الاجمالي: ${purchases.reduce((s,p)=>s+p.total,0).toLocaleString()} ${cur()}
    </div>
  </div>`;
}

function purSum(list){
  const t=list.reduce((s,p)=>s+p.total,0);
  const paid=list.filter(p=>p.status==='مدفوع').reduce((s,p)=>s+p.total,0);
  const pend=list.filter(p=>p.status==='معلق').reduce((s,p)=>s+p.total,0);
  return `
  <div class="stat"><div style="font-size:12px;color:#64748b;">اجمالي الفترة</div><div style="font-size:17px;font-weight:800;color:#60a5fa;margin-top:6px;">${t.toLocaleString()} ${cur()}</div></div>
  <div class="stat"><div style="font-size:12px;color:#64748b;">مدفوع</div><div style="font-size:17px;font-weight:800;color:#52b788;margin-top:6px;">${paid.toLocaleString()} ${cur()}</div></div>
  <div class="stat"><div style="font-size:12px;color:#64748b;">معلق</div><div style="font-size:17px;font-weight:800;color:#fbbf24;margin-top:6px;">${pend.toLocaleString()} ${cur()}</div></div>`;
}

function purRows(list){
  if(!list.length) return '<tr><td colspan="7" style="text-align:center;color:#475569;padding:28px;">لا توجد مشتريات في هذه الفترة</td></tr>';
  return list.map(p=>`
  <tr>
    <td style="color:#64748b;font-weight:600;">#${p.id}</td>
    <td style="color:#f1f5f9;font-weight:700;font-size:14px;">📅 ${p.date}</td>
    <td style="color:#60a5fa;font-weight:600;">${suppliers.find(s=>s.id===p.supplier_id)?.name||'—'}</td>
    <td><span class="badge b">${p.items?.length||0} صنف</span></td>
    <td style="font-weight:800;color:#f1f5f9;">${(p.total||0).toLocaleString()} ${cur()}</td>
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
        ${groupInvoiceItems(p.items||[]).map(item=>{
          const pr=products.find(x=>x.id===item.product_id);
          return `<tr>
            <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${item.barcode||pr?.barcode||'—'}</td>
            <td style="color:#f1f5f9;font-weight:600;">${esc(item.product_name)||esc(pr?.name)||'—'}
              ${item.serials&&item.serials.length?`<div style="font-size:10px;color:#52b788;font-family:monospace;margin-top:2px;">📟 ${item.serials.map(esc).join(' ، ')}</div>`:''}
            </td>
            <td style="color:#94a3b8;">${item.qty} ${item.unit||pr?.unit||''}</td>
            <td>${(item.price||0).toLocaleString()} ${cur()}</td>
            <td style="color:#52b788;font-weight:700;">${(item.qty*item.price).toLocaleString()} ${cur()}</td>
          </tr>`;}).join('')||'<tr><td colspan="5" style="color:#64748b;text-align:center;padding:10px;">لا توجد اصناف</td></tr>'}
        </tbody></table>
        ${p.notes?`<div style="margin-top:8px;color:#64748b;font-size:13px;">📝 ${esc(p.notes)}</div>`:''}
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
  // تجميع الفئات
  const cats = [...new Set(products.map(p=>p.category||'عام'))];

  return `<div style="display:grid;grid-template-columns:180px 1fr 480px;gap:0;height:calc(100vh - 44px);overflow:hidden;">

  <!-- ══ يسار: الأصناف/الفئات ══ -->
  <div style="background:#0d1018;border-left:1px solid #1e2537;display:flex;flex-direction:column;overflow:hidden;">
    <div style="padding:12px 10px;border-bottom:1px solid #1e2537;">
      <div style="font-size:12px;font-weight:800;color:#52b788;margin-bottom:8px;letter-spacing:.5px;">📂 الأصناف</div>
      <input class="inp" id="cat-search" placeholder="بحث فئة..." style="font-size:12px;padding:6px 10px;"/>
    </div>
    <div style="flex:1;overflow-y:auto;padding:6px;">
      <div onclick="filterCat('')" id="cat-all"
        style="padding:8px 12px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:700;
               color:#52b788;background:rgba(45,106,79,.2);border:1px solid rgba(45,106,79,.3);
               margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;">
        <span>الكل</span>
        <span class="badge g" style="font-size:10px;">${products.length}</span>
      </div>
      ${cats.map(cat=>{
        const count = products.filter(p=>(p.category||'عام')===cat).length;
        return `<div onclick="filterCat('${cat}')" data-cat="${cat}"
          style="padding:8px 12px;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600;
                 color:#94a3b8;border:1px solid transparent;margin-bottom:3px;
                 display:flex;justify-content:space-between;align-items:center;transition:all .15s;"
          onmouseover="this.style.background='#161923';this.style.color='#f1f5f9'"
          onmouseout="this.style.background='';this.style.color='#94a3b8'">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${cat}</span>
          <span class="badge b" style="font-size:10px;min-width:22px;text-align:center;">${count}</span>
        </div>`;
      }).join('')}
    </div>
  </div>

  <!-- ══ وسط: منتجات + بحث ══ -->
  <div style="display:flex;flex-direction:column;overflow:hidden;border-left:1px solid #1e2537;">
    <!-- رأس -->
    <div style="padding:10px 14px;background:#0d1018;border-bottom:1px solid #1e2537;display:flex;align-items:center;gap:10px;">
      <div style="flex:1;position:relative;">
        <input class="inp" id="pi"
          placeholder="🔍  ابحث أو امسح الباركود..."
          style="height:42px;font-size:14px;"
          autocomplete="off"/>
        <div id="pos-suggest" style="display:none;position:absolute;top:100%;right:0;left:0;
          background:#1e2130;border:1px solid #2d6a4f;border-radius:0 0 10px 10px;
          max-height:240px;overflow-y:auto;z-index:200;box-shadow:0 8px 28px rgba(0,0,0,.5);"></div>
      </div>
      <button class="btn s" style="font-size:12px;padding:6px 12px;height:42px;white-space:nowrap;" onclick="openCameraScan()">📷 مسح بالكاميرا</button>
      <button class="btn s" style="font-size:12px;padding:6px 12px;height:42px;white-space:nowrap;" onclick="openSalesList()">📋 المبيعات</button>
    </div>
    <!-- عنوان الفئة الحالية -->
    <div id="pos-cat-title" style="padding:7px 14px;font-size:12px;color:#64748b;background:#0f1018;border-bottom:1px solid #1a1d27;display:flex;justify-content:space-between;align-items:center;">
      <span>عرض جميع المنتجات — <span style="color:#52b788;">${products.length} منتج</span></span>
      <span style="font-size:11px;color:#475569;">
        <span class="badge b" style="font-size:10px;">F1</span> بحث
        <span class="badge g" style="font-size:10px;margin-right:4px;">F2</span> إتمام البيع
        <span class="badge r" style="font-size:10px;margin-right:4px;">F3</span> حذف آخر صنف
        <span class="badge y" style="font-size:10px;margin-right:4px;">F4</span> تعليق
      </span>
    </div>
    <!-- شبكة المنتجات -->
    <div id="pos-grid" style="flex:1;overflow-y:auto;padding:10px;display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;align-content:start;">
      ${products.map(p=>posProductCard(p)).join('')}
    </div>
  </div>

  <!-- ══ يمين: السلة ══ -->
  <div style="display:flex;flex-direction:column;overflow:hidden;background:#0d1018;">
    <!-- رأس السلة -->
    <div style="padding:10px 14px;background:#161923;border-bottom:1px solid #1e2537;display:flex;align-items:center;justify-content:space-between;">
      <div style="font-size:14px;font-weight:800;color:#f1f5f9;">
        🛒 السلة <span id="cc" class="badge b" style="display:none;font-size:11px;"></span>
      </div>
      <div style="display:flex;gap:4px;">
        <button class="btn s" style="padding:3px 8px;font-size:11px;" id="phl-btn">⏸️ تعليق</button>
        <button class="btn s" style="padding:3px 10px;font-size:11px;color:#f87171;border-color:#3d1515;" id="pcl">🗑️</button>
      </div>
    </div>
    <!-- الفواتير المعلقة (تظهر عند وجودها) -->
    <div id="phl-area" style="display:none;">
      <div style="padding:6px 10px;background:#1a2e22;border-bottom:1px solid #1e2537;display:flex;justify-content:space-between;align-items:center;">
        <span style="font-size:11px;font-weight:700;color:#52b788;">⏸️ فواتير معلقة <span id="phl-count" class="badge g" style="font-size:10px;"></span></span>
        <button class="btn s" style="padding:2px 8px;font-size:10px;" onclick="clearAllHeld()">✕ إخفاء الكل</button>
      </div>
      <div id="phl-list" style="max-height:140px;overflow-y:auto;"></div>
    </div>
    <!-- أصناف السلة -->
    <div id="ci" style="flex:1;overflow-y:auto;">
      <div style="color:#475569;text-align:center;padding:40px 20px;font-size:13px;">
        🛒<br/>السلة فارغة<br/>
        <span style="font-size:11px;color:#334155;">اضغط على منتج لإضافته</span>
      </div>
    </div>
    <!-- تذييل الفاتورة -->
    <div style="padding:12px;border-top:1px solid #1e2537;background:#161923;">
      <!-- الزبون + الدفع -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:7px;">
        <div>
          <label class="lbl" style="font-size:10px;margin-bottom:3px;">الزبون</label>
          <div style="display:flex;gap:4px;">
            <select class="inp" id="pc" style="font-size:12px;padding:6px 8px;flex:1;">
              <option value="">-- زبون عام --</option>
              ${customers.map(c=>`<option value="${c.id}">${c.name}</option>`).join('')}
            </select>
            <button class="btn s" id="pqc-btn" style="padding:3px 8px;font-size:13px;" title="إضافة زبون جديد">+</button>
          </div>
        </div>
        <div>
          <label class="lbl" style="font-size:10px;margin-bottom:3px;">طريقة الدفع</label>
          <select class="inp" id="pm" style="font-size:12px;padding:6px 8px;">
            ${['نقدي','بطاقة','تحويل','آجل'].map(m=>`<option>${m}</option>`).join('')}
          </select>
        </div>
      </div>
      <!-- ملاحظات -->
      <input class="inp" id="pos-notes" placeholder="ملاحظات الفاتورة..." style="font-size:12px;padding:6px 10px;margin-bottom:8px;width:100%;"/>
      <!-- خصم الفاتورة -->
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
        <span style="font-size:11px;color:#64748b;white-space:nowrap;">💰 خصم الفاتورة</span>
        <input class="inp" id="pos-inv-disc" type="number" min="0" step="1" value="0"
          placeholder="0" style="flex:1;font-size:12px;padding:5px 8px;"
          onchange="setInvDiscount(this.value)"/>
        <span style="font-size:10px;color:#475569;">${cur()}</span>
      </div>
      <!-- الإجمالي -->
      <div style="background:linear-gradient(135deg,#1a2e22,#161923);border-radius:10px;padding:10px 14px;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-size:10px;color:#64748b;">الإجمالي</div>
            <div id="ct" style="font-size:26px;font-weight:900;color:#52b788;line-height:1;">0 <span style="font-size:12px;">${cur()}</span></div>
          </div>
          <div style="text-align:left;font-size:11px;color:#64748b;">
            <div id="pos-items-count"></div>
            <div id="pos-unit-count"></div>
          </div>
        </div>
      </div>
      <button class="btn p" id="pco" style="width:100%;justify-content:center;height:46px;font-size:16px;font-weight:800;letter-spacing:.5px;">
        ✅ إتمام البيع
      </button>
    </div>
  </div>

  </div>`;
}

function posProductCard(p){
  const border = p.stock===0 ? '#3d1515' : p.stock<5 ? '#3d2e0a' : '#1e2537';
  const hoverBg = p.stock===0 ? '#1a1010' : '#1a2520';
  return `<div onclick="addCart(${p.id})"
    style="background:#161923;border:1px solid ${border};border-radius:10px;padding:10px;
           cursor:pointer;transition:all .15s;user-select:none;"
    onmouseover="this.style.borderColor='#2d6a4f';this.style.background='${hoverBg}';this.style.transform='translateY(-1px)'"
    onmouseout="this.style.borderColor='${border}';this.style.background='#161923';this.style.transform=''">
    <div style="font-size:12px;font-weight:700;color:#f1f5f9;margin-bottom:3px;
      overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${p.name}">${p.track_serial?'📟 ':''}${p.name}</div>
    <div style="font-size:10px;color:#334155;margin-bottom:6px;font-family:monospace;">${p.barcode}</div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span style="color:#52b788;font-weight:800;font-size:13px;">${(p.sell_price||0).toLocaleString()}</span>
      <span class="badge ${p.stock===0?'r':p.stock<5?'y':'g'}" style="font-size:10px;padding:2px 5px;">
        ${p.stock===0?'نفد':p.stock}
      </span>
    </div>
  </div>`;
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
  tb.innerHTML=f.map(x=>{
    let nameExtra = '';
    if(type==='customers'){
      if(customerTier(x.id)==='vip') nameExtra += ' <span class="badge y" style="font-size:10px;">⭐ مميز</span>';
      const od = customerOverdueInfo(x.id);
      if(od) nameExtra += ` <span class="badge r" style="font-size:10px;">⏰ متأخر ${od.ageDays} يوم</span>`;
    }
    if(type==='suppliers'){
      const payable = supplierPayable(x.id);
      const threshold = parseFloat(sysSettings.supplier_payable_alert_threshold||5000);
      if(payable >= threshold && payable > 0) nameExtra += ` <span class="badge y" style="font-size:10px;">⚠️ مستحق ${payable.toLocaleString()} ${cur()}</span>`;
    }
    return `<tr>
    <td style="font-weight:700;color:#f1f5f9;">${esc(x.name)}${nameExtra}</td>
    <td style="color:#60a5fa;">${esc(x.phone)||''}</td>
    <td><span class="badge b">${esc(x.city)||''}</span></td>
    <td><span class="badge ${x.balance!==0?'y':'g'}">${Math.abs(x.balance||0).toLocaleString()} ${cur()}</span></td>
    <td><div style="display:flex;gap:5px;">
      <button class="btn p" style="padding:4px 9px;font-size:12px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openAccountPay('${type}',${x.id},'${x.name}')">💳 دفعة</button>
      ${type==='customers'?`<button class="btn s" style="padding:4px 8px;" onclick="copyCustomerStatement(${x.id})" title="نسخ كشف حساب جاهز للإرسال">📋</button>`:''}
      <button class="btn s" style="padding:4px 8px;" onclick="openEdit('${type}',${x.id})">✏️</button>
      <button class="btn d" style="padding:4px 8px;" onclick="delItem('${type}',${x.id})">🗑️</button>
    </div></td></tr>`;
  }).join('')||'<tr><td colspan="5" style="text-align:center;color:#475569;padding:28px;">لا توجد بيانات</td></tr>';
}

// ACCOUNTING
function accountingHTML(){
  const ts = sales.reduce((s,x)=>s+x.total, 0);
  const tp = purchases.reduce((s,x)=>s+x.total, 0);

  // حساب إجمالي مشتريات كل مورد من الفواتير الفعلية
  supStats = suppliers.map(s=>{
    const purList = purchases.filter(p=> parseInt(p.supplier_id)===s.id);
    const total   = purList.reduce((t,p)=>t+p.total, 0);
    const paid    = purList.filter(p=>p.status==='مدفوع').reduce((t,p)=>t+p.total, 0);
    const pending = purList.filter(p=>p.status!=='مدفوع').reduce((t,p)=>t+p.total, 0);
    return {...s, purTotal:total, purPaid:paid, purPending:pending, purCount:purList.length};
  });

  // حساب إجمالي مبيعات كل زبون من الفواتير الفعلية
  custStats = customers.map(c=>{
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
      <div style="font-size:18px;font-weight:800;color:#52b788;margin-top:6px;">${ts.toLocaleString()} ${cur()}</div>
    </div>
    <div class="stat">
      <div style="font-size:12px;color:#64748b;">إجمالي المشتريات</div>
      <div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:6px;">${tp.toLocaleString()} ${cur()}</div>
    </div>
    <div class="stat">
      <div style="font-size:12px;color:#64748b;">مستحق للموردين</div>
      <div style="font-size:18px;font-weight:800;color:#f87171;margin-top:6px;">${totalPending.toLocaleString()} ${cur()}</div>
    </div>
    <div class="stat">
      <div style="font-size:12px;color:#64748b;">مستحق من الزبائن</div>
      <div style="font-size:18px;font-weight:800;color:#fbbf24;margin-top:6px;">${totalReceive.toLocaleString()} ${cur()}</div>
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
          <span style="font-weight:800;color:#60a5fa;font-size:14px;">${s.purTotal.toLocaleString()} ${cur()}</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <span class="badge b">${s.purCount} فاتورة</span>
          ${s.purPaid>0?`<span class="badge g">مدفوع: ${s.purPaid.toLocaleString()} ${cur()}</span>`:''}
          ${s.purPending>0?`<span class="badge r">معلق: ${s.purPending.toLocaleString()} ${cur()}</span>`:''}
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
          <span style="font-weight:800;color:#52b788;font-size:14px;">${c.saleTotal.toLocaleString()} ${cur()}</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <span class="badge b">${c.saleCount} فاتورة</span>
          ${c.salePaid>0?`<span class="badge g">مدفوع: ${c.salePaid.toLocaleString()} ${cur()}</span>`:''}
          ${c.salePending>0?`<span class="badge y">معلق: ${c.salePending.toLocaleString()} ${cur()}</span>`:''}
          ${c.saleTotal===0?`<span class="badge y">لا توجد مبيعات</span>`:''}
        </div>
      </div>`).join('') : '<div style="color:#64748b;text-align:center;padding:20px;">لا يوجد زبائن</div>'}
    </div>

  </div></div>
  </div>`;
}

// ══════════════════════════════════════════════
//  صفحة المصاريف (عام / الموظفين والرواتب / متكرر)
// ══════════════════════════════════════════════
let _expTab = 'general';

function expensesHTML(){
  const today = new Date().toISOString().slice(0,7);
  const monthExpenses = expenses.filter(e=>(e.date||'').slice(0,7)===today);
  const monthTotal = monthExpenses.reduce((s,e)=>s+(e.amount||0),0);
  const catTotals = {};
  expenses.forEach(e=>{ const k=e.category_name||'أخرى'; catTotals[k]=(catTotals[k]||0)+(e.amount||0); });
  const topCat = Object.entries(catTotals).sort((a,b)=>b[1]-a[1])[0];
  return `<div class="ti">المصاريف</div><div class="sub">إدارة المصاريف التشغيلية والرواتب</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px;">
    <div class="stat"><div style="font-size:12px;color:#64748b;">إجمالي كل الأوقات</div><div style="font-size:18px;font-weight:800;color:#f87171;margin-top:6px;">${expenses.reduce((s,e)=>s+(e.amount||0),0).toLocaleString()} ${cur()}</div></div>
    <div class="stat"><div style="font-size:12px;color:#64748b;">مصاريف الشهر الحالي</div><div style="font-size:18px;font-weight:800;color:#fbbf24;margin-top:6px;">${monthTotal.toLocaleString()} ${cur()}</div></div>
    <div class="stat"><div style="font-size:12px;color:#64748b;">أكبر تصنيف</div><div style="font-size:16px;font-weight:800;color:#60a5fa;margin-top:6px;">${topCat?esc(topCat[0])+' — '+topCat[1].toLocaleString()+' '+cur():'—'}</div></div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:16px;">
    <button class="btn ${_expTab==='general'?'p':'s'}" id="exp-tab-general" onclick="expTab('general')">📦 عام</button>
    <button class="btn ${_expTab==='employees'?'p':'s'}" id="exp-tab-employees" onclick="expTab('employees')">👤 الموظفون والرواتب</button>
    <button class="btn ${_expTab==='recurring'?'p':'s'}" id="exp-tab-recurring" onclick="expTab('recurring')">🔁 مصاريف متكررة</button>
  </div>
  <div id="exp-content">${_expTab==='employees'?expEmployeesTabHTML():_expTab==='recurring'?expRecurringTabHTML():expGeneralTabHTML()}</div>`;
}

window.expTab = function(tab){
  _expTab = tab;
  document.querySelectorAll('[id^="exp-tab-"]').forEach(b=>{
    b.className = b.id==='exp-tab-'+tab ? 'btn p' : 'btn s';
  });
  const el = document.getElementById('exp-content');
  if(!el) return;
  if(tab==='general')   el.innerHTML = expGeneralTabHTML();
  if(tab==='employees') el.innerHTML = expEmployeesTabHTML();
  if(tab==='recurring') el.innerHTML = expRecurringTabHTML();
  bindExpensesTab();
};

// ── تبويب: المصاريف العامة ──
function expGeneralTabHTML(){
  const today = new Date().toISOString().slice(0,10);
  const first = today.slice(0,7)+'-01';
  return `
  <div class="card" style="padding:16px;margin-bottom:14px;">
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;align-items:end;">
      <div><label class="lbl">من تاريخ</label><input class="inp" id="exp-from" type="date" value="${first}"/></div>
      <div><label class="lbl">إلى تاريخ</label><input class="inp" id="exp-to" type="date" value="${today}"/></div>
      <div><label class="lbl">التصنيف</label>
        <select class="inp" id="exp-cat-filter"><option value="">الكل</option>
        ${expenseCategories.map(c=>`<option value="${c.id}">${c.icon} ${esc(c.name)}</option>`).join('')}</select>
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn p" id="exp-filter-btn" style="flex:1;justify-content:center;">🔍 فلترة</button>
        <button class="btn p" id="exp-add-btn" style="flex:1;justify-content:center;background:linear-gradient(135deg,#1e40af,#1e3a8a);">+ مصروف</button>
      </div>
    </div>
  </div>
  <div id="exp-list-body">${expListHTML(expenses)}</div>`;
}

function expListHTML(list){
  const total = list.reduce((s,e)=>s+(e.amount||0),0);
  return `<div class="card" style="overflow:hidden;">
    <table>
      <thead><tr><th>التاريخ</th><th>التصنيف</th><th>الوصف</th><th>المبلغ</th><th>طريقة الدفع</th><th>ملاحظات</th><th>إجراءات</th></tr></thead>
      <tbody>
      ${list.map(e=>`<tr>
        <td style="font-weight:600;">${e.date}</td>
        <td><span class="badge b">${e.category_icon||'📦'} ${esc(e.category_name)||'—'}</span></td>
        <td style="font-weight:600;color:#f1f5f9;">${esc(e.description)}${e.payroll_id?' <span class="badge g" style="font-size:10px;">راتب</span>':''}${e.recurring_id?' <span class="badge y" style="font-size:10px;">متكرر</span>':''}</td>
        <td style="font-weight:800;color:#f87171;">${(e.amount||0).toLocaleString()} ${cur()}</td>
        <td><span class="badge ${e.payment_method==='نقدي'?'g':e.payment_method==='شيك'?'b':'y'}">${e.payment_method}</span></td>
        <td style="font-size:12px;color:#64748b;">${esc(e.notes)||''}</td>
        <td><div style="display:flex;gap:4px;">
          ${!e.payroll_id?`<button class="btn s" style="padding:4px 8px;font-size:11px;" onclick="openEditExpense(${e.id})">✏️</button>
          <button class="btn d" style="padding:4px 8px;font-size:11px;" onclick="deleteExpense(${e.id})">🗑️</button>`
          :`<span style="font-size:11px;color:#64748b;">من كشف راتب</span>`}
        </div></td>
      </tr>`).join('')||'<tr><td colspan="7" style="text-align:center;color:#475569;padding:24px;">لا توجد مصاريف</td></tr>'}
      </tbody>
    </table>
    <div style="text-align:left;padding:10px 16px;font-size:15px;font-weight:800;color:#f87171;border-top:1px solid #1e2537;">
      الإجمالي: ${total.toLocaleString()} ${cur()}
    </div>
  </div>`;
}

window.applyExpFilter = function(){
  const from = document.getElementById('exp-from')?.value||'';
  const to   = document.getElementById('exp-to')?.value||'';
  const cat  = document.getElementById('exp-cat-filter')?.value||'';
  let list = expenses.filter(e=>(!from||e.date>=from) && (!to||e.date<=to));
  if(cat) list = list.filter(e=>String(e.category_id)===String(cat));
  const el = document.getElementById('exp-list-body');
  if(el) el.innerHTML = expListHTML(list);
};

window.openEditExpense = function(id){
  const e = expenses.find(x=>x.id===id);
  if(!e){ alert('المصروف غير موجود'); return; }
  MS = {type:'expenseform', data: e};
  render();
};
window.deleteExpense = async function(id){
  if(!confirm('هل تريد حذف هذا المصروف؟')) return;
  try{ await api('DELETE','/api/expenses/'+id); await loadAll(); expTab('general'); }
  catch(e){ alert('خطأ: '+e.message); }
};

// ── تبويب: الموظفون والرواتب ──
function expEmployeesTabHTML(){
  const month = currentMonth();
  return `
  <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
    <button class="btn p" id="emp-add-btn">+ إضافة موظف</button>
  </div>
  <div class="card" style="overflow:hidden;">
    <table>
      <thead><tr><th>الاسم</th><th>الوظيفة</th><th>الراتب الأساسي</th><th>الحالة</th><th>راتب ${month}</th><th>إجراءات</th></tr></thead>
      <tbody>
      ${employees.map(e=>{
        const paid = payrollRecords.find(p=>parseInt(p.employee_id)===e.id && p.month===month);
        return `<tr>
        <td style="font-weight:700;color:#f1f5f9;">${esc(e.name)}</td>
        <td style="color:#94a3b8;">${esc(e.position)||'—'}</td>
        <td style="font-weight:700;">${(e.base_salary||0).toLocaleString()} ${cur()}</td>
        <td><span class="badge ${e.is_active?'g':'r'}">${e.is_active?'نشط':'موقوف'}</span></td>
        <td>${paid?`<span class="badge g">✅ مدفوع (${paid.net_paid.toLocaleString()} ${cur()})</span>`:`<span class="badge y">لسا</span>`}</td>
        <td><div style="display:flex;gap:4px;flex-wrap:wrap;">
          <button class="btn s" style="padding:4px 8px;font-size:11px;" onclick="openEmployeeDetail(${e.id})">📋 التفاصيل</button>
          <button class="btn s" style="padding:4px 8px;font-size:11px;" onclick="openEmployeeForm(${e.id})">✏️</button>
          <button class="btn d" style="padding:4px 8px;font-size:11px;" onclick="deleteEmployee(${e.id})">🗑️</button>
        </div></td>
        </tr>`;
      }).join('')||'<tr><td colspan="6" style="text-align:center;color:#475569;padding:24px;">لا يوجد موظفون</td></tr>'}
      </tbody>
    </table>
  </div>`;
}

window.openEmployeeForm = function(id){
  const emp = id ? employees.find(e=>e.id===id)||{} : {};
  MS = {type:'employeeform', data: emp};
  render();
};
window.deleteEmployee = async function(id){
  if(!confirm('حذف هذا الموظف؟ (لن يُحذف سجل رواتبه وسلفه السابقة)')) return;
  try{ await api('DELETE','/api/employees/'+id); await loadAll(); expTab('employees'); }
  catch(e){ alert('خطأ: '+e.message); }
};

// ── تفاصيل موظف: سجل الرواتب + السلف ──
window.openEmployeeDetail = function(id){
  const emp = employees.find(e=>e.id===id);
  if(!emp){ alert('الموظف غير موجود'); return; }
  MS = {type:'employeedetail', data: emp};
  render();
};

function employeeDetailModal(emp){
  const advances = []; // تُحمَّل ديناميكياً
  const history = payrollRecords.filter(p=>parseInt(p.employee_id)===emp.id).sort((a,b)=>b.month.localeCompare(a.month));
  const month = currentMonth();
  const alreadyPaid = history.find(p=>p.month===month);
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:680px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">👤 ${esc(emp.name)}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">${esc(emp.position)||''} — راتب أساسي: ${(emp.base_salary||0).toLocaleString()} ${cur()}</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>

  <div style="display:flex;gap:8px;margin-bottom:14px;">
    ${alreadyPaid
      ? `<span class="badge g" style="padding:8px 14px;font-size:13px;">✅ راتب ${month} مدفوع (${alreadyPaid.net_paid.toLocaleString()} ${cur()})</span>`
      : `<button class="btn p" style="flex:1;justify-content:center;height:40px;" id="emp-pay-salary">💳 دفع راتب ${month}</button>`}
    <button class="btn s" style="flex:1;justify-content:center;height:40px;" id="emp-add-advance">➕ سلفة جديدة</button>
  </div>

  <div style="font-size:13px;font-weight:700;color:#94a3b8;margin-bottom:8px;">💰 السلف غير المخصومة بعد</div>
  <div id="emp-advances-list" style="margin-bottom:16px;"><div class="spin"></div></div>

  <div style="font-size:13px;font-weight:700;color:#94a3b8;margin-bottom:8px;">📊 سجل الرواتب المدفوعة</div>
  <div class="card" style="overflow:hidden;">
    <table>
      <thead><tr><th>الشهر</th><th>الأساسي</th><th>السلف المخصومة</th><th>تعديل</th><th>الصافي المدفوع</th><th>تاريخ الدفع</th><th></th></tr></thead>
      <tbody>
      ${history.map(p=>`<tr>
        <td style="font-weight:700;">${p.month}</td>
        <td>${(p.base_salary||0).toLocaleString()} ${cur()}</td>
        <td style="color:#f87171;">${(p.total_advances||0)>0?'-'+p.total_advances.toLocaleString():'0'} ${cur()}</td>
        <td style="color:${p.adjustment>0?'#52b788':p.adjustment<0?'#f87171':'#64748b'};">${p.adjustment?(p.adjustment>0?'+':'')+p.adjustment.toLocaleString():'0'} ${cur()}</td>
        <td style="font-weight:800;color:#52b788;">${(p.net_paid||0).toLocaleString()} ${cur()}</td>
        <td style="color:#94a3b8;">${p.date_paid}</td>
        <td><button class="btn d" style="padding:3px 7px;font-size:11px;" onclick="deletePayroll(${p.id},${emp.id})">🗑️</button></td>
      </tr>`).join('')||'<tr><td colspan="7" style="text-align:center;color:#475569;padding:16px;">لا يوجد سجل رواتب سابق</td></tr>'}
      </tbody>
    </table>
  </div>
  </div></div>`;
}

async function loadEmployeeAdvances(empId){
  const el = document.getElementById('emp-advances-list');
  if(!el) return;
  try{
    const advs = await api('GET','/api/salary_advances?employee_id='+empId);
    const unconsumed = advs.filter(a=>!a.payroll_id);
    const total = unconsumed.reduce((s,a)=>s+a.amount,0);
    el.innerHTML = unconsumed.length
      ? `<div class="card" style="overflow:hidden;">
          <table><thead><tr><th>التاريخ</th><th>المبلغ</th><th>ملاحظات</th><th></th></tr></thead><tbody>
          ${unconsumed.map(a=>`<tr>
            <td>${a.date}</td>
            <td style="color:#f87171;font-weight:700;">${a.amount.toLocaleString()} ${cur()}</td>
            <td style="font-size:12px;color:#64748b;">${esc(a.notes)||''}</td>
            <td><button class="btn d" style="padding:3px 7px;font-size:11px;" onclick="deleteAdvance(${a.id},${empId})">🗑️</button></td>
          </tr>`).join('')}
          </tbody></table>
          <div style="text-align:left;padding:8px 14px;font-size:13px;font-weight:800;color:#f87171;border-top:1px solid #1e2537;">
            إجمالي السلف غير المخصومة: ${total.toLocaleString()} ${cur()}
          </div>
        </div>`
      : '<div style="color:#64748b;text-align:center;padding:14px;font-size:13px;">لا توجد سلف غير مخصومة</div>';
  }catch(e){ el.innerHTML = '<div class="err">'+e.message+'</div>'; }
}

window.deleteAdvance = async function(id, empId){
  if(!confirm('حذف هذه السلفة؟')) return;
  try{ await api('DELETE','/api/salary_advances/'+id); await loadEmployeeAdvances(empId); }
  catch(e){ alert('خطأ: '+e.message); }
};
window.deletePayroll = async function(id, empId){
  if(!confirm('حذف كشف الراتب هذا؟ سيُحذف المصروف المرتبط به وتُعاد السلف المخصومة لحالتها.')) return;
  try{
    await api('DELETE','/api/payroll/'+id);
    await loadAll();
    MS = {type:'employeedetail', data: employees.find(e=>e.id===empId)};
    render();
  }catch(e){ alert('خطأ: '+e.message); }
};

// ── تبويب: المصاريف المتكررة ──
function expRecurringTabHTML(){
  const month = currentMonth();
  return `
  <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
    <button class="btn p" id="rec-add-btn">+ مصروف متكرر جديد</button>
  </div>
  <div class="card" style="overflow:hidden;">
    <table>
      <thead><tr><th>الوصف</th><th>التصنيف</th><th>المبلغ</th><th>يوم الاستحقاق</th><th>الحالة</th><th>شهر ${month}</th><th>إجراءات</th></tr></thead>
      <tbody>
      ${recurringExpenses.map(r=>{
        const paid = expenses.find(e=>parseInt(e.recurring_id)===r.id && (e.date||'').slice(0,7)===month);
        return `<tr>
        <td style="font-weight:700;color:#f1f5f9;">${esc(r.description)}</td>
        <td><span class="badge b">${r.category_icon||'📦'} ${esc(r.category_name)||'—'}</span></td>
        <td style="font-weight:700;">${(r.amount||0).toLocaleString()} ${cur()}</td>
        <td>يوم ${r.day_of_month}</td>
        <td><span class="badge ${r.is_active?'g':'r'}">${r.is_active?'نشط':'موقوف'}</span></td>
        <td>${paid?`<span class="badge g">✅ مدفوع</span>`:`<span class="badge y">لسا</span>`}</td>
        <td><div style="display:flex;gap:4px;flex-wrap:wrap;">
          ${!paid&&r.is_active?`<button class="btn p" style="padding:4px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPayRecurring(${r.id})">💳 دفع</button>`:''}
          <button class="btn s" style="padding:4px 8px;font-size:11px;" onclick="openRecurringForm(${r.id})">✏️</button>
          <button class="btn d" style="padding:4px 8px;font-size:11px;" onclick="deleteRecurring(${r.id})">🗑️</button>
        </div></td>
        </tr>`;
      }).join('')||'<tr><td colspan="7" style="text-align:center;color:#475569;padding:24px;">لا توجد مصاريف متكررة معرّفة</td></tr>'}
      </tbody>
    </table>
  </div>`;
}

window.openRecurringForm = function(id){
  const rec = id ? recurringExpenses.find(r=>r.id===id)||{} : {};
  MS = {type:'recurringform', data: rec};
  render();
};
window.deleteRecurring = async function(id){
  if(!confirm('حذف هذا المصروف المتكرر؟ (المصاريف السابقة المسجَّلة منه تبقى بالسجل)')) return;
  try{ await api('DELETE','/api/recurring_expenses/'+id); await loadAll(); expTab('recurring'); }
  catch(e){ alert('خطأ: '+e.message); }
};
window.openPayRecurring = function(id){
  const rec = recurringExpenses.find(r=>r.id===id);
  if(!rec){ alert('غير موجود'); return; }
  MS = {type:'payrecurring', data: rec};
  render();
};

function bindExpensesTab(){
  document.getElementById('exp-add-btn')?.addEventListener('click', ()=>{ MS={type:'expenseform', data:{}}; render(); });
  document.getElementById('exp-filter-btn')?.addEventListener('click', applyExpFilter);
  document.getElementById('emp-add-btn')?.addEventListener('click', ()=>{ MS={type:'employeeform', data:{}}; render(); });
  document.getElementById('rec-add-btn')?.addEventListener('click', ()=>{ MS={type:'recurringform', data:{}}; render(); });
}

// ══════════════════════════════════════════════
//  صفحة التركيب والصيانة (خدمات)
// ══════════════════════════════════════════════
const SERVICE_STATUSES = ['قيد الانتظار','قيد التنفيذ','مكتمل','ملغى'];
const SERVICE_STATUS_CLS = {'قيد الانتظار':'y','قيد التنفيذ':'b','مكتمل':'g','ملغى':'r'};

// طلبات الخدمة المكتملة اللي انتهى ضمانها خلال آخر 7 أيام (تنبيه استباقي) أو منتهي فعلاً
function getServiceWarrantyStatus(so){
  if(so.status!=='مكتمل' || !so.completed_date || !so.warranty_days) return null;
  const end = new Date(so.completed_date);
  end.setDate(end.getDate() + parseInt(so.warranty_days));
  const daysLeft = Math.ceil((end - new Date()) / 86400000);
  if(daysLeft < 0) return {expired:true, daysLeft};
  if(daysLeft <= 7) return {expired:false, daysLeft};
  return null;
}

function servicesHTML(){
  const totalFee = serviceOrders.reduce((s,o)=>s+(o.service_fee||0),0);
  const totalCost = serviceOrders.reduce((s,o)=>s+(o.parts_cost||0),0);
  const pending = serviceOrders.filter(o=>o.status==='قيد الانتظار'||o.status==='قيد التنفيذ').length;
  return `<div class="ti">التركيب والصيانة</div><div class="sub">إدارة طلبات التركيب والصيانة والإصلاح</div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px;">
    <div class="stat"><div style="font-size:12px;color:#64748b;">إجمالي الطلبات</div><div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:6px;">${serviceOrders.length}</div></div>
    <div class="stat"><div style="font-size:12px;color:#64748b;">قيد التنفيذ/الانتظار</div><div style="font-size:18px;font-weight:800;color:#fbbf24;margin-top:6px;">${pending}</div></div>
    <div class="stat"><div style="font-size:12px;color:#64748b;">إجمالي الإيراد</div><div style="font-size:18px;font-weight:800;color:#52b788;margin-top:6px;">${totalFee.toLocaleString()} ${cur()}</div></div>
    <div class="stat"><div style="font-size:12px;color:#64748b;">صافي ربح الخدمات</div><div style="font-size:18px;font-weight:800;color:#fbbf24;margin-top:6px;">${(totalFee-totalCost).toLocaleString()} ${cur()}</div></div>
  </div>
  <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;align-items:center;">
    <button class="btn p" id="svc-add-btn">+ طلب خدمة جديد</button>
    <select class="inp" id="svc-status-filter" style="width:180px;">
      <option value="">كل الحالات</option>
      ${SERVICE_STATUSES.map(s=>`<option value="${s}">${s}</option>`).join('')}
    </select>
  </div>
  ${svcWarrantyAlertsHTML()}
  <div id="svc-list">${svcListHTML(serviceOrders)}</div>`;
}

function svcWarrantyAlertsHTML(){
  const alerts = serviceOrders.map(o=>({o, w:getServiceWarrantyStatus(o)})).filter(x=>x.w);
  if(!alerts.length) return '';
  return `<div class="card" style="padding:16px;margin-bottom:16px;border:1px solid #5c4a23;">
    <div style="font-weight:700;color:#fbbf24;margin-bottom:12px;">🛡️ تنبيهات الضمان (${alerts.length})</div>
    ${alerts.map(({o,w})=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e2537;">
      <span style="font-size:13px;color:#f1f5f9;font-weight:700;">#${o.id} — ${esc(o.customer_name)||'—'} — ${esc(o.device_desc)}</span>
      <span class="badge ${w.expired?'r':'y'}">${w.expired?`⏰ انتهى الضمان منذ ${Math.abs(w.daysLeft)} يوم`:`⚠️ الضمان ينتهي خلال ${w.daysLeft} يوم`}</span>
    </div>`).join('')}
  </div>`;
}

function svcListHTML(list){
  return `<div class="card" style="overflow:hidden;">
    <table>
      <thead><tr><th>#</th><th>الزبون</th><th>النوع</th><th>الجهاز</th><th>الفني</th><th>الحالة</th><th>الأجرة</th><th>المتبقي</th><th>تاريخ الاستلام</th><th>إجراءات</th></tr></thead>
      <tbody>
      ${list.map(o=>`<tr>
        <td style="color:#64748b;">#${o.id}</td>
        <td style="font-weight:700;color:#f1f5f9;">${esc(o.customer_name)||'—'}</td>
        <td><span class="badge b">${esc(o.service_type)}</span></td>
        <td style="color:#94a3b8;">${esc(o.device_desc)||'—'}</td>
        <td style="color:#60a5fa;">${esc(o.technician_name)||'—'}</td>
        <td><span class="badge ${SERVICE_STATUS_CLS[o.status]||'b'}">${o.status}</span></td>
        <td style="font-weight:700;">${(o.service_fee||0).toLocaleString()} ${cur()}</td>
        <td style="color:${(o.remaining||0)>0?'#f87171':'#52b788'};font-weight:700;">${(o.remaining||0).toLocaleString()} ${cur()}</td>
        <td style="color:#94a3b8;">${o.received_date}</td>
        <td><div style="display:flex;gap:4px;flex-wrap:wrap;">
          <button class="btn s" style="padding:4px 8px;font-size:11px;" onclick="openServiceDetail(${o.id})">📋</button>
          <button class="btn s" style="padding:4px 8px;font-size:11px;" onclick="openServiceForm(${o.id})">✏️</button>
          ${(o.remaining||0)>0?`<button class="btn p" style="padding:4px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay(${o.id},'service')">💳</button>`:''}
          <button class="btn d" style="padding:4px 8px;font-size:11px;" onclick="deleteServiceOrder(${o.id})">🗑️</button>
        </div></td>
      </tr>`).join('')||'<tr><td colspan="10" style="text-align:center;color:#475569;padding:24px;">لا توجد طلبات خدمة</td></tr>'}
      </tbody>
    </table>
  </div>`;
}

window.applySvcFilter = function(){
  const status = document.getElementById('svc-status-filter')?.value||'';
  const list = status ? serviceOrders.filter(o=>o.status===status) : serviceOrders;
  const el = document.getElementById('svc-list');
  if(el) el.innerHTML = svcListHTML(list);
};

window.openServiceForm = function(id){
  const so = id ? serviceOrders.find(o=>o.id===id)||{} : {};
  MS = {type:'serviceform', data: JSON.parse(JSON.stringify(so))};
  render();
};

window.deleteServiceOrder = async function(id){
  if(!confirm('حذف طلب الخدمة؟ سيتم إرجاع قطع الغيار المستخدمة للمخزون تلقائياً')) return;
  try{ await api('DELETE','/api/service_orders/'+id); await loadAll(); page='services'; render(); }
  catch(e){ alert('خطأ: '+e.message); }
};

window.openServiceDetail = function(id){
  const so = serviceOrders.find(o=>o.id===id);
  if(!so){ alert('غير موجود'); return; }
  MS = {type:'servicedetail', data: so};
  render();
};

function serviceDetailModal(o){
  const w = getServiceWarrantyStatus(o);
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:600px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">طلب خدمة #${o.id}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">${o.received_date}</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;">
    <div class="stat"><div style="font-size:11px;color:#64748b;">الزبون</div><div style="font-weight:700;color:#f1f5f9;margin-top:4px;">${esc(o.customer_name)||'—'}</div></div>
    <div class="stat"><div style="font-size:11px;color:#64748b;">الحالة</div><div style="margin-top:4px;"><span class="badge ${SERVICE_STATUS_CLS[o.status]||'b'}">${o.status}</span></div></div>
    <div class="stat"><div style="font-size:11px;color:#64748b;">نوع الخدمة</div><div style="font-weight:700;color:#f1f5f9;margin-top:4px;">${esc(o.service_type)}</div></div>
    <div class="stat"><div style="font-size:11px;color:#64748b;">الفني</div><div style="font-weight:700;color:#60a5fa;margin-top:4px;">${esc(o.technician_name)||'—'}</div></div>
    <div class="stat"><div style="font-size:11px;color:#64748b;">الجهاز</div><div style="font-weight:700;color:#f1f5f9;margin-top:4px;">${esc(o.device_desc)||'—'}</div></div>
    <div class="stat"><div style="font-size:11px;color:#64748b;">الضمان</div><div style="font-weight:700;margin-top:4px;color:${w?(w.expired?'#f87171':'#fbbf24'):'#94a3b8'};">${o.warranty_days?o.warranty_days+' يوم':'بدون ضمان'}${w?(w.expired?' (منتهي)':' (ينتهي قريباً)'):''}</div></div>
  </div>
  ${o.issue_desc?`<div style="margin-bottom:12px;"><div class="lbl">وصف العطل/المطلوب</div><div style="color:#cbd5e1;font-size:13px;">${esc(o.issue_desc)}</div></div>`:''}
  ${(o.parts&&o.parts.length)?`
  <div style="font-size:13px;font-weight:700;color:#94a3b8;margin-bottom:8px;">🔧 قطع الغيار المستخدمة</div>
  <div class="card" style="margin-bottom:14px;overflow:hidden;">
    <table><thead><tr><th>القطعة</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr></thead><tbody>
    ${o.parts.map(pt=>`<tr>
      <td style="font-weight:600;color:#f1f5f9;">${esc(pt.product_name)}</td>
      <td>${pt.qty} ${pt.unit||''}</td>
      <td>${(pt.price||0).toLocaleString()} ${cur()}</td>
      <td style="color:#f87171;font-weight:700;">${(pt.qty*pt.price).toLocaleString()} ${cur()}</td>
    </tr>`).join('')}
    </tbody></table>
  </div>`:''}
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px;">
    <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">أجرة الخدمة</div><div style="font-size:16px;font-weight:800;color:#52b788;margin-top:4px;">${(o.service_fee||0).toLocaleString()} ${cur()}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">تكلفة القطع</div><div style="font-size:16px;font-weight:800;color:#f87171;margin-top:4px;">${(o.parts_cost||0).toLocaleString()} ${cur()}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">صافي الربح</div><div style="font-size:16px;font-weight:800;color:#fbbf24;margin-top:4px;">${((o.service_fee||0)-(o.parts_cost||0)).toLocaleString()} ${cur()}</div></div>
  </div>
  ${o.notes?`<div style="color:#64748b;font-size:12px;margin-bottom:10px;">📝 ${esc(o.notes)}</div>`:''}
  <div style="display:flex;gap:10px;">
    ${(o.remaining||0)>0?`<button class="btn p" style="flex:1;justify-content:center;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="closeM();openPay(${o.id},'service')">💳 تحصيل دفعة</button>`:''}
    <button class="btn s" style="flex:1;justify-content:center;" onclick="closeM();openServiceForm(${o.id})">✏️ تعديل الطلب</button>
  </div>
  </div></div>`;
}

window.accTab = async function(tab){
  document.querySelectorAll('[id^="acc-tab-"]').forEach(b=>{
    b.className = b.id==='acc-tab-'+tab ? 'btn p' : 'btn s';
  });
  const el = document.getElementById('acc-content');
  if(!el) return;

  // إعادة حساب الإحصاءات دائماً
  supStats = suppliers.map(s=>{
    const purList = purchases.filter(p=>parseInt(p.supplier_id)===s.id);
    const total   = purList.reduce((t,p)=>t+p.total,0);
    const paid    = purList.filter(p=>p.status==='مدفوع').reduce((t,p)=>t+p.total,0);
    const pending = purList.filter(p=>p.status!=='مدفوع').reduce((t,p)=>t+p.total,0);
    return {...s, purTotal:total, purPaid:paid, purPending:pending, purCount:purList.length};
  });
  custStats = customers.map(c=>{
    const saleList = sales.filter(s=>parseInt(s.customer_id)===c.id);
    const total    = saleList.reduce((t,s)=>t+s.total,0);
    const paid     = saleList.filter(s=>s.status==='مدفوع').reduce((t,s)=>t+s.total,0);
    const pending  = saleList.filter(s=>s.status!=='مدفوع').reduce((t,s)=>t+s.total,0);
    return {...c, saleTotal:total, salePaid:paid, salePending:pending, saleCount:saleList.length};
  });

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
        <div style="display:flex;gap:8px;">
          <button class="btn p" style="padding:5px 12px;font-size:12px;"
            onclick="openAccountPay('suppliers',${s.id},'${s.name.replace(/'/g,"\\'")}')">💳 دفعة على الحساب</button>
          <button class="btn p" style="padding:5px 12px;font-size:12px;background:linear-gradient(135deg,#1e40af,#1e3a8a);"
            onclick="openSupPaySummary(${s.id})">📊 كشف الحساب</button>
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <span class="badge b">${s.purCount} فاتورة</span>
        <span style="color:#60a5fa;font-weight:700;">${s.purTotal.toLocaleString()} ${cur()} إجمالي</span>
        ${s.purPaid>0?`<span class="badge g">مدفوع: ${s.purPaid.toLocaleString()} ${cur()}</span>`:''}
        ${s.purPending>0?`<span class="badge r">معلق: ${s.purPending.toLocaleString()} ${cur()}</span>`:''}
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
        <div style="display:flex;gap:8px;">
          <button class="btn p" style="padding:5px 12px;font-size:12px;"
            onclick="openAccountPay('customers',${c.id},'${c.name.replace(/'/g,"\\'")}')">💳 دفعة على الحساب</button>
          <button class="btn p" style="padding:5px 12px;font-size:12px;"
            onclick="openCustPaySummary(${c.id})">📊 كشف الحساب</button>
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <span class="badge b">${c.saleCount} فاتورة</span>
        <span style="color:#52b788;font-weight:700;">${c.saleTotal.toLocaleString()} ${cur()} إجمالي</span>
        ${c.salePaid>0?`<span class="badge g">مدفوع: ${c.salePaid.toLocaleString()} ${cur()}</span>`:''}
        ${c.salePending>0?`<span class="badge y">معلق: ${c.salePending.toLocaleString()} ${cur()}</span>`:''}
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
    if(el) el.innerHTML = paySummaryHTML(data, sup.name, 'supplier', sup_id);
  }catch(e){ if(el) el.innerHTML='<div class="err">'+e.message+'</div>'; }
};

window.openCustPaySummary = async function(cust_id){
  const cust = customers.find(c=>c.id===cust_id);
  if(!cust) return;
  const el = document.getElementById('acc-content');
  if(el) el.innerHTML='<div class="spin"></div>';
  try{
    const data = await api('GET','/api/payments_summary?party_type=customer&party_id='+cust_id);
    if(el) el.innerHTML = paySummaryHTML(data, cust.name, 'customer', cust_id);
  }catch(e){ if(el) el.innerHTML='<div class="err">'+e.message+'</div>'; }
};

function paySummaryHTML(data, name, party_type, party_id){
  const {invoices, total_invoices, total_paid, total_remaining} = data;
  return '<div>'
  + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
    + '<div style="font-size:16px;font-weight:800;color:#f1f5f9;">كشف حساب: '+esc(name)+'</div>'
    + '<div style="display:flex;gap:8px;">'
      + '<button class="btn p" style="font-size:12px;padding:5px 12px;" onclick=\'openAllPayments("'+party_type+'",'+party_id+',"'+name.replace(/"/g,'&quot;')+'")\'>📋 كل الدفعات</button>'
      + '<button class="btn s" style="font-size:12px;" onclick="accTab(&quot;sum&quot;)">← رجوع</button>'
    + '</div>'
  + '</div>'
  + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">'
    + '<div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">إجمالي الفواتير</div><div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:6px;">'+total_invoices.toLocaleString()+' '+cur()+'</div></div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">إجمالي المدفوع</div><div style="font-size:18px;font-weight:800;color:#52b788;margin-top:6px;">'+total_paid.toLocaleString()+' '+cur()+'</div>'
      + (data.account_paid>0?('<div style="font-size:10px;color:#94a3b8;margin-top:2px;">منها '+data.account_paid.toLocaleString()+' '+cur()+' دفعات حساب مباشرة</div>'):'')
    + '</div>'
    + '<div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">المتبقي</div><div style="font-size:18px;font-weight:800;color:'+(total_remaining>0?'#f87171':'#52b788')+';margin-top:6px;">'+total_remaining.toLocaleString()+' '+cur()+'</div></div>'
  + '</div>'
  + '<div class="card"><table>'
    + '<thead><tr><th>#</th><th>النوع</th><th>التاريخ</th><th>الإجمالي</th><th>المدفوع</th><th>المتبقي</th><th>الحالة</th><th></th></tr></thead>'
    + '<tbody>'
    + invoices.map(inv=>'<tr>'
        + '<td style="color:#64748b;">#'+inv.id+'</td>'
        + '<td><span class="badge '+(inv.ref_type==='service'?'y':inv.ref_type==='purchase'?'b':'g')+'">'+(inv.ref_type==='service'?'🔧 '+esc(inv.service_type||'خدمة'):inv.ref_type==='purchase'?'شراء':'بيع')+'</span></td>'
        + '<td>'+inv.date+'</td>'
        + '<td style="font-weight:700;">'+Math.abs(inv.total||0).toLocaleString()+' '+cur()+'</td>'
        + '<td style="color:#52b788;font-weight:600;">'+(inv.paid||0).toLocaleString()+' '+cur()+'</td>'
        + '<td style="color:'+(inv.remaining>0?'#f87171':'#52b788')+';font-weight:700;">'+(inv.remaining||0).toLocaleString()+' '+cur()+'</td>'
        + '<td><span class="badge '+(inv.status==='مدفوع'?'g':inv.status==='معلق'?'r':'b')+'">'+inv.status+'</span></td>'
        + '<td><div style="display:flex;gap:4px;">'
          + (inv.remaining>0?('<button class="btn p" style="padding:3px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay('+inv.id+',&quot;'+inv.ref_type+'&quot;)">💳 دفعة</button>'):'')
          + '<button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="viewPayHist('+inv.id+',&quot;'+inv.ref_type+'&quot;)">📊</button>'
        + '</div></td>'
      + '</tr>').join('')
    + '</tbody></table></div>'
  + '</div>';
}

// ── عرض كل دفعات الحساب (مورد/زبون) مع تعديل وحذف مباشر ──
window.openAllPayments = async function(party_type, party_id, name){
  const el = document.getElementById('acc-content');
  if(el) el.innerHTML='<div class="spin"></div>';
  try{
    const pays = await api('GET', `/api/payments?party_type=${party_type}&party_id=${party_id}`);
    if(el) el.innerHTML = allPaymentsHTML(pays, name, party_type, party_id);
  }catch(e){
    if(el) el.innerHTML = '<div class="err">'+e.message+'</div>';
  }
};

function allPaymentsHTML(pays, name, party_type, party_id){
  const total = pays.reduce((s,p)=>s+p.amount,0);
  const ref_type = party_type==='supplier' ? 'purchase' : 'sale';
  return `<div>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">📋 كل دفعات: ${name}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">${pays.length} دفعة — إجمالي ${total.toLocaleString()} ${cur()}</div>
    </div>
    <button class="btn s" style="font-size:12px;" onclick="${party_type==='supplier'?'openSupPaySummary':'openCustPaySummary'}(${party_id})">← رجوع لكشف الحساب</button>
  </div>
  <div class="card">
    <table>
      <thead><tr><th>#</th><th>الفاتورة</th><th>التاريخ</th><th>الطريقة</th><th>المبلغ</th><th>تفاصيل الشيك</th><th>ملاحظات</th><th>إجراءات</th></tr></thead>
      <tbody>
      ${pays.length ? pays.map(p=>`<tr>
        <td style="color:#64748b;">#${p.id}</td>
        <td>${p.ref_type==='account'
          ? '<span class="badge y">💼 دفعة على الحساب</span>'
          : `<span class="badge ${ref_type==='purchase'?'b':'g'}">#${p.ref_id}</span>`}</td>
        <td style="font-weight:600;">${p.date}</td>
        <td><span class="badge ${p.method==='نقدي'?'g':p.method==='شيك'?'b':'y'}">${p.method}</span></td>
        <td style="font-weight:800;color:#52b788;font-size:14px;">${p.amount.toLocaleString()} ${cur()}</td>
        <td style="font-size:12px;color:#94a3b8;">${p.cheque_no?'#'+p.cheque_no+' — '+(p.cheque_bank||''):'—'}</td>
        <td style="font-size:12px;color:#64748b;">${p.notes||''}</td>
        <td><div style="display:flex;gap:4px;">
          <button class="btn s" style="padding:4px 9px;font-size:11px;" onclick='openEditPayment(${JSON.stringify(p).replace(/'/g,"&#39;")})'>✏️ تعديل</button>
          <button class="btn d" style="padding:4px 9px;font-size:11px;" onclick="deletePaymentDirect(${p.id},'${party_type}',${party_id},'${name.replace(/'/g,"\\'")}')">🗑️ حذف</button>
        </div></td>
      </tr>`).join('') : '<tr><td colspan="8" style="text-align:center;color:#475569;padding:24px;">لا توجد دفعات مسجلة</td></tr>'}
      </tbody>
    </table>
  </div>
  </div>`;
}

window.deletePaymentDirect = async function(id, party_type, party_id, name){
  if(!confirm('هل تريد حذف هذه الدفعة نهائياً؟\nسيتم تحديث حالة الفاتورة المرتبطة.')) return;
  try{
    await api('DELETE','/api/payments/'+id);
    await loadAll();
    await openAllPayments(party_type, party_id, name);
  }catch(e){ alert('خطأ: '+e.message); }
};

// REPORTS
function reportsHTML(){
  const ts=sales.reduce((s,x)=>s+x.total,0), tp=purchases.reduce((s,x)=>s+x.total,0);
  const te=expenses.reduce((s,x)=>s+(x.amount||0),0);
  return `<div class="ti">التقارير</div><div class="sub">تقارير شاملة لجميع العمليات</div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px;">
    <div class="stat"><div style="font-size:13px;color:#64748b;">المبيعات</div><div style="font-size:19px;font-weight:800;color:#52b788;margin-top:7px;">${ts.toLocaleString()} ${cur()}</div></div>
    <div class="stat"><div style="font-size:13px;color:#64748b;">المشتريات</div><div style="font-size:19px;font-weight:800;color:#60a5fa;margin-top:7px;">${tp.toLocaleString()} ${cur()}</div></div>
    <div class="stat"><div style="font-size:13px;color:#64748b;">المصاريف</div><div style="font-size:19px;font-weight:800;color:#f87171;margin-top:7px;">${te.toLocaleString()} ${cur()}</div></div>
    <div class="stat"><div style="font-size:13px;color:#64748b;">الربح الصافي</div><div style="font-size:19px;font-weight:800;color:#fbbf24;margin-top:7px;">${(ts-tp-te).toLocaleString()} ${cur()}</div></div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;" id="rep-tabs">
    ${[['sales','المبيعات'],['top-products','الأكثر/الأقل مبيعاً 📈'],['purchases','المشتريات'],['expenses-report','المصاريف 💸'],['sup-compare','مقارنة أسعار الموردين ⚖️'],['cheques','الشيكات 🏦'],['sup-detail','كشف مورد 🔍'],['cust-detail','كشف زبون 🔍'],['customers','ملخص الزبائن'],['inventory','المخزون']
    ].map(([id,label],i)=>`<button class="btn ${i===0?'p':'s'}" data-rep="${id}">${label}</button>`).join('')}
  </div>
  <div id="rc">${repContent('sales')}</div>`;
}

function repContent(type){
  if(type==='sales'){
    const today=new Date().toISOString().slice(0,10);
    const first=today.slice(0,7)+'-01';
    return `
    <div class="card" style="padding:16px;margin-bottom:14px;">
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;align-items:end;">
        <div><label class="lbl">من تاريخ</label><input class="inp" type="date" id="srep-from" value="${first}"/></div>
        <div><label class="lbl">إلى تاريخ</label><input class="inp" type="date" id="srep-to" value="${today}"/></div>
        <div><label class="lbl">طريقة الدفع</label>
          <select class="inp" id="srep-method"><option value="">الكل</option>${['نقدي','بطاقة','تحويل','آجل'].map(m=>`<option>${m}</option>`).join('')}</select>
        </div>
        <div><label class="lbl">الحالة</label>
          <select class="inp" id="srep-status"><option value="">الكل</option>${['مدفوع','معلق','مدفوع جزئياً'].map(s=>`<option>${s}</option>`).join('')}</select>
        </div>
        <div><button class="btn p" style="width:100%;height:42px;justify-content:center;" onclick="renderSalesReport()">🔍 تطبيق الفلترة</button></div>
      </div>
    </div>
    <div id="sales-rep-body"><div class="spin"></div></div>`;
  }

  if(type==='top-products'){
    const today=new Date().toISOString().slice(0,10);
    const first=today.slice(0,7)+'-01';
    return `
    <div class="card" style="padding:16px;margin-bottom:14px;">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;align-items:end;">
        <div><label class="lbl">من تاريخ</label><input class="inp" type="date" id="tprep-from" value="${first}"/></div>
        <div><label class="lbl">إلى تاريخ</label><input class="inp" type="date" id="tprep-to" value="${today}"/></div>
        <div><button class="btn p" style="width:100%;height:42px;justify-content:center;" onclick="renderTopProducts()">🔍 تطبيق الفلترة</button></div>
      </div>
    </div>
    <div id="top-products-body"><div class="spin"></div></div>`;
  }

  if(type==='sup-compare'){
    return `
    <div class="card" style="padding:16px;margin-bottom:14px;">
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px;align-items:end;">
        <div><label class="lbl">اختر منتجاً (أو اتركه فارغاً لعرض كل المنتجات التي اشتُريت من أكثر من مورد)</label>
          <select class="inp" id="supcmp-product">
            <option value="">-- كل المنتجات --</option>
            ${products.map(p=>`<option value="${p.id}">${p.name} — ${p.barcode}</option>`).join('')}
          </select>
        </div>
        <div><button class="btn p" style="width:100%;height:42px;justify-content:center;" onclick="renderSupplierCompare()">🔍 عرض المقارنة</button></div>
      </div>
    </div>
    <div id="sup-compare-body"><div class="spin"></div></div>`;
  }

  if(type==='purchases') return `<div class="card"><table>
    <thead><tr><th>#</th><th>التاريخ</th><th>المورد</th><th>الاصناف</th><th>الاجمالي</th><th>المدفوع</th><th>المتبقي</th><th>الحالة</th><th>إجراءات</th></tr></thead>
    <tbody>${purchases.map(p=>{
      const paidAmt = (p.paid || 0);
      const remAmt  = Math.max(0, (p.total||0) - paidAmt);
      return `<tr>
      <td style="color:#64748b;">#${p.id}</td>
      <td style="font-weight:700;color:#f1f5f9;">📅 ${p.date}</td>
      <td style="color:#60a5fa;font-weight:600;">${suppliers.find(s=>s.id===p.supplier_id)?.name||'—'}</td>
      <td><span class="badge b">${p.items?.length||0} صنف</span></td>
      <td style="font-weight:700;">${(p.total||0).toLocaleString()} ${cur()}</td>
      <td style="color:#52b788;font-weight:600;">${paidAmt.toLocaleString()} ${cur()}</td>
      <td style="color:${remAmt>0?'#f87171':'#52b788'};font-weight:700;">${remAmt.toLocaleString()} ${cur()}</td>
      <td><span class="badge ${p.status==='مدفوع'?'g':p.status==='مدفوع جزئياً'?'b':'y'}">${p.status}</span></td>
      <td><div style="display:flex;gap:4px;">
        ${remAmt>0?`<button class="btn p" style="padding:3px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay(${p.id},'purchase')">💳 دفعة</button>`:''}
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="viewPayHist(${p.id},'purchase')">📊 الدفعات</button>
      </div></td>
    </tr>`;}).join('')||'<tr><td colspan="9" style="text-align:center;color:#475569;padding:20px;">لا توجد مشتريات</td></tr>'}
    </tbody></table>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:14px;border-top:1px solid #1e2537;">
      <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي المشتريات</div><div style="font-size:16px;font-weight:800;color:#60a5fa;margin-top:5px;">${purchases.reduce((s,p)=>s+(p.total||0),0).toLocaleString()} ${cur()}</div></div>
      <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي المدفوع</div><div style="font-size:16px;font-weight:800;color:#52b788;margin-top:5px;">${purchases.reduce((s,p)=>s+(p.paid||0),0).toLocaleString()} ${cur()}</div></div>
      <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي المتبقي</div><div style="font-size:16px;font-weight:800;color:#f87171;margin-top:5px;">${purchases.reduce((s,p)=>s+Math.max(0,(p.total||0)-(p.paid||0)),0).toLocaleString()} ${cur()}</div></div>
    </div>
    </div>`;

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

  if(type==='cust-detail'){
    const today=new Date().toISOString().slice(0,10);
    const first=today.slice(0,7)+'-01';
    const custOpts = customers.map(c=>'<option value="'+c.id+'">'+c.name+'</option>').join('');
    return '<div class="card" style="padding:20px;margin-bottom:14px;">'
      + '<div style="font-size:16px;font-weight:800;color:#f1f5f9;margin-bottom:16px;">🔍 كشف حساب زبون تفصيلي</div>'
      + '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px;">'
        + '<div><label class="lbl">اختر الزبون</label>'
          + '<select class="inp" id="crid"><option value="">-- اختر الزبون --</option>'+custOpts+'</select>'
        + '</div>'
        + '<div><label class="lbl">من تاريخ</label>'
          + '<input class="inp" type="date" id="crf" value="'+first+'"/>'
        + '</div>'
        + '<div><label class="lbl">الى تاريخ</label>'
          + '<input class="inp" type="date" id="crt" value="'+today+'"/>'
        + '</div>'
      + '</div>'
      + '<button class="btn p" id="crb" style="height:44px;width:100%;justify-content:center;font-size:15px;" '
      + 'onclick="doCustReport()">🔍 عرض كشف الزبون</button>'
      + '<div id="crr" style="margin-top:16px;"></div>'
    + '</div>';
  }

  if(type==='customers') return `<div class="card"><table>
    <thead><tr><th>الزبون</th><th>المدينة</th><th>الطلبات</th><th>الاجمالي</th><th>المدفوع</th><th>المتبقي</th><th>إجراءات</th></tr></thead>
    <tbody>${customers.map(c=>{
      const o=sales.filter(s=>parseInt(s.customer_id)===c.id);
      const totalSales = o.reduce((t,s)=>t+(s.total||0),0);
      const totalPaid  = o.reduce((t,s)=>t+(s.paid||0),0);
      const totalRem   = o.reduce((t,s)=>t+Math.max(0,(s.total||0)-(s.paid||0)),0);
      return `<tr>
      <td style="font-weight:700;color:#f1f5f9;">${c.name}</td>
      <td>${c.city||''}</td>
      <td><span class="badge b">${o.length}</span></td>
      <td style="font-weight:700;">${totalSales.toLocaleString()} ${cur()}</td>
      <td style="color:#52b788;font-weight:600;">${totalPaid.toLocaleString()} ${cur()}</td>
      <td style="color:${totalRem>0?'#f87171':'#52b788'};font-weight:700;">${totalRem.toLocaleString()} ${cur()}</td>
      <td><div style="display:flex;gap:4px;">
        <button class="btn p" style="padding:3px 8px;font-size:11px;" onclick="doCustReport(${c.id})">📋 كشف حساب</button>
      </div></td>
      </tr>`;}).join('')||'<tr><td colspan="7" style="text-align:center;color:#475569;padding:20px;">لا يوجد زبائن</td></tr>'}
    </tbody></table>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:14px;border-top:1px solid #1e2537;">
      <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي المبيعات</div><div style="font-size:16px;font-weight:800;color:#52b788;margin-top:5px;">${sales.reduce((s,x)=>s+(x.total||0),0).toLocaleString()} ${cur()}</div></div>
      <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي المدفوع</div><div style="font-size:16px;font-weight:800;color:#60a5fa;margin-top:5px;">${sales.reduce((s,x)=>s+(x.paid||0),0).toLocaleString()} ${cur()}</div></div>
      <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">إجمالي المتبقي</div><div style="font-size:16px;font-weight:800;color:#fbbf24;margin-top:5px;">${sales.reduce((s,x)=>s+Math.max(0,(x.total||0)-(x.paid||0)),0).toLocaleString()} ${cur()}</div></div>
    </div>
    </div>`;

  if(type==='inventory') return `<div class="card"><table>
    <thead><tr><th>المنتج</th><th>الفئة</th><th>المخزون</th><th>القيمة</th><th>الحالة</th></tr></thead>
    <tbody>${products.map(p=>`<tr>
    <td style="font-weight:700;color:#f1f5f9;">${p.name}</td>
    <td><span class="badge b">${p.category||''}</span></td>
    <td><span class="badge ${p.stock<lowStockLimit()?'r':'g'}">${p.stock}</span></td>
    <td style="color:#52b788;font-weight:600;">${(p.stock*p.buy_price).toLocaleString()} ${cur()}</td>
    <td><span class="badge ${p.stock===0?'r':p.stock<lowStockLimit()?'y':'g'}">${p.stock===0?'نفد':p.stock<lowStockLimit()?'منخفض':'متوفر'}</span></td></tr>`).join('')}
    </tbody></table></div>`;

  if(type==='expenses-report'){
    const today = new Date().toISOString().slice(0,10);
    const first = today.slice(0,7)+'-01';
    return `
    <div class="card" style="padding:16px;margin-bottom:14px;">
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;align-items:end;">
        <div><label class="lbl">من تاريخ</label><input class="inp" id="exprep-from" type="date" value="${first}"/></div>
        <div><label class="lbl">إلى تاريخ</label><input class="inp" id="exprep-to" type="date" value="${today}"/></div>
        <div><label class="lbl">التصنيف</label>
          <select class="inp" id="exprep-cat"><option value="">الكل</option>
          ${expenseCategories.map(c=>`<option value="${c.id}">${c.icon} ${esc(c.name)}</option>`).join('')}</select>
        </div>
        <div><button class="btn p" style="width:100%;height:42px;justify-content:center;" onclick="renderExpensesReport()">🔍 تطبيق الفلترة</button></div>
      </div>
    </div>
    <div id="expenses-rep-body"><div class="spin"></div></div>`;
  }

  if(type==='cheques'){
    const today = new Date().toISOString().slice(0,10);
    const first = today.slice(0,7)+'-01';
    return `
    <div class="card" style="padding:18px;margin-bottom:14px;">
      <div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:14px;">🏦 كشف الشيكات الصادرة والواردة</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px;">
        <div>
          <label class="lbl">النوع</label>
          <select class="inp" id="chq-dir">
            <option value="all">الكل</option>
            <option value="outgoing">صادرة (للموردين)</option>
            <option value="incoming">واردة (من الزبائن)</option>
          </select>
        </div>
        <div>
          <label class="lbl">الحالة</label>
          <select class="inp" id="chq-status">
            <option value="all">الكل</option>
            <option value="قيد التحصيل">قيد التحصيل</option>
            <option value="محصّل">محصّل</option>
            <option value="مرتجع">مرتجع</option>
            <option value="مؤجل">مؤجل</option>
          </select>
        </div>
        <div>
          <label class="lbl">من تاريخ الشيك</label>
          <input class="inp" type="date" id="chq-from" value="${first}"/>
        </div>
        <div>
          <label class="lbl">إلى تاريخ الشيك</label>
          <input class="inp" type="date" id="chq-to" value="${today}"/>
        </div>
      </div>
      <button class="btn p" id="chq-search" style="width:100%;justify-content:center;height:42px;" onclick="loadCheques()">
        🔍 عرض الشيكات
      </button>
    </div>
    <div id="chq-result"></div>`;
  }

  return '';
}

// ══════════════════════════════════════════════
//  تقرير المبيعات: فلترة + هامش ربح + رسم بياني
// ══════════════════════════════════════════════
let _salesChartGroup = 'daily'; // daily | weekly | monthly

window.renderSalesReport = function(){
  const el = document.getElementById('sales-rep-body');
  if(!el) return;
  const from   = document.getElementById('srep-from')?.value || '2000-01-01';
  const to     = document.getElementById('srep-to')?.value   || '2099-12-31';
  const method = document.getElementById('srep-method')?.value || '';
  const status = document.getElementById('srep-status')?.value || '';

  let list = sales.filter(s => s.date >= from && s.date <= to);
  if(method) list = list.filter(s => s.pay_method === method);
  if(status) list = list.filter(s => s.status === status);
  list = [...list].sort((a,b)=> (a.date||'').localeCompare(b.date||''));

  // هامش الربح: نستخدم سعر الشراء الحالي للمنتج كأفضل تقدير متاح (لا يوجد سجل تكلفة تاريخي لكل عملية بيع)
  const withMargin = list.map(s=>{
    let cost = 0;
    (s.items||[]).forEach(it=>{
      const prod = products.find(p=>p.id===it.product_id);
      cost += (prod ? prod.buy_price : 0) * (it.qty||0);
    });
    const revenue = s.total||0;
    const profit  = revenue - cost;
    return {...s, _cost:cost, _profit:profit};
  });

  const totalRevenue = withMargin.reduce((t,s)=>t+(s.total||0),0);
  const totalProfit  = withMargin.reduce((t,s)=>t+s._profit,0);
  const avgInvoice   = withMargin.length ? totalRevenue/withMargin.length : 0;

  el.innerHTML = `
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
    <div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">عدد الفواتير</div><div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:5px;">${withMargin.length}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">إجمالي المبيعات</div><div style="font-size:18px;font-weight:800;color:#52b788;margin-top:5px;">${totalRevenue.toLocaleString()} ${cur()}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">هامش الربح التقديري</div><div style="font-size:18px;font-weight:800;color:${totalProfit>=0?'#fbbf24':'#f87171'};margin-top:5px;">${totalProfit.toLocaleString()} ${cur()}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">متوسط الفاتورة</div><div style="font-size:18px;font-weight:800;color:#f1f5f9;margin-top:5px;">${avgInvoice.toLocaleString(undefined,{maximumFractionDigits:0})} ${cur()}</div></div>
  </div>

  <div class="card" style="padding:16px;margin-bottom:14px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div style="font-weight:700;color:#f1f5f9;">📈 حجم المبيعات</div>
      <div style="display:flex;gap:6px;">
        ${[['daily','يومي'],['weekly','أسبوعي'],['monthly','شهري']].map(([k,l])=>
          `<button class="btn ${_salesChartGroup===k?'p':'s'}" style="padding:4px 12px;font-size:12px;" onclick="_salesChartGroup='${k}';renderSalesReport();">${l}</button>`
        ).join('')}
      </div>
    </div>
    <div id="sales-chart">${salesChartHTML(withMargin)}</div>
  </div>

  <div class="card" style="overflow:hidden;">
    <table>
      <thead><tr><th>#</th><th>التاريخ</th><th>الزبون</th><th>الاجمالي</th><th>هامش الربح التقديري</th><th>الحالة</th><th>الدفع</th><th>إجراءات</th></tr></thead>
      <tbody>${withMargin.map(s=>`<tr>
      <td style="color:#64748b;">#${s.id}</td>
      <td style="font-weight:600;">${s.date}</td>
      <td style="color:#52b788;font-weight:600;">${customers.find(c=>c.id===s.customer_id)?.name||'زبون عام'}</td>
      <td style="font-weight:700;">${(s.total||0).toLocaleString()} ${cur()}</td>
      <td style="font-weight:700;color:${s._profit>=0?'#52b788':'#f87171'};">${s._profit.toLocaleString()} ${cur()}</td>
      <td><span class="badge ${s.status==='مدفوع'?'g':'y'}">${s.status}</span></td>
      <td>${s.pay_method}</td>
      <td><div style="display:flex;gap:4px;">
        ${s.status!=='مدفوع'?`<button class="btn p" style="padding:3px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay(${s.id},'sale')">💳 دفعة</button>`:''}
        <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="viewPayHist(${s.id},'sale')">📊 الدفعات</button>
      </div></td>
      </tr>`).join('') || '<tr><td colspan="8" style="text-align:center;color:#475569;padding:20px;">لا توجد مبيعات ضمن هذه الفلترة</td></tr>'}
      </tbody>
    </table>
  </div>`;
};

// رسم بياني بسيط بالأعمدة (بدون أي مكتبة خارجية) — يجمّع المبيعات حسب يوم/أسبوع/شهر
function salesChartHTML(list){
  if(!list.length) return '<div style="text-align:center;color:#64748b;padding:20px;">لا توجد بيانات لعرضها</div>';
  const buckets = {};
  list.forEach(s=>{
    let key;
    if(_salesChartGroup==='daily') key = s.date;
    else if(_salesChartGroup==='monthly') key = (s.date||'').slice(0,7);
    else{
      // أسبوعي: نجمع حسب بداية الأسبوع (السبت)
      const d = new Date(s.date);
      const day = d.getDay();
      d.setDate(d.getDate()-day);
      key = d.toISOString().slice(0,10);
    }
    buckets[key] = (buckets[key]||0) + (s.total||0);
  });
  const keys = Object.keys(buckets).sort();
  const max = Math.max(...keys.map(k=>buckets[k]), 1);
  return `<div style="display:flex;align-items:flex-end;gap:6px;height:180px;overflow-x:auto;padding:6px 2px;">
    ${keys.map(k=>{
      const h = Math.max(4, Math.round((buckets[k]/max)*150));
      return `<div style="display:flex;flex-direction:column;align-items:center;min-width:44px;flex:1;">
        <div style="font-size:10px;color:#52b788;font-weight:700;margin-bottom:3px;">${buckets[k].toLocaleString()}</div>
        <div title="${k}: ${buckets[k].toLocaleString()} ${cur()}"
          style="width:26px;height:${h}px;background:linear-gradient(180deg,#3d8b67,#1b4332);border-radius:4px 4px 0 0;"></div>
        <div style="font-size:9px;color:#64748b;margin-top:4px;white-space:nowrap;transform:rotate(0deg);">${k.slice(5)||k}</div>
      </div>`;
    }).join('')}
  </div>`;
}

// ══════════════════════════════════════════════
//  تقرير المصاريف: فلترة + تجميع حسب التصنيف
// ══════════════════════════════════════════════
window.renderExpensesReport = function(){
  const el = document.getElementById('expenses-rep-body');
  if(!el) return;
  const from = document.getElementById('exprep-from')?.value || '2000-01-01';
  const to   = document.getElementById('exprep-to')?.value   || '2099-12-31';
  const cat  = document.getElementById('exprep-cat')?.value  || '';

  let list = expenses.filter(e => e.date >= from && e.date <= to);
  if(cat) list = list.filter(e => String(e.category_id) === String(cat));
  list = [...list].sort((a,b)=> (b.date||'').localeCompare(a.date||''));

  const total = list.reduce((t,e)=>t+(e.amount||0),0);
  const byCat = {};
  list.forEach(e=>{
    const k = e.category_name || 'أخرى';
    if(!byCat[k]) byCat[k] = {total:0, icon:e.category_icon||'📦'};
    byCat[k].total += (e.amount||0);
  });
  const catRows = Object.entries(byCat).sort((a,b)=>b[1].total-a[1].total);
  const maxCat = Math.max(...catRows.map(([,v])=>v.total), 1);

  el.innerHTML = `
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">
    <div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">عدد المصاريف</div><div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:5px;">${list.length}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">إجمالي المصاريف</div><div style="font-size:18px;font-weight:800;color:#f87171;margin-top:5px;">${total.toLocaleString()} ${cur()}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:12px;color:#64748b;">متوسط المصروف</div><div style="font-size:18px;font-weight:800;color:#f1f5f9;margin-top:5px;">${(list.length?total/list.length:0).toLocaleString(undefined,{maximumFractionDigits:0})} ${cur()}</div></div>
  </div>

  <div class="card" style="padding:16px;margin-bottom:14px;">
    <div style="font-weight:700;color:#f1f5f9;margin-bottom:12px;">📊 التوزيع حسب التصنيف</div>
    ${catRows.map(([name,v])=>`
    <div style="margin-bottom:10px;">
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px;">
        <span style="color:#cbd5e1;">${v.icon} ${esc(name)}</span>
        <span style="color:#f87171;font-weight:700;">${v.total.toLocaleString()} ${cur()}</span>
      </div>
      <div style="background:#1a1d27;border-radius:6px;height:8px;overflow:hidden;">
        <div style="width:${Math.round((v.total/maxCat)*100)}%;height:100%;background:linear-gradient(90deg,#dc2626,#f87171);"></div>
      </div>
    </div>`).join('') || '<div style="text-align:center;color:#64748b;padding:16px;">لا توجد بيانات لعرضها</div>'}
  </div>

  <div class="card" style="overflow:hidden;">
    <table>
      <thead><tr><th>التاريخ</th><th>التصنيف</th><th>الوصف</th><th>المبلغ</th><th>طريقة الدفع</th></tr></thead>
      <tbody>${list.map(e=>`<tr>
      <td style="font-weight:600;">${e.date}</td>
      <td><span class="badge b">${e.category_icon||'📦'} ${esc(e.category_name)||'—'}</span></td>
      <td style="color:#f1f5f9;">${esc(e.description)}</td>
      <td style="font-weight:700;color:#f87171;">${(e.amount||0).toLocaleString()} ${cur()}</td>
      <td>${e.payment_method}</td>
      </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:#475569;padding:20px;">لا توجد مصاريف ضمن هذه الفلترة</td></tr>'}
      </tbody>
    </table>
  </div>`;
};

// ══════════════════════════════════════════════
//  الأكثر مبيعاً / الأقل حركة — لكل منتج خلال فترة
// ══════════════════════════════════════════════
window.renderTopProducts = function(){
  const el = document.getElementById('top-products-body');
  if(!el) return;
  const from = document.getElementById('tprep-from')?.value || '2000-01-01';
  const to   = document.getElementById('tprep-to')?.value   || '2099-12-31';

  const list = sales.filter(s => s.date >= from && s.date <= to);
  const agg = {}; // product_id -> {qty, revenue}
  list.forEach(s=>{
    (s.items||[]).forEach(it=>{
      if(!agg[it.product_id]) agg[it.product_id] = {qty:0, revenue:0};
      agg[it.product_id].qty     += (it.qty||0);
      agg[it.product_id].revenue += (it.qty||0)*(it.price||0);
    });
  });
  const rowsArr = products.map(p=>({
    product: p,
    qty: agg[p.id]?.qty || 0,
    revenue: agg[p.id]?.revenue || 0
  }));
  const sold   = rowsArr.filter(r=>r.qty>0).sort((a,b)=>b.qty-a.qty);
  const top10  = sold.slice(0,10);
  const slow   = rowsArr.filter(r=>r.qty===0);
  const least10= sold.slice(-10).reverse();

  el.innerHTML = `
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    <div class="card" style="padding:0;overflow:hidden;">
      <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;font-weight:700;color:#52b788;">🏆 الأكثر مبيعاً (أعلى 10)</div>
      <table><thead><tr><th>المنتج</th><th>الكمية المباعة</th><th>الإيراد</th></tr></thead><tbody>
      ${top10.map(r=>`<tr>
        <td style="font-weight:600;color:#f1f5f9;">${r.product.name}</td>
        <td><span class="badge g">${r.qty} ${r.product.unit||''}</span></td>
        <td style="color:#52b788;font-weight:700;">${r.revenue.toLocaleString()} ${cur()}</td>
      </tr>`).join('') || '<tr><td colspan="3" style="text-align:center;color:#64748b;padding:16px;">لا توجد مبيعات ضمن الفترة</td></tr>'}
      </tbody></table>
    </div>
    <div class="card" style="padding:0;overflow:hidden;">
      <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;font-weight:700;color:#f87171;">🐌 الأقل حركة</div>
      <table><thead><tr><th>المنتج</th><th>الكمية المباعة</th><th>الإيراد</th></tr></thead><tbody>
      ${least10.map(r=>`<tr>
        <td style="font-weight:600;color:#f1f5f9;">${r.product.name}</td>
        <td><span class="badge y">${r.qty} ${r.product.unit||''}</span></td>
        <td style="color:#94a3b8;">${r.revenue.toLocaleString()} ${cur()}</td>
      </tr>`).join('') || '<tr><td colspan="3" style="text-align:center;color:#64748b;padding:16px;">—</td></tr>'}
      </tbody></table>
      ${slow.length ? `<div style="padding:10px 16px;border-top:1px solid #1e2537;font-size:12px;color:#f87171;">⚠️ ${slow.length} منتج لم يُبَع إطلاقاً ضمن هذه الفترة</div>` : ''}
    </div>
  </div>`;
};

// ══════════════════════════════════════════════
//  نسخ كشف حساب زبون كنص جاهز للإرسال (واتساب/أي وسيلة تواصل)
// ══════════════════════════════════════════════
// ── نافذة نسخ نص يدوياً (بديل عند رفض المتصفح الوصول لحافظة النظام) ──
function textCopyModal(d){
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
    <div style="font-size:16px;font-weight:800;color:#f1f5f9;">${d.title||'نسخ النص'}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div style="font-size:12px;color:#64748b;margin-bottom:8px;">تعذّر النسخ التلقائي — حدد النص أدناه وانسخه يدوياً (Ctrl+C):</div>
  <textarea id="textcopy-area" class="inp" style="min-height:220px;font-family:monospace;font-size:12px;" readonly onclick="this.select()">${d.text||''}</textarea>
  <button class="btn p" style="width:100%;justify-content:center;margin-top:10px;" onclick="document.getElementById('textcopy-area').select()">تحديد الكل</button>
  </div></div>`;
}

window.copyCustomerStatement = async function(custId){
  const c = customers.find(x=>x.id===custId);
  if(!c){ alert('الزبون غير موجود'); return; }

  const custSales = sales.filter(s=>parseInt(s.customer_id)===custId)
    .map(s=>({id:s.id, date:s.date, total:s.total, paid:s.paid, remaining:s.remaining, label:'فاتورة'}));
  const custServices = serviceOrders.filter(o=>parseInt(o.customer_id)===custId)
    .map(o=>({id:o.id, date:o.received_date, total:o.service_fee, paid:o.paid, remaining:o.remaining, label:'خدمة ('+o.service_type+')'}));
  const allOps    = [...custSales, ...custServices].sort((a,b)=>(a.date||'').localeCompare(b.date||''));
  const total     = allOps.reduce((t,s)=>t+(s.total||0),0);
  const paid      = allOps.reduce((t,s)=>t+(s.paid||0),0);
  const remaining = Math.max(0, total-paid);
  const unpaid    = allOps.filter(s=>(s.remaining||0)>0);
  const overdue   = customerOverdueInfo(custId);
  const today     = new Date().toISOString().slice(0,10);

  let txt = `📋 كشف حساب — ${c.name}\n`;
  txt += `📅 تاريخ الكشف: ${today}\n`;
  txt += `━━━━━━━━━━━━━━━\n`;
  txt += `إجمالي المشتريات والخدمات: ${total.toLocaleString()} ${cur()}\n`;
  txt += `إجمالي المدفوع: ${paid.toLocaleString()} ${cur()}\n`;
  txt += `المتبقي المستحق: ${remaining.toLocaleString()} ${cur()}\n`;
  if(overdue) txt += `⏰ متأخر السداد منذ ${overdue.ageDays} يوم\n`;
  if(unpaid.length){
    txt += `━━━━━━━━━━━━━━━\nالعمليات غير المسددة بالكامل:\n`;
    unpaid.forEach(s=>{
      txt += `• ${s.label} #${s.id} بتاريخ ${s.date} — متبقي ${(s.remaining||0).toLocaleString()} ${cur()}\n`;
    });
  }
  txt += `━━━━━━━━━━━━━━━\nشكراً لتعاملكم معنا 🙏\n${sysSettings.system_name||''}`;

  try{
    await navigator.clipboard.writeText(txt);
    alert('✅ تم نسخ كشف الحساب — يمكنك الآن لصقه في واتساب أو أي تطبيق آخر');
  }catch(e){
    // بعض المتصفحات تمنع الوصول لبيانات الحافظة — نعرض نص قابل للتحديد اليدوي كبديل
    MS = {type:'textcopy', data:{title:'كشف حساب '+c.name, text:txt}};
    render();
  }
};

// ══════════════════════════════════════════════
//  مقارنة أسعار الشراء بين الموردين لنفس المنتج
// ══════════════════════════════════════════════
function buildSupplierPriceStats(productId){
  // يرجع مصفوفة: [{supplier, avgPrice, lastPrice, lastDate, count}] لمنتج معيّن
  const stats = {};
  purchases.forEach(p=>{
    if(p.status==='مردود') return;
    (p.items||[]).forEach(it=>{
      if(parseInt(it.product_id)!==parseInt(productId)) return;
      const sid = parseInt(p.supplier_id);
      if(!stats[sid]) stats[sid] = {sum:0, count:0, lastPrice:0, lastDate:''};
      stats[sid].sum += it.price;
      stats[sid].count += 1;
      if(!stats[sid].lastDate || p.date > stats[sid].lastDate){
        stats[sid].lastDate = p.date;
        stats[sid].lastPrice = it.price;
      }
    });
  });
  return Object.entries(stats).map(([sid,s])=>{
    const sup = suppliers.find(x=>x.id===parseInt(sid));
    return {
      supplier: sup || {id:sid, name:'مورد محذوف #'+sid},
      avgPrice: s.sum/s.count,
      lastPrice: s.lastPrice,
      lastDate: s.lastDate,
      count: s.count
    };
  }).sort((a,b)=>a.lastPrice-b.lastPrice);
}

function supplierCompareTableHTML(product, rowsArr){
  const minPrice = Math.min(...rowsArr.map(r=>r.lastPrice));
  return `<div class="card" style="margin-bottom:14px;overflow:hidden;">
    <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;">
      <div style="font-weight:700;color:#f1f5f9;">${product.name}</div>
      <div style="font-size:11px;color:#64748b;margin-top:2px;font-family:monospace;">${product.barcode}</div>
    </div>
    <table>
      <thead><tr><th>المورد</th><th>آخر سعر شراء</th><th>تاريخ آخر شراء</th><th>متوسط السعر</th><th>عدد مرات الشراء</th></tr></thead>
      <tbody>
      ${rowsArr.map(r=>`<tr>
        <td style="font-weight:700;color:#f1f5f9;">${r.supplier.name}</td>
        <td style="font-weight:800;color:${r.lastPrice===minPrice?'#52b788':'#f1f5f9'};">
          ${r.lastPrice.toLocaleString()} ${cur()} ${r.lastPrice===minPrice && rowsArr.length>1?'<span class="badge g" style="font-size:10px;">✅ الأرخص</span>':''}
        </td>
        <td style="color:#94a3b8;">${r.lastDate}</td>
        <td style="color:#60a5fa;">${r.avgPrice.toLocaleString(undefined,{maximumFractionDigits:2})} ${cur()}</td>
        <td><span class="badge b">${r.count}</span></td>
      </tr>`).join('')}
      </tbody>
    </table>
  </div>`;
}

window.renderSupplierCompare = function(){
  const el = document.getElementById('sup-compare-body');
  if(!el) return;
  const pid = document.getElementById('supcmp-product')?.value;

  if(pid){
    const product = products.find(p=>p.id===parseInt(pid));
    const rowsArr = buildSupplierPriceStats(pid);
    if(!product || !rowsArr.length){
      el.innerHTML = '<div class="card" style="padding:24px;text-align:center;color:#64748b;">لا يوجد سجل شراء لهذا المنتج بعد</div>';
      return;
    }
    el.innerHTML = supplierCompareTableHTML(product, rowsArr);
    return;
  }

  // كل المنتجات التي اشتُريت من أكثر من مورد واحد
  const multiSupplierProducts = products
    .map(p=>({product:p, rowsArr: buildSupplierPriceStats(p.id)}))
    .filter(x=>x.rowsArr.length >= 2);

  if(!multiSupplierProducts.length){
    el.innerHTML = '<div class="card" style="padding:24px;text-align:center;color:#64748b;">لا توجد منتجات اشتُريت من أكثر من مورد بعد لعرض مقارنة</div>';
    return;
  }
  el.innerHTML = multiSupplierProducts.map(x=>supplierCompareTableHTML(x.product, x.rowsArr)).join('');
};

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

// ── كشف الزبون التفصيلي ──
window.doCustReport = async function(custIdDirect){
  // يمكن استدعاؤها من زر في جدول الزبائن بـ id مباشر
  let custId, dateFrom, dateTo, resEl, btn;

  if(custIdDirect){
    // استدعاء من تقرير الزبائن (جدول ملخص)
    custId   = custIdDirect;
    dateFrom = '2000-01-01';
    dateTo   = '2099-12-31';
    // نغير التبويب لعرض الكشف
    const rc = document.getElementById('rc');
    if(rc){
      rc.innerHTML = '<div style="text-align:center;padding:30px;"><div class="spin"></div></div>';
      resEl = rc;
    }
  } else {
    // استدعاء من نموذج البحث
    const custSel = document.getElementById('crid');
    const fromEl  = document.getElementById('crf');
    const toEl    = document.getElementById('crt');
    resEl = document.getElementById('crr');
    btn   = document.getElementById('crb');

    if(!custSel || !custSel.value){
      alert('يرجى اختيار الزبون أولاً');
      if(custSel) custSel.focus();
      return;
    }
    custId   = custSel.value;
    dateFrom = fromEl ? fromEl.value : '2000-01-01';
    dateTo   = toEl   ? toEl.value   : '2099-12-31';

    if(resEl) resEl.innerHTML = '<div style="text-align:center;padding:30px;"><div class="spin"></div><div style="color:#64748b;margin-top:10px;font-size:13px;">جاري تحميل الكشف...</div></div>';
    if(btn){ btn.disabled=true; btn.textContent='جاري التحميل...'; }
  }

  try{
    const url = '/api/reports/customer?customer_id='+custId+'&date_from='+dateFrom+'&date_to='+dateTo;
    const data = await api('GET', url);
    if(resEl) resEl.innerHTML = custRepHTML(data);
    setTimeout(()=>{ if(resEl) resEl.scrollIntoView({behavior:'smooth', block:'start'}); }, 150);
  } catch(err){
    if(resEl) resEl.innerHTML = '<div class="err">حدث خطأ: ' + err.message + '</div>';
  } finally {
    if(btn){ btn.disabled=false; btn.textContent='🔍 عرض كشف الزبون'; }
  }
};

function custPaymentsTableHTML(payments){
  if(!payments || !payments.length) return '';
  return `
    <div style="background:#0f1117;padding:10px 14px;border-top:1px solid #1e2537;">
      <div style="font-size:12px;font-weight:700;color:#52b788;margin-bottom:7px;">💳 الدفعات المسجلة</div>
      <table style="margin:0;"><thead><tr>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">التاريخ</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">الطريقة</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">المبلغ</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">رقم الشيك</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">البنك</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">ملاحظات</th>
      </tr></thead><tbody>
      ${payments.map(pay=>`<tr>
        <td style="font-size:12px;padding:5px 8px;color:#94a3b8;">${pay.date}</td>
        <td style="font-size:12px;padding:5px 8px;"><span class="badge ${pay.method==='نقدي'?'g':pay.method==='شيك'?'b':'y'}">${pay.method}</span></td>
        <td style="font-size:13px;padding:5px 8px;font-weight:800;color:#52b788;">${(pay.amount||0).toLocaleString()} ${cur()}</td>
        <td style="font-size:12px;padding:5px 8px;font-family:monospace;color:#60a5fa;">${pay.cheque_no||'—'}</td>
        <td style="font-size:12px;padding:5px 8px;color:#94a3b8;">${pay.cheque_bank||'—'}</td>
        <td style="font-size:12px;padding:5px 8px;color:#64748b;">${esc(pay.notes)||''}</td>
      </tr>`).join('')}
      </tbody></table>
    </div>`;
}

function custSaleCardHTML(s){
  return `
  <div class="card" style="margin-bottom:12px;overflow:hidden;">
    <div style="background:#1a1d27;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">
      <div style="display:flex;align-items:center;gap:12px;">
        <span class="badge g" style="font-size:10px;">🛒 بيع</span>
        <span style="color:#64748b;font-size:13px;">#${s.id}</span>
        <span style="font-weight:800;color:#f1f5f9;">📅 ${s.date}</span>
        <span class="badge ${s.status==='مدفوع'?'g':s.status==='مدفوع جزئياً'?'b':'y'}">${s.status}</span>
        <span class="badge b">${s.pay_method||''}</span>
      </div>
      <div style="display:flex;align-items:center;gap:14px;">
        <div style="text-align:left;font-size:12px;">
          <span style="color:#64748b;">مدفوع: </span><span style="color:#52b788;font-weight:700;">${(s.paid||0).toLocaleString()} ${cur()}</span>
          ${(s.remaining||0)>0?`<span style="color:#64748b;margin-right:8px;"> متبقي: </span><span style="color:#fbbf24;font-weight:700;">${(s.remaining||0).toLocaleString()} ${cur()}</span>`:''}
        </div>
        <span style="font-weight:900;color:#f1f5f9;font-size:15px;">${(s.total||0).toLocaleString()} ${cur()}</span>
      </div>
    </div>
    <table><thead><tr>
      <th style="font-size:12px;">الباركود</th><th style="font-size:12px;">المنتج</th>
      <th style="font-size:12px;">الكمية</th><th style="font-size:12px;">سعر البيع</th><th style="font-size:12px;">الاجمالي</th>
    </tr></thead><tbody>
    ${(s.items&&s.items.length>0)?groupInvoiceItems(s.items).map(item=>`<tr>
      <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${item.barcode||'—'}</td>
      <td style="font-weight:600;color:#f1f5f9;">${esc(item.product_name)||('منتج #'+item.product_id)||'—'}
        ${item.serials&&item.serials.length?`<div style="font-size:10px;color:#52b788;font-family:monospace;margin-top:2px;">📟 ${item.serials.map(esc).join(' ، ')}</div>`:''}
      </td>
      <td style="color:#94a3b8;">${item.qty||0} ${item.unit||'قطعة'}</td>
      <td>${(item.price||0).toLocaleString()} ${cur()}</td>
      <td style="color:#52b788;font-weight:700;">${((item.qty||0)*(item.price||0)).toLocaleString()} ${cur()}</td>
    </tr>`).join(''):'<tr><td colspan="5" style="text-align:center;color:#fbbf24;padding:10px;">لا توجد أصناف</td></tr>'}
    </tbody></table>
    ${custPaymentsTableHTML(s.payments)}
  </div>`;
}

function custServiceCardHTML(so){
  return `
  <div class="card" style="margin-bottom:12px;overflow:hidden;border:1px solid #3d3020;">
    <div style="background:#1a1d27;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">
      <div style="display:flex;align-items:center;gap:12px;">
        <span class="badge y" style="font-size:10px;">🔧 ${esc(so.service_type)||'خدمة'}</span>
        <span style="color:#64748b;font-size:13px;">#${so.id}</span>
        <span style="font-weight:800;color:#f1f5f9;">📅 ${so.date}</span>
        <span class="badge ${so.status==='مدفوع'?'g':so.status==='مدفوع جزئياً'?'b':'y'}">${so.status}</span>
        <span class="badge ${SERVICE_STATUS_CLS[so.workflow_status]||'b'}">${so.workflow_status||''}</span>
      </div>
      <div style="display:flex;align-items:center;gap:14px;">
        <div style="text-align:left;font-size:12px;">
          <span style="color:#64748b;">مدفوع: </span><span style="color:#52b788;font-weight:700;">${(so.paid||0).toLocaleString()} ${cur()}</span>
          ${(so.remaining||0)>0?`<span style="color:#64748b;margin-right:8px;"> متبقي: </span><span style="color:#fbbf24;font-weight:700;">${(so.remaining||0).toLocaleString()} ${cur()}</span>`:''}
        </div>
        <span style="font-weight:900;color:#f1f5f9;font-size:15px;">${(so.total||0).toLocaleString()} ${cur()}</span>
      </div>
    </div>
    <table><thead><tr>
      <th style="font-size:12px;">الباركود</th><th style="font-size:12px;">المنتج</th>
      <th style="font-size:12px;">الكمية</th><th style="font-size:12px;">سعر البيع</th><th style="font-size:12px;">الاجمالي</th>
    </tr></thead><tbody>
      <tr>
        <td style="font-family:monospace;font-size:12px;color:#60a5fa;">خدمة</td>
        <td style="font-weight:600;color:#f1f5f9;">
          ${esc(so.service_type)||'خدمة'}${so.device_desc?' — '+esc(so.device_desc):''}
          ${so.notes?`<div style="font-size:10px;color:#64748b;margin-top:2px;">📝 ${esc(so.notes)}</div>`:''}
        </td>
        <td style="color:#94a3b8;">1</td>
        <td>${(so.total||0).toLocaleString()} ${cur()}</td>
        <td style="color:#52b788;font-weight:700;">${(so.total||0).toLocaleString()} ${cur()}</td>
      </tr>
      ${(so.parts||[]).map(pt=>`<tr>
        <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${pt.barcode||'—'}</td>
        <td style="color:#cbd5e1;">🔩 ${esc(pt.product_name)} <span style="font-size:10px;color:#64748b;">(قطعة مستخدمة)</span></td>
        <td style="color:#94a3b8;">${pt.qty} ${pt.unit||''}</td>
        <td>${(pt.price||0).toLocaleString()} ${cur()}</td>
        <td style="color:#f87171;font-weight:700;">${(pt.qty*pt.price).toLocaleString()} ${cur()}</td>
      </tr>`).join('')}
    </tbody></table>
    ${custPaymentsTableHTML(so.payments)}
  </div>`;
}

function custRepHTML(d){
  const {customer:c,transactions:tx,total,total_paid,total_remaining,all_payments,count,date_from,date_to,account_paid=0}=d;
  const tier = customerTier(c.id);
  const overdue = customerOverdueInfo(c.id);
  return `<div id="spa">
  <div class="card" style="padding:18px;margin-bottom:12px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
      <div><div style="font-size:17px;font-weight:900;color:#f1f5f9;">كشف حساب زبون</div>
        <div style="font-size:13px;color:#64748b;margin-top:3px;">الفترة: ${date_from} الى ${date_to}</div></div>
      <div style="text-align:left;">
        <div style="font-size:15px;font-weight:800;color:#52b788;">${esc(c.name)} ${tier==='vip'?'<span class="badge y" style="font-size:10px;">⭐ زبون مميز</span>':''}</div>
        <div style="font-size:12px;color:#64748b;">${esc(c.phone)||''} ${c.city?'— '+esc(c.city):''}</div>
      </div>
    </div>
    ${overdue?`<div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:13px;color:#f87171;">
      ⏰ هذا الزبون متأخر بالسداد منذ ${overdue.ageDays} يوم — ${overdue.invoiceCount} فاتورة غير مسددة بقيمة ${overdue.totalDue.toLocaleString()} ${cur()}
    </div>`:''}
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
      <div class="stat"><div style="font-size:12px;color:#64748b;">عدد العمليات</div><div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:4px;">${count}</div></div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">الإجمالي (مبيعات + خدمات)</div><div style="font-size:18px;font-weight:800;color:#f1f5f9;margin-top:4px;">${total.toLocaleString()} ${cur()}</div></div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">إجمالي المدفوع</div><div style="font-size:18px;font-weight:800;color:#52b788;margin-top:4px;">${(total_paid||0).toLocaleString()} ${cur()}</div>${account_paid>0?`<div style="font-size:10px;color:#94a3b8;margin-top:2px;">منها ${account_paid.toLocaleString()} ${cur()} دفعات مباشرة</div>`:''}</div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">المتبقي (مستحق)</div><div style="font-size:18px;font-weight:800;color:${(total_remaining||0)>0?'#fbbf24':'#52b788'};margin-top:4px;">${(total_remaining||0).toLocaleString()} ${cur()}</div></div>
    </div>
  </div>
  ${(tx||[]).map(t=>t.kind==='service'?custServiceCardHTML(t):custSaleCardHTML(t)).join('')||'<div class="card" style="padding:28px;text-align:center;color:#475569;">لا توجد عمليات في هذه الفترة</div>'}

  ${(all_payments&&all_payments.length>0)?`
  <div class="card" style="margin-bottom:12px;overflow:hidden;">
    <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;">
      <div style="font-size:14px;font-weight:800;color:#52b788;">📊 سجل الدفعات الكامل للزبون</div>
    </div>
    <table><thead><tr>
      <th>التاريخ</th><th>الفاتورة</th><th>الطريقة</th><th>المبلغ</th><th>رقم الشيك</th><th>البنك</th><th>ملاحظات</th>
    </tr></thead><tbody>
    ${all_payments.map(pay=>`<tr>
      <td style="color:#94a3b8;">${pay.date}</td>
      <td style="color:#64748b;">#${pay.ref_id}</td>
      <td><span class="badge ${pay.method==='نقدي'?'g':pay.method==='شيك'?'b':'y'}">${pay.method}</span></td>
      <td style="font-weight:800;color:#52b788;font-size:14px;">${(pay.amount||0).toLocaleString()} ${cur()}</td>
      <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${pay.cheque_no||'—'}</td>
      <td style="font-size:12px;color:#94a3b8;">${pay.cheque_bank||'—'}</td>
      <td style="font-size:12px;color:#64748b;">${pay.notes||''}</td>
    </tr>`).join('')}
    </tbody></table>
    <div style="text-align:left;padding:10px 16px;border-top:1px solid #1e2537;font-size:15px;font-weight:800;color:#52b788;">
      إجمالي الدفعات: ${all_payments.reduce((s,p)=>s+(p.amount||0),0).toLocaleString()} ${cur()}
    </div>
  </div>`:''}

  ${(tx&&tx.length)?`<div class="card" style="padding:14px;background:linear-gradient(135deg,#1a2e22,#161923);">
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
      <div style="text-align:center;">
        <div style="font-size:12px;color:#94a3b8;">الإجمالي من ${date_from} الى ${date_to}</div>
        <div style="font-size:20px;font-weight:900;color:#f1f5f9;margin-top:4px;">${total.toLocaleString()} ${cur()}</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:12px;color:#94a3b8;">المدفوع</div>
        <div style="font-size:20px;font-weight:900;color:#52b788;margin-top:4px;">${(total_paid||0).toLocaleString()} ${cur()}</div>
        ${account_paid>0?`<div style="font-size:11px;color:#64748b;margin-top:2px;">منها ${account_paid.toLocaleString()} ${cur()} دفعات على الحساب</div>`:''}
      </div>
      <div style="text-align:center;">
        <div style="font-size:12px;color:#94a3b8;">المتبقي المستحق</div>
        <div style="font-size:20px;font-weight:900;color:${(total_remaining||0)>0?'#fbbf24':'#52b788'};margin-top:4px;">${(total_remaining||0).toLocaleString()} ${cur()}</div>
      </div>
    </div>
  </div>`:''}
  </div>
  <div style="display:flex;gap:10px;margin-top:14px;">
    <button class="btn p" onclick="doPrint()">🖨️ طباعة</button>
    <button class="btn s" onclick="doPDF()">📄 تصدير PDF</button>
    <button class="btn s" onclick="copyCustomerStatement(${c.id})">📋 نسخ كشف الحساب (واتساب)</button>
  </div>`;
}

function supRepHTML(d){
  const {supplier:s,purchases:ps,total,total_paid,total_remaining,all_payments,count,date_from,date_to,account_paid=0}=d;
  return `<div id="spa">
  <div class="card" style="padding:18px;margin-bottom:12px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
      <div><div style="font-size:17px;font-weight:900;color:#f1f5f9;">كشف حساب مورد</div>
        <div style="font-size:13px;color:#64748b;margin-top:3px;">الفترة: ${date_from} الى ${date_to}</div></div>
      <div style="text-align:left;"><div style="font-size:15px;font-weight:800;color:#52b788;">${s.name}</div>
        <div style="font-size:12px;color:#64748b;">${s.phone||''} ${s.city?'— '+s.city:''}</div></div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
      <div class="stat"><div style="font-size:12px;color:#64748b;">عدد الفواتير</div><div style="font-size:18px;font-weight:800;color:#60a5fa;margin-top:4px;">${count}</div></div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">إجمالي المشتريات</div><div style="font-size:18px;font-weight:800;color:#f1f5f9;margin-top:4px;">${total.toLocaleString()} ${cur()}</div></div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">إجمالي المدفوع</div><div style="font-size:18px;font-weight:800;color:#52b788;margin-top:4px;">${(total_paid||0).toLocaleString()} ${cur()}</div>${account_paid>0?`<div style="font-size:10px;color:#94a3b8;margin-top:2px;">منها ${account_paid.toLocaleString()} ${cur()} دفعات مباشرة</div>`:''}</div>
      <div class="stat"><div style="font-size:12px;color:#64748b;">المتبقي (مستحق)</div><div style="font-size:18px;font-weight:800;color:${(total_remaining||0)>0?'#f87171':'#52b788'};margin-top:4px;">${(total_remaining||0).toLocaleString()} ${cur()}</div></div>
    </div>
  </div>
  ${ps.map(p=>`
  <div class="card" style="margin-bottom:12px;overflow:hidden;">
    <div style="background:#1a1d27;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">
      <div style="display:flex;align-items:center;gap:12px;">
        <span style="color:#64748b;font-size:13px;">#${p.id}</span>
        <span style="font-weight:800;color:#f1f5f9;">📅 ${p.date}</span>
        <span class="badge ${p.status==='مدفوع'?'g':p.status==='مدفوع جزئياً'?'b':p.status==='معلق'?'y':'r'}">${p.status}</span>
      </div>
      <div style="display:flex;align-items:center;gap:14px;">
        <div style="text-align:left;font-size:12px;">
          <span style="color:#64748b;">مدفوع: </span><span style="color:#52b788;font-weight:700;">${(p.paid||0).toLocaleString()} ${cur()}</span>
          ${(p.remaining||0)>0?`<span style="color:#64748b;margin-right:8px;"> متبقي: </span><span style="color:#f87171;font-weight:700;">${(p.remaining||0).toLocaleString()} ${cur()}</span>`:''}
        </div>
        <span style="font-weight:900;color:#f1f5f9;font-size:15px;">${(p.total||0).toLocaleString()} ${cur()}</span>
      </div>
    </div>
    <table><thead><tr>
      <th style="font-size:12px;">الباركود</th><th style="font-size:12px;">المنتج</th>
      <th style="font-size:12px;">الكمية</th><th style="font-size:12px;">سعر الوحدة</th><th style="font-size:12px;">الاجمالي</th>
    </tr></thead><tbody>
    ${(p.items&&p.items.length>0) ? groupInvoiceItems(p.items).map(item=>`<tr>
      <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${item.barcode||item.product_id||'—'}</td>
      <td style="font-weight:600;color:#f1f5f9;">${esc(item.product_name)||('منتج #'+item.product_id)||'—'}
        ${item.serials&&item.serials.length?`<div style="font-size:10px;color:#52b788;font-family:monospace;margin-top:2px;">📟 ${item.serials.map(esc).join(' ، ')}</div>`:''}
      </td>
      <td style="color:#94a3b8;">${item.qty||0} ${item.unit||'قطعة'}</td>
      <td>${(item.price||0).toLocaleString()} ${cur()}</td>
      <td style="color:#52b788;font-weight:700;">${((item.qty||0)*(item.price||0)).toLocaleString()} ${cur()}</td>
    </tr>`).join('') : '<tr><td colspan="5" style="text-align:center;color:#fbbf24;padding:10px;">لا توجد أصناف مسجلة</td></tr>'}
    </tbody></table>
    ${(p.payments&&p.payments.length>0)?`
    <div style="background:#0f1117;padding:10px 14px;border-top:1px solid #1e2537;">
      <div style="font-size:12px;font-weight:700;color:#60a5fa;margin-bottom:7px;">💳 الدفعات المسجلة</div>
      <table style="margin:0;"><thead><tr>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">التاريخ</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">الطريقة</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">المبلغ</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">رقم الشيك</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">البنك</th>
        <th style="background:#0d1018;font-size:11px;padding:5px 8px;">ملاحظات</th>
      </tr></thead><tbody>
      ${p.payments.map(pay=>`<tr>
        <td style="font-size:12px;padding:5px 8px;color:#94a3b8;">${pay.date}</td>
        <td style="font-size:12px;padding:5px 8px;"><span class="badge ${pay.method==='نقدي'?'g':pay.method==='شيك'?'b':'y'}">${pay.method}</span></td>
        <td style="font-size:13px;padding:5px 8px;font-weight:800;color:#52b788;">${(pay.amount||0).toLocaleString()} ${cur()}</td>
        <td style="font-size:12px;padding:5px 8px;font-family:monospace;color:#60a5fa;">${pay.cheque_no||'—'}</td>
        <td style="font-size:12px;padding:5px 8px;color:#94a3b8;">${pay.cheque_bank||'—'}</td>
        <td style="font-size:12px;padding:5px 8px;color:#64748b;">${pay.notes||''}</td>
      </tr>`).join('')}
      </tbody></table>
    </div>`:''}
  </div>`).join('')||'<div class="card" style="padding:28px;text-align:center;color:#475569;">لا توجد مشتريات في هذه الفترة</div>'}

  ${(all_payments&&all_payments.length>0)?`
  <div class="card" style="margin-bottom:12px;overflow:hidden;">
    <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;">
      <div style="font-size:14px;font-weight:800;color:#60a5fa;">📊 سجل الدفعات الكامل للمورد</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">جميع الدفعات المسجلة بغض النظر عن الفترة</div>
    </div>
    <table><thead><tr>
      <th>التاريخ</th><th>الفاتورة</th><th>الطريقة</th><th>المبلغ</th><th>رقم الشيك</th><th>البنك</th><th>ملاحظات</th>
    </tr></thead><tbody>
    ${all_payments.map(pay=>`<tr>
      <td style="color:#94a3b8;">${pay.date}</td>
      <td style="color:#64748b;">#${pay.ref_id}</td>
      <td><span class="badge ${pay.method==='نقدي'?'g':pay.method==='شيك'?'b':'y'}">${pay.method}</span></td>
      <td style="font-weight:800;color:#52b788;font-size:14px;">${(pay.amount||0).toLocaleString()} ${cur()}</td>
      <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${pay.cheque_no||'—'}</td>
      <td style="font-size:12px;color:#94a3b8;">${pay.cheque_bank||'—'}</td>
      <td style="font-size:12px;color:#64748b;">${pay.notes||''}</td>
    </tr>`).join('')}
    </tbody></table>
    <div style="text-align:left;padding:10px 16px;border-top:1px solid #1e2537;font-size:15px;font-weight:800;color:#52b788;">
      إجمالي الدفعات: ${all_payments.reduce((s,p)=>s+(p.amount||0),0).toLocaleString()} ${cur()}
    </div>
  </div>`:''}

  ${ps.length?`<div class="card" style="padding:14px;background:linear-gradient(135deg,#1a2e22,#161923);">
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
      <div style="text-align:center;">
        <div style="font-size:12px;color:#94a3b8;">الإجمالي من ${date_from} الى ${date_to}</div>
        <div style="font-size:20px;font-weight:900;color:#f1f5f9;margin-top:4px;">${total.toLocaleString()} ${cur()}</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:12px;color:#94a3b8;">المدفوع</div>
        <div style="font-size:20px;font-weight:900;color:#52b788;margin-top:4px;">${(total_paid||0).toLocaleString()} ${cur()}</div>
        ${account_paid>0?`<div style="font-size:11px;color:#64748b;margin-top:2px;">منها ${account_paid.toLocaleString()} ${cur()} دفعات على الحساب</div>`:''}
      </div>
      <div style="text-align:center;">
        <div style="font-size:12px;color:#94a3b8;">المتبقي المستحق</div>
        <div style="font-size:20px;font-weight:900;color:${(total_remaining||0)>0?'#f87171':'#52b788'};margin-top:4px;">${(total_remaining||0).toLocaleString()} ${cur()}</div>
      </div>
    </div>
  </div>`:''}
  </div>
  <div style="display:flex;gap:10px;margin-top:14px;">
    <button class="btn p" onclick="doPrint()">🖨️ طباعة</button>
    <button class="btn s" onclick="doPDF()">📄 تصدير PDF</button>
    <button class="btn s" onclick='exportSupplierExcel(${JSON.stringify(d).replace(/'/g,"&#39;")})'>📊 تصدير Excel</button>
  </div>`;
}

// ── تصدير كشف حساب المورد إلى Excel (ملف .xlsx حقيقي عبر SheetJS) ──
window.exportSupplierExcel = function(d){
  if(typeof XLSX === 'undefined'){
    alert('تعذر تحميل مكتبة تصدير Excel — تأكد من الاتصال بالإنترنت وأعد المحاولة');
    return;
  }
  const s = d.supplier;
  const invoiceRows = (d.purchases||[]).map(p=>({
    'رقم الفاتورة': p.id,
    'التاريخ': p.date,
    'الإجمالي': p.total,
    'المدفوع': p.paid||0,
    'المتبقي': p.remaining||0,
    'الحالة': p.status
  }));
  const paymentRows = (d.all_payments||[]).map(pay=>({
    'التاريخ': pay.date,
    'الفاتورة': pay.ref_id,
    'الطريقة': pay.method,
    'المبلغ': pay.amount,
    'رقم الشيك': pay.cheque_no||'',
    'البنك': pay.cheque_bank||'',
    'ملاحظات': pay.notes||''
  }));
  const summaryRows = [
    {'البيان':'اسم المورد','القيمة':s.name},
    {'البيان':'الفترة','القيمة': d.date_from+' الى '+d.date_to},
    {'البيان':'عدد الفواتير','القيمة': d.count},
    {'البيان':'إجمالي المشتريات','القيمة': d.total},
    {'البيان':'إجمالي المدفوع','القيمة': d.total_paid},
    {'البيان':'المتبقي (مستحق)','القيمة': d.total_remaining},
  ];

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(summaryRows), 'ملخص');
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(invoiceRows), 'الفواتير');
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(paymentRows), 'الدفعات');
  XLSX.writeFile(wb, `كشف_حساب_${s.name}_${d.date_from}_${d.date_to}.xlsx`);
};

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

// ── إضافة زبون سريع من POS ──
window.openQuickCustomer = function(){
  if(document.getElementById('pqc-modal')) return;
  const div = document.createElement('div');
  div.id = 'pqc-modal';
  div.className = 'overlay';
  div.innerHTML = `<div class="modal" style="max-width:380px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <div style="font-size:15px;font-weight:700;color:#f1f5f9;">➕ إضافة زبون جديد</div>
      <button class="btn s" style="padding:4px 9px;" onclick="document.getElementById('pqc-modal')?.remove()">✕</button>
    </div>
    <div id="pqc-err" style="color:#f87171;font-size:12px;margin-bottom:8px;display:none;"></div>
    <div style="margin-bottom:12px;">
      <label class="lbl">الاسم <span style="color:#f87171;">*</span></label>
      <input class="inp" id="pqc-name" placeholder="اسم الزبون" style="width:100%;"/>
    </div>
    <div style="margin-bottom:16px;">
      <label class="lbl">رقم الهاتف</label>
      <input class="inp" id="pqc-phone" placeholder="رقم الهاتف (اختياري)" style="width:100%;"/>
    </div>
    <div style="display:flex;gap:8px;">
      <button class="btn p" id="pqc-save" style="flex:1;">💾 حفظ</button>
      <button class="btn s" onclick="document.getElementById('pqc-modal')?.remove()">إلغاء</button>
    </div>
  </div>`;
  document.body.appendChild(div);
  document.getElementById('pqc-name')?.focus();
  document.getElementById('pqc-save')?.addEventListener('click', async ()=>{
    const name = document.getElementById('pqc-name')?.value.trim();
    const errEl = document.getElementById('pqc-err');
    if(!errEl) return;
    if(!name){ errEl.textContent='الاسم مطلوب'; errEl.style.display='block'; return; }
    errEl.style.display='none';
    try{
      const cust = await api('POST','/api/customers',{name,phone:document.getElementById('pqc-phone')?.value||''});
      customers.push(cust);
      const sel = document.getElementById('pc');
      if(sel){
        const opt = document.createElement('option');
        opt.value = cust.id; opt.textContent = cust.name;
        sel.appendChild(opt);
        sel.value = cust.id;
      }
      document.getElementById('pqc-modal')?.remove();
    }catch(e){ errEl.textContent=e.message; errEl.style.display='block'; }
  });
};

// فتح نموذج إنشاء منتج جديد من داخل فاتورة شراء (جديدة أو قيد التعديل) دون فقدان بيانات الفاتورة الحالية
window.openQuickProduct = function(fromType){
  const supplierField = fromType==='editpur' ? 'edit-pus' : 'pus';
  const dateField      = fromType==='editpur' ? 'edit-pud' : 'pud';
  const statusField    = fromType==='editpur' ? 'edit-pust' : 'pust';
  // نحفظ حالة الفاتورة الحالية بالكامل (بما فيها الأصناف المضافة إلى الآن) لاستعادتها بعد إنشاء المنتج
  _purDraftStash = fromType==='editpur'
    ? {type:'editpur', editId:MS.editId, data:MS.data}
    : {type:'purform'};
  if(fromType!=='editpur'){
    // فاتورة الشراء الجديدة تفقد حقول المورد/التاريخ/الحالة عند إعادة الرسم — نحفظها لإعادة تطبيقها
    _pendingPurDraftFields = {
      sup: document.getElementById(supplierField)?.value || '',
      date: document.getElementById(dateField)?.value || '',
      status: document.getElementById(statusField)?.value || ''
    };
  }
  MS = {type:'pform', data:{}, _fromPurchase:true};
  render();
};

function modalHTML(){
  if(!MS) return '';
  if(MS.type==='pform')    return prodModal(MS.data||{});
  if(MS.type==='eform')    return entModal(MS.data||{});
  if(MS.type==='purform')  return purModal();
  if(MS.type==='editpur')  return editPurModal(MS.data||{});
  if(MS.type==='retpur')   return returnPurModal(MS.data||{});
  if(MS?.type==='payform') return payModal(MS.data||{});
  if(MS?.type==='payhist') return payHistModal(MS.data||{});
  if(MS.type==='userform') return userModal(MS.data||{});
  if(MS.type==='chequeStatus') return chequeStatusModal(MS.data||{});
  if(MS.type==='saleslist')  return salesListModal();
  if(MS.type==='editsale')   return editSaleModal(MS.data||{});
  if(MS.type==='accountpay') return accountPayModal(MS.data||{});
  if(MS.type==='editpayment') return editPaymentModal(MS.data||{});
  if(MS.type==='done')     return doneModal(MS.data);
  if(MS.type==='unitpicker') return unitPickerModal(MS.data||{});
  if(MS.type==='camerascan') return cameraScanModal();
  if(MS.type==='serialsentry') return serialsEntryModal(MS.data||{});
  if(MS.type==='serviceform') return serviceFormModal(MS.data||{});
  if(MS.type==='servicedetail') return serviceDetailModal(MS.data||{});
  if(MS.type==='textcopy') return textCopyModal(MS.data||{});
  if(MS.type==='expenseform') return expenseFormModal(MS.data||{});
  if(MS.type==='employeeform') return employeeFormModal(MS.data||{});
  if(MS.type==='employeedetail') return employeeDetailModal(MS.data||{});
  if(MS.type==='recurringform') return recurringFormModal(MS.data||{});
  if(MS.type==='payrecurring') return payRecurringModal(MS.data||{});
  if(MS.type==='payrollform') return payrollFormModal(MS.data||{});
  return '';
}

// ── مودال تحديث حالة الشيك ──
function chequeStatusModal(d){
  const statuses = ['قيد التحصيل','محصّل','مرتجع','مؤجل'];
  const icons    = {'قيد التحصيل':'⏳','محصّل':'✅','مرتجع':'↩️','مؤجل':'📅'};
  const hasImg   = d.currentImage && d.currentImage.startsWith('data:image');
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
    <div style="font-size:16px;font-weight:800;color:#f1f5f9;">🏦 تحديث حالة الشيك #${d.id}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>

  <!-- حالة الشيك -->
  <div style="margin-bottom:14px;">
    <label class="lbl">حالة الشيك <span style="color:#f87171;">*</span></label>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:6px;">
      ${statuses.map(s=>`
      <div onclick="selectChqStatus('${s}')" id="cst-${s.replace(/[^a-zA-Z0-9]/g,'_')}"
        style="display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:8px;cursor:pointer;
               border:2px solid ${d.currentStatus===s?'#2d6a4f':'#1e2537'};
               background:${d.currentStatus===s?'rgba(45,106,79,.15)':'#1a1d27'};transition:all .15s;">
        <span style="font-size:16px;">${icons[s]}</span>
        <span style="font-size:13px;font-weight:600;color:#f1f5f9;">${s}</span>
        ${d.currentStatus===s?'<span style="margin-right:auto;color:#52b788;font-size:14px;">✓</span>':''}
      </div>`).join('')}
    </div>
  </div>

  <!-- صورة الشيك -->
  <div style="margin-bottom:14px;">
    <label class="lbl">📷 صورة الشيك</label>
    <div id="cst-img-wrap" style="margin-top:6px;">
      ${hasImg ? `
      <div id="cst-img-preview" style="position:relative;margin-bottom:8px;">
        <img id="cst-img-tag" src="${d.currentImage}"
          style="width:100%;max-height:220px;object-fit:contain;border-radius:8px;
                 border:1px solid #2d3349;background:#0f1018;cursor:zoom-in;"
          onclick="window.open(this.src,'_blank')"/>
        <div style="position:absolute;top:6px;left:6px;display:flex;gap:4px;">
          <button onclick="window.open(document.getElementById('cst-img-tag').src,'_blank')"
            style="background:#1a1d27;border:1px solid #2d3349;color:#60a5fa;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">🔍 تكبير</button>
          <button onclick="cstRemoveImg()"
            style="background:#3d1515;border:none;color:#f87171;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">✕ حذف</button>
        </div>
      </div>` : ''}
      <label id="cst-upload-btn" style="display:${hasImg?'none':'flex'};align-items:center;gap:10px;background:#161923;
        border:2px dashed #2d3349;border-radius:8px;padding:12px 16px;cursor:pointer;"
        onmouseover="this.style.borderColor='#2d6a4f'" onmouseout="this.style.borderColor='#2d3349'">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
        <div><div style="font-size:13px;font-weight:600;color:#94a3b8;">${hasImg?'تغيير صورة الشيك':'رفع صورة الشيك'}</div>
        <div style="font-size:11px;color:#475569;margin-top:2px;">JPG, PNG, WEBP — حتى 5MB</div></div>
        <input type="file" id="cst-img-input" accept="image/*" style="display:none;" onchange="cstPreviewImg(this)"/>
      </label>
      ${hasImg?`<button onclick="document.getElementById('cst-upload-btn').style.display='flex';document.getElementById('cst-img-preview').style.display='none'"
        style="margin-top:6px;background:transparent;border:1px solid #2d3349;color:#94a3b8;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;width:100%;">
        🔄 تغيير الصورة</button>`:''}
    </div>
  </div>

  <!-- ملاحظات -->
  <div style="margin-bottom:16px;">
    <label class="lbl">ملاحظات</label>
    <textarea class="inp" id="cst-notes" style="min-height:60px;" placeholder="سبب التغيير، تاريخ التحصيل الفعلي...">${d.currentNotes||''}</textarea>
  </div>

  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 حفظ التحديث</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

let _selectedChqStatus = null;
window.selectChqStatus = function(status){
  _selectedChqStatus = status;
  ['قيد التحصيل','محصّل','مرتجع','مؤجل'].forEach(s=>{
    const el = document.getElementById('cst-'+s.replace(/[^a-zA-Z0-9]/g,'_'));
    if(!el) return;
    if(s===status){
      el.style.border='2px solid #2d6a4f';
      el.style.background='rgba(45,106,79,.15)';
      if(!el.querySelector('.cst-chk'))
        el.innerHTML += '<span class="cst-chk" style="margin-right:auto;color:#52b788;font-size:14px;">✓</span>';
    } else {
      el.style.border='2px solid #1e2537';
      el.style.background='#1a1d27';
      el.querySelector('.cst-chk')?.remove();
    }
  });
};

// معاينة الصورة داخل مودال الحالة
window.cstPreviewImg = function(input){
  const file = input.files[0];
  if(!file) return;
  if(file.size > 5*1024*1024){ alert('الصورة أكبر من 5MB'); input.value=''; return; }
  const reader = new FileReader();
  reader.onload = function(e){
    let prev = document.getElementById('cst-img-preview');
    if(!prev){
      prev = document.createElement('div');
      prev.id = 'cst-img-preview';
      prev.style.cssText = 'position:relative;margin-bottom:8px;';
      prev.innerHTML = '<img id="cst-img-tag" style="width:100%;max-height:220px;object-fit:contain;border-radius:8px;border:1px solid #2d3349;background:#0f1018;cursor:zoom-in;" onclick="window.open(this.src,\'_blank\')"/>'
        + '<div style="position:absolute;top:6px;left:6px;display:flex;gap:4px;">'
        + '<button onclick="window.open(document.getElementById(\'cst-img-tag\').src,\'_blank\')" style="background:#1a1d27;border:1px solid #2d3349;color:#60a5fa;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">🔍 تكبير</button>'
        + '<button onclick="cstRemoveImg()" style="background:#3d1515;border:none;color:#f87171;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">✕ حذف</button></div>';
      const wrap = document.getElementById('cst-img-wrap');
      if(wrap) wrap.insertBefore(prev, wrap.firstChild);
    }
    const tag = document.getElementById('cst-img-tag');
    if(tag) tag.src = e.target.result;
    prev.style.display = 'block';
    const btn = document.getElementById('cst-upload-btn');
    if(btn) btn.style.display = 'none';
  };
  reader.readAsDataURL(file);
};

window.cstRemoveImg = function(){
  const inp  = document.getElementById('cst-img-input');
  const prev = document.getElementById('cst-img-preview');
  const btn  = document.getElementById('cst-upload-btn');
  if(inp)  inp.value = '';
  if(prev) prev.style.display = 'none';
  if(btn)  btn.style.display = 'flex';
  window._cstDeleteImage = true;
};

// ── مودال المستخدم ──
function userModal(usr){
  const isEdit = !!usr.id;
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">${isEdit?'✏️ تعديل المستخدم':'👤 إضافة مستخدم جديد'}</div>
      ${isEdit?`<div style="font-size:12px;color:#60a5fa;font-family:monospace;margin-top:2px;">@${usr.username}</div>`:''}
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2">
    ${!isEdit?`<div style="grid-column:span 2;"><label class="lbl">اسم المستخدم <span style="color:#f87171;">*</span></label>
      <input class="inp" id="uf-username" placeholder="بدون مسافات..." value="${usr.username||''}"/>
    </div>`:''}
    <div style="grid-column:span 2;"><label class="lbl">الاسم الكامل</label>
      <input class="inp" id="uf-fullname" placeholder="الاسم كما يظهر في النظام..." value="${usr.full_name||''}"/>
    </div>
    <div><label class="lbl">${isEdit?'كلمة مرور جديدة (اتركها فارغة للإبقاء)':'كلمة المرور <span style="color:#f87171;">*</span>'}</label>
      <input class="inp" type="password" id="uf-pw" placeholder="${isEdit?'اتركها فارغة لعدم التغيير...':'4 أحرف على الأقل...'}"/>
    </div>
    <div><label class="lbl">تأكيد كلمة المرور</label>
      <input class="inp" type="password" id="uf-pw2" placeholder="أعد الإدخال..."/>
    </div>
    <div><label class="lbl">الصلاحية <span style="color:#f87171;">*</span></label>
      <select class="inp" id="uf-role">
        <option value="user"${(!usr.role||usr.role==='user')?' selected':''}>👤 مستخدم عادي</option>
        <option value="cashier"${usr.role==='cashier'?' selected':''}>💰 كاشير</option>
        <option value="admin"${usr.role==='admin'?' selected':''}>🔑 مدير</option>
      </select>
    </div>
    <div><label class="lbl">الحالة</label>
      <select class="inp" id="uf-active">
        <option value="1"${(usr.is_active===undefined||usr.is_active)?' selected':''}>✅ نشط</option>
        <option value="0"${usr.is_active===0?' selected':''}>🚫 موقوف</option>
      </select>
    </div>
  </div>
  <div style="background:#1a1d27;border-radius:8px;padding:12px;margin-top:14px;margin-bottom:16px;">
    <div style="font-size:12px;font-weight:700;color:#94a3b8;margin-bottom:6px;">🔑 الصلاحيات لكل دور:</div>
    <div style="font-size:12px;color:#64748b;line-height:1.8;">
      <span class="badge r">مدير</span> — وصول كامل لجميع الصفحات والإعدادات<br/>
      <span class="badge b">كاشير</span> — نقطة البيع + عرض المنتجات فقط<br/>
      <span class="badge g">مستخدم</span> — جميع الصفحات بدون الإعدادات والمستخدمين
    </div>
  </div>
  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 ${isEdit?'حفظ التعديلات':'إضافة المستخدم'}</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

// ── مودال تعديل دفعة ──
function editPaymentModal(p){
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">✏️ تعديل دفعة #${p.id}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">${p.ref_type==='purchase'?'فاتورة شراء':'فاتورة بيع'} #${p.ref_id}</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2" style="margin-bottom:12px;">
    <div><label class="lbl">المبلغ <span style="color:#f87171;">*</span></label>
      <input class="inp" type="number" id="ep-amount" min="0.01" step="0.01" value="${p.amount}"/>
    </div>
    <div><label class="lbl">طريقة الدفع</label>
      <select class="inp" id="ep-method" onchange="epToggleCheque(this.value)">
        ${['نقدي','شيك','تحويل بنكي','بطاقة'].map(m=>`<option${p.method===m?' selected':''}>${m}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">التاريخ</label>
      <input class="inp" type="date" id="ep-date" value="${p.date}"/>
    </div>
    <div><label class="lbl">ملاحظات</label>
      <input class="inp" id="ep-notes" value="${p.notes||''}"/>
    </div>
  </div>
  <div id="ep-cheque-fields" style="display:${p.method==='شيك'?'block':'none'};background:#1a1d27;border-radius:8px;padding:12px;margin-bottom:12px;">
    <div style="font-size:12px;font-weight:700;color:#60a5fa;margin-bottom:8px;">🏦 بيانات الشيك</div>
    <div class="g2">
      <div><label class="lbl">رقم الشيك</label><input class="inp" id="ep-cheque-no" value="${p.cheque_no||''}"/></div>
      <div><label class="lbl">تاريخ الشيك</label><input class="inp" type="date" id="ep-cheque-date" value="${p.cheque_date||''}"/></div>
      <div style="grid-column:span 2"><label class="lbl">اسم البنك</label><input class="inp" id="ep-cheque-bank" value="${p.cheque_bank||''}"/></div>
    </div>
    <div style="margin-top:12px;">
      <label class="lbl">📷 صورة الشيك</label>
      <div id="ep-img-wrap" style="margin-top:6px;">
        ${(p.cheque_image && p.cheque_image.startsWith('data:image')) ? `
        <div id="ep-img-preview" style="position:relative;margin-bottom:8px;">
          <img id="ep-img-tag" src="${p.cheque_image}"
            style="width:100%;max-height:200px;object-fit:contain;border-radius:8px;border:1px solid #2d3349;background:#0f1018;cursor:zoom-in;"
            onclick="window.open(this.src,'_blank')"/>
          <div style="position:absolute;top:6px;left:6px;display:flex;gap:4px;">
            <button onclick="window.open(document.getElementById('ep-img-tag').src,'_blank')"
              style="background:#1a1d27;border:1px solid #2d3349;color:#60a5fa;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">🔍 تكبير</button>
            <button onclick="epRemoveImg()"
              style="background:#3d1515;border:none;color:#f87171;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">✕ حذف</button>
          </div>
        </div>` : `<img id="ep-img-tag" style="display:none;"/>`}
        <label id="ep-upload-btn" style="display:${(p.cheque_image && p.cheque_image.startsWith('data:image'))?'none':'flex'};align-items:center;gap:10px;background:#161923;border:2px dashed #2d3349;border-radius:8px;padding:12px 16px;cursor:pointer;" onmouseover="this.style.borderColor='#2d6a4f'" onmouseout="this.style.borderColor='#2d3349'">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          <div><div style="font-size:13px;font-weight:600;color:#94a3b8;">${(p.cheque_image)?'تغيير صورة الشيك':'رفع صورة الشيك'}</div>
          <div style="font-size:11px;color:#475569;margin-top:2px;">JPG, PNG, WEBP — حتى 5MB</div></div>
          <input type="file" id="ep-cheque-img" accept="image/*" style="display:none;" onchange="epPreviewImg(this)"/>
        </label>
      </div>
    </div>
  </div>
  <div style="background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.2);border-radius:8px;padding:10px;margin-bottom:14px;font-size:12px;color:#94a3b8;">
    ℹ️ سيتم تحديث حالة الفاتورة المرتبطة تلقائياً بعد التعديل
  </div>
  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 حفظ التعديل</button>
    <button class="btn d" onclick="deletePaymentFromEdit(${p.id})">🗑️ حذف الدفعة</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

window.epToggleCheque = function(val){
  const el = document.getElementById('ep-cheque-fields');
  if(el) el.style.display = val==='شيك' ? 'block' : 'none';
};

// معاينة صورة الشيك في مودال تعديل الدفعة
window.epPreviewImg = function(input){
  const file = input.files[0];
  if(!file) return;
  if(file.size > 5*1024*1024){ alert('الصورة أكبر من 5MB'); input.value=''; return; }
  const reader = new FileReader();
  reader.onload = function(e){
    let prev = document.getElementById('ep-img-preview');
    if(!prev){
      prev = document.createElement('div');
      prev.id = 'ep-img-preview';
      prev.style.cssText = 'position:relative;margin-bottom:8px;';
      prev.innerHTML = '<img id="ep-img-tag" style="width:100%;max-height:200px;object-fit:contain;border-radius:8px;border:1px solid #2d3349;background:#0f1018;cursor:zoom-in;" onclick="window.open(this.src,\'_blank\')"/>'
        + '<div style="position:absolute;top:6px;left:6px;display:flex;gap:4px;">'
        + '<button onclick="window.open(document.getElementById(\'ep-img-tag\').src,\'_blank\')" style="background:#1a1d27;border:1px solid #2d3349;color:#60a5fa;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">🔍 تكبير</button>'
        + '<button onclick="epRemoveImg()" style="background:#3d1515;border:none;color:#f87171;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;">✕ حذف</button></div>';
      const wrap = document.getElementById('ep-img-wrap');
      if(wrap) wrap.insertBefore(prev, wrap.firstChild);
    }
    const tag = document.getElementById('ep-img-tag');
    if(tag) tag.src = e.target.result;
    prev.style.display = 'block';
    const btn = document.getElementById('ep-upload-btn');
    if(btn) btn.style.display = 'none';
  };
  reader.readAsDataURL(file);
};

window.epRemoveImg = function(){
  const inp  = document.getElementById('ep-cheque-img');
  const tag  = document.getElementById('ep-img-tag');
  const prev = document.getElementById('ep-img-preview');
  const btn  = document.getElementById('ep-upload-btn');
  if(inp)  inp.value = '';
  if(tag)  tag.src = '';
  if(prev) prev.style.display = 'none';
  if(btn)  btn.style.display = 'flex';
  window._epDeleteImage = true;
};

window.deletePaymentFromEdit = async function(id){
  if(!confirm('هل تريد حذف هذه الدفعة نهائياً؟\nسيتم تحديث حالة الفاتورة المرتبطة.')) return;
  try{
    await api('DELETE','/api/payments/'+id);
    await loadAll();
    closeM();
  }catch(e){ alert('خطأ: '+e.message); }
};

// فتح مودال تعديل دفعة (من أي مكان عبر معرف الدفعة)
window.openEditPayment = function(payment){
  window._epDeleteImage = false;
  MS = {type:'editpayment', data: payment};
  render();
};
function payModal(d){
  const today = new Date().toISOString().slice(0,10);
  const paidSoFar = d.paid || 0;
  const remaining = Math.max(0, Math.abs(d.total||0) - paidSoFar);
  return '<div class="overlay" id="mover"><div class="modal" style="max-width:520px;">'
  + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">'
    + '<div><div style="font-size:16px;font-weight:700;color:#f1f5f9;">💳 إضافة دفعة</div>'
    + '<div style="font-size:12px;color:#64748b;margin-top:2px;">'+(d.ref_type==='purchase'?'فاتورة شراء':d.ref_type==='service'?'طلب خدمة':'فاتورة بيع')+' #'+d.ref_id+' — '+(d.party_name||'')+'</div></div>'
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
    + '<div style="margin-top:12px;">'
      + '<label class="lbl">📷 صورة الشيك</label>'
      + '<div id="cheque-img-wrap" style="margin-top:6px;">'
        + '<label style="display:flex;align-items:center;gap:10px;background:#161923;border:2px dashed #2d3349;border-radius:8px;padding:12px 16px;cursor:pointer;transition:border .2s;" onmouseover="this.style.borderColor=\'#2d6a4f\'" onmouseout="this.style.borderColor=\'#2d3349\'">'
          + '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>'
          + '<div><div style="font-size:13px;font-weight:600;color:#94a3b8;">اضغط لرفع صورة الشيك</div>'
          + '<div style="font-size:11px;color:#475569;margin-top:2px;">JPG, PNG, WEBP — حتى 5MB</div></div>'
          + '<input type="file" id="pay-cheque-img" accept="image/*" style="display:none;" onchange="previewChequeImg(this)"/>'
        + '</label>'
        + '<div id="cheque-img-preview" style="display:none;margin-top:8px;position:relative;">'
          + '<img id="cheque-img-tag" style="width:100%;max-height:200px;object-fit:contain;border-radius:8px;border:1px solid #2d3349;background:#0f1018;"/>'
          + '<button onclick="removeChequeImg()" style="position:absolute;top:6px;left:6px;background:#3d1515;border:none;color:#f87171;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:12px;">✕ حذف</button>'
        + '</div>'
      + '</div>'
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
    + '<td style="font-weight:800;color:#52b788;">'+p.amount.toLocaleString()+' '+cur()+'</td>'
    + '<td style="font-size:12px;color:#64748b;">'+(p.cheque_no?'#'+p.cheque_no+' '+p.cheque_bank:'')+'</td>'
    + '<td style="font-size:12px;color:#94a3b8;">'+(p.notes||'')+'</td>'
    + '<td><div style="display:flex;gap:4px;">'
      + '<button class="btn s" style="padding:3px 7px;" onclick=\'openEditPayment('+JSON.stringify(p).replace(/'/g,"&#39;")+')\'>✏️</button>'
      + '<button class="btn d" style="padding:3px 7px;" onclick="deletePay('+p.id+')">🗑️</button>'
    + '</div></td>'
  + '</tr>').join('');
  return '<div class="overlay" id="mover"><div class="modal" style="max-width:640px;">'
  + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
    + '<div><div style="font-size:16px;font-weight:700;color:#f1f5f9;">📋 سجل الدفعات</div>'
    + '<div style="font-size:12px;color:#64748b;margin-top:2px;">'+(d.ref_type==='purchase'?'فاتورة شراء':d.ref_type==='service'?'طلب خدمة':'فاتورة بيع')+' #'+d.ref_id+' — '+(d.party_name||'')+'</div></div>'
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

// معاينة صورة الشيك
window.previewChequeImg = function(input){
  const file = input.files[0];
  if(!file) return;
  if(file.size > 5*1024*1024){ alert('الصورة أكبر من 5MB'); input.value=''; return; }
  const reader = new FileReader();
  reader.onload = function(e){
    const tag  = document.getElementById('cheque-img-tag');
    const prev = document.getElementById('cheque-img-preview');
    if(tag)  tag.src = e.target.result;
    if(prev) prev.style.display = 'block';
    // إخفاء زر الرفع
    const wrap = document.querySelector('#cheque-img-wrap label');
    if(wrap) wrap.style.display = 'none';
  };
  reader.readAsDataURL(file);
};

window.removeChequeImg = function(){
  const inp  = document.getElementById('pay-cheque-img');
  const tag  = document.getElementById('cheque-img-tag');
  const prev = document.getElementById('cheque-img-preview');
  const wrap = document.querySelector('#cheque-img-wrap label');
  if(inp)  inp.value = '';
  if(tag)  tag.src = '';
  if(prev) prev.style.display = 'none';
  if(wrap) wrap.style.display = 'flex';
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
    <div><label class="lbl">الباركود *</label>
      <div style="display:flex;gap:6px;">
        <input class="inp" id="pfbarcode" type="text" value="${item.barcode??''}" style="flex:1;"/>
        <button type="button" class="btn s" style="white-space:nowrap;padding:8px 10px;" onclick="autoGenBarcode()" title="توليد باركود تلقائي">🎲 توليد</button>
      </div>
    </div>
    ${[['serial','السيريال','text'],['name','اسم المنتج *','text'],
       ['category','الفئة','text'],['unit','الوحدة','text'],['stock','المخزون','number'],
       ['buy_price','سعر الشراء','number'],['sell_price','سعر البيع','number']].map(([k,l,t])=>`
    <div><label class="lbl">${l}</label><input class="inp" id="pf${k}" type="${t}" value="${item[k]??''}"/></div>`).join('')}
    <div><label class="lbl">المورد</label>
      <select class="inp" id="pfsupp"><option value="">بدون مورد</option>${sups}</select>
    </div>
    <div><label class="lbl">تاريخ الصلاحية (اختياري)</label>
      <input class="inp" id="pfexpiry_date" type="date" value="${item.expiry_date??''}"/>
    </div>
  </div>
  <div onclick="document.getElementById('pftrackserial').click()"
    style="display:flex;align-items:center;gap:10px;background:#1a1d27;border:1px solid #2d3349;border-radius:8px;padding:12px 14px;margin-top:14px;cursor:pointer;">
    <input type="checkbox" id="pftrackserial" ${item.track_serial?'checked':''} style="width:17px;height:17px;accent-color:#2d6a4f;" onclick="event.stopPropagation()"/>
    <div>
      <div style="font-size:13px;font-weight:700;color:#f1f5f9;">📟 تتبع بسيريال فريد لكل قطعة</div>
      <div style="font-size:11px;color:#64748b;margin-top:2px;">فعّلها لمنتجات مثل الأجهزة الإلكترونية — كل قطعة سيكون لها سيريال مستقل يُدخَل عند الشراء ويُختار عند البيع</div>
    </div>
  </div>
  <div style="display:flex;gap:10px;margin-top:18px;">
    <button class="btn p" id="ms">${item.id?'حفظ التعديل':'اضافة'}</button>
    <button class="btn s" id="mc2">الغاء</button>
  </div></div></div>`;
}

window.autoGenBarcode = async function(){
  const btn = event?.target;
  try{
    const r = await api('GET','/api/products/next_barcode');
    const inp = document.getElementById('pfbarcode');
    if(inp) inp.value = r.barcode;
  }catch(e){ alert('تعذر توليد الباركود: '+e.message); }
};

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
        <div style="display:flex;gap:6px;">
          <select class="inp" id="pur-prod-select" style="flex:1;">
            <option value="">-- اختر منتج --</option>${prods}
          </select>
          <button type="button" class="btn s" style="white-space:nowrap;padding:8px 10px;" onclick="openQuickProduct('purform')" title="إنشاء منتج جديد الآن دون مغادرة الفاتورة">+ منتج جديد</button>
        </div>
      </div>
      <div>
        <label class="lbl">الكمية</label>
        <input class="inp" type="number" id="pur-qty" value="1" min="1"/>
      </div>
      <div>
        <label class="lbl">سعر الشراء</label>
        <input class="inp" type="number" id="pur-price" value="" placeholder="0"/>
        <div id="pur-price-hist" style="font-size:11px;color:#64748b;margin-top:3px;"></div>
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
  ${cart.map((i,idx)=>`<tr>
    <td style="font-weight:600;color:#f1f5f9;">${i.name}${(i.serials&&i.serials.length)?`<div style="font-size:10px;color:#52b788;font-family:monospace;margin-top:2px;">📟 ${i.serials.join(', ')}</div>`:''}</td>
    <td><input class="inp" type="number" style="width:70px;padding:4px 7px;" value="${i.qty}" min="1" ${(i.serials&&i.serials.length)?'disabled':''} onchange="updCart(${idx},'qty',this.value)"/></td>
    <td><input class="inp" type="number" style="width:90px;padding:4px 7px;" value="${i.price}" onchange="updCart(${idx},'price',this.value)"/></td>
    <td style="color:#52b788;font-weight:700;">${(i.qty*i.price).toLocaleString()} ${cur()}</td>
    <td><button class="btn d" style="padding:3px 7px;" onclick="remCart(${idx})">🗑️</button></td>
  </tr>`).join('')}
  </tbody></table>
  <div style="text-align:left;padding:10px 16px;font-size:17px;font-weight:800;color:#52b788;border-top:1px solid #1e2537;">
    المجموع: ${tot.toLocaleString()} ${cur()}
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
    <div style="font-size:24px;font-weight:900;color:#f1f5f9;">${(sale.total||0).toLocaleString()} ${cur()}</div>
    <div style="color:#64748b;font-size:13px;margin-top:3px;">${sale.pay_method} — ${sale.date}</div>
  </div>
  <div style="display:flex;gap:8px;">
    <button class="btn p" style="flex:1;justify-content:center;" onclick="printThermalReceipt(${sale.id})">🖨️ فاتورة حرارية</button>
    <button class="btn s" id="mc" style="flex:1;justify-content:center;">اغلاق</button>
  </div>
  </div></div>`;
}

// ── نافذة اختيار قطعة محددة (سيريال) لمنتج يُتتبَّع بشكل فريد ──
function unitPickerModal(d){
  const p = d.product || {};
  const units = d.units || [];
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:460px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">📟 اختر القطعة</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">${p.name} — متاح ${units.length} قطعة</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div style="max-height:340px;overflow-y:auto;display:flex;flex-direction:column;gap:6px;">
    ${units.map(u=>`
    <div onclick="pickUnit(${u.id})"
      style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;
             background:#1a1d27;border:1px solid #2d3349;border-radius:8px;cursor:pointer;"
      onmouseover="this.style.borderColor='#2d6a4f'" onmouseout="this.style.borderColor='#2d3349'">
      <span style="font-family:monospace;font-weight:700;color:#52b788;font-size:14px;">${u.serial}</span>
      <span style="color:#60a5fa;font-weight:700;">${(p.sell_price||0).toLocaleString()} ${cur()}</span>
    </div>`).join('')}
  </div>
  </div></div>`;
}

window.pickUnit = function(unitId){
  const d = MS?.data; if(!d) return;
  const u = (d.units||[]).find(x=>x.id===unitId);
  if(!u) return;
  posAddResolved(d.product, u);
  closeM();
  document.getElementById('pi')?.focus();
};

// ── نافذة المسح عبر كاميرا الجوال (BarcodeDetector API) ──
function cameraScanModal(){
  const supported = 'BarcodeDetector' in window;
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:420px;text-align:center;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
    <div style="font-size:16px;font-weight:800;color:#f1f5f9;">📷 مسح بالكاميرا</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  ${supported ? `
  <video id="cam-video" playsinline style="width:100%;border-radius:10px;background:#000;max-height:320px;"></video>
  <div id="cam-status" style="margin-top:10px;color:#64748b;font-size:13px;">📡 جارِ تشغيل الكاميرا...</div>
  ` : `
  <div style="padding:24px;color:#f87171;font-size:14px;">
    ⚠️ هذا المتصفح لا يدعم مسح الباركود بالكاميرا مباشرة.<br/>
    <span style="color:#64748b;font-size:12px;">جرّب متصفح Chrome على أندرويد، أو استخدم قارئ باركود USB / الإدخال اليدوي.</span>
  </div>`}
  </div></div>`;
}

let _camStream = null;
window.openCameraScan = function(){
  MS = {type:'camerascan'}; render();
};

// ── مودال إدخال السيريالات لصنف مسلسل بفاتورة شراء (جديدة أو قيد التعديل) ──
function serialsEntryModal(d){
  const p = d.product||{};
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">📟 إدخال السيريالات</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">${esc(p.name)} — مطلوب <span style="color:#52b788;font-weight:700;">${d.qty}</span> سيريال</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="se-cancel">✕</button>
  </div>
  <div id="merr"></div>
  <label class="lbl">أدخل سيريال واحد بكل سطر (Enter بعد كل سيريال)</label>
  <textarea id="se-textarea" class="inp" style="min-height:180px;font-family:monospace;font-size:13px;line-height:1.8;" placeholder="مثال:
SN00123
SN00124
SN00125" oninput="seUpdateCounter(${d.qty})"></textarea>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">
    <span id="se-counter" style="font-size:12px;color:#64748b;">0 / ${d.qty} تم إدخاله</span>
    <button class="btn s" style="padding:4px 10px;font-size:11px;" onclick="seAutoFill(${d.qty})">🎲 توليد تلقائي (بدون سيريال حقيقي)</button>
  </div>
  <div style="display:flex;gap:10px;margin-top:16px;">
    <button class="btn p" id="se-confirm" style="flex:1;justify-content:center;">✅ تأكيد وإضافة للفاتورة</button>
    <button class="btn s" id="se-cancel2">إلغاء</button>
  </div>
  </div></div>`;
}

window.seUpdateCounter = function(required){
  const ta = document.getElementById('se-textarea');
  const el = document.getElementById('se-counter');
  if(!ta || !el) return;
  const count = ta.value.split('\n').map(s=>s.trim()).filter(Boolean).length;
  el.textContent = `${count} / ${required} تم إدخاله`;
  el.style.color = count===required ? '#52b788' : (count>required ? '#f87171' : '#64748b');
};

// تعبئة سريعة بأرقام تسلسلية مؤقتة (تسهيلاً حين لا تتوفر سيريالات حقيقية بعد) — يمكن للمستخدم تعديلها يدوياً
window.seAutoFill = function(required){
  const ta = document.getElementById('se-textarea');
  if(!ta) return;
  const stamp = Date.now().toString().slice(-6);
  const lines = [];
  for(let i=1;i<=required;i++) lines.push(`SN-${stamp}-${String(i).padStart(3,'0')}`);
  ta.value = lines.join('\n');
  seUpdateCounter(required);
};

async function startCameraScan(){
  const video = document.getElementById('cam-video');
  const status = document.getElementById('cam-status');
  if(!video || !('BarcodeDetector' in window)) return;
  try{
    _camStream = await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});
    video.srcObject = _camStream;
    await video.play();
    const detector = new BarcodeDetector();
    const loop = async()=>{
      if(!MS || MS.type!=='camerascan') return; // أُغلقت النافذة
      try{
        const codes = await detector.detect(video);
        if(codes && codes.length){
          const val = codes[0].rawValue;
          stopCameraScan();
          closeM();
          const inp = document.getElementById('pi');
          if(inp){ inp.value = val; }
          await posAdd();
          return;
        }
      }catch(e){}
      requestAnimationFrame(loop);
    };
    if(status) status.textContent = '🎯 وجّه الكاميرا نحو الباركود...';
    loop();
  }catch(e){
    if(status) status.textContent = '❌ تعذّر الوصول للكاميرا: '+e.message;
  }
}

function stopCameraScan(){
  if(_camStream){ _camStream.getTracks().forEach(t=>t.stop()); _camStream=null; }
}

// ── طباعة فاتورة حرارية 80mm ──
window.printThermalReceipt = async function(saleId){
  let sale = sales.find(s=>s.id===saleId);
  if(!sale || !sale.items){
    try{ sale = await api('GET','/api/sales/'+saleId); }catch(e){ alert('تعذر جلب الفاتورة'); return; }
  }
  const custName = sale.customer_id ? (customers.find(c=>c.id===parseInt(sale.customer_id))?.name||'زبون عام') : 'زبون عام';
  const itemsHtml = groupInvoiceItems(sale.items||[]).map(it=>`
    <div style="font-size:12px;margin-bottom:3px;">
      <div style="display:flex;justify-content:space-between;">
        <span>${it.product_name||('#'+it.product_id)} × ${it.qty}</span>
        <span>${((it.qty||0)*(it.price||0)).toLocaleString()}</span>
      </div>
      ${it.serials&&it.serials.length?`<div style="font-size:10px;color:#333;">📟 ${it.serials.join(' ، ')}</div>`:''}
    </div>`).join('');
  const html = `<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">
  <style>
    @page{ size:80mm auto; margin:2mm; }
    *{font-family:'Tajawal','Arial',sans-serif;box-sizing:border-box;}
    body{width:76mm;padding:2mm;color:#000;}
    .c{text-align:center;}
    .b{font-weight:800;}
    hr{border:none;border-top:1px dashed #000;margin:6px 0;}
    .row{display:flex;justify-content:space-between;font-size:12px;margin-bottom:2px;}
    .tot{font-size:15px;font-weight:900;}
  </style></head>
  <body onload="window.print()">
    <div class="c b" style="font-size:15px;">${(sysSettings.system_name||'نظام إدارة المخازن')}</div>
    <div class="c" style="font-size:11px;">فاتورة بيع #${sale.id}</div>
    <div class="c" style="font-size:11px;">${sale.date}</div>
    <hr/>
    <div class="row"><span>الزبون</span><span>${custName}</span></div>
    <div class="row"><span>طريقة الدفع</span><span>${sale.pay_method||''}</span></div>
    <hr/>
    ${itemsHtml}
    <hr/>
    <div class="row tot"><span>الإجمالي</span><span>${(sale.total||0).toLocaleString()} ${cur()}</span></div>
    <hr/>
    <div class="c" style="font-size:11px;margin-top:6px;">شكراً لتعاملكم معنا 🙏</div>
  </body></html>`;
  const w = window.open('','_blank','width=340,height=600');
  w.document.write(html); w.document.close();
};

// ── modal تعديل فاتورة الشراء ──
function editPurModal(p){
  const sups = suppliers.map(s=>'<option value="'+s.id+'"'+(parseInt(p.supplier_id)===s.id?' selected':'')+'>'+s.name+'</option>').join('');
  const prods = products.map(x=>'<option value="'+x.id+'" data-price="'+x.buy_price+'" data-name="'+x.name+'">'+x.name+' — '+x.barcode+'</option>').join('');
  const tot = cart.reduce((s,i)=>s+i.qty*i.price,0);
  const cartRows = cart.map((item,idx)=>`
    <tr>
      <td style="font-weight:600;color:#f1f5f9;">${item.name}${(item.serials&&item.serials.length)?`<div style="font-size:10px;color:#52b788;font-family:monospace;margin-top:2px;">📟 ${item.serials.join(', ')}</div>`:''}</td>
      <td><input class="inp" type="number" style="width:70px;padding:4px 7px;" value="${item.qty}" min="1" ${(item.serials&&item.serials.length)?'disabled':''} onchange="updCart(${idx},'qty',this.value)"/></td>
      <td><input class="inp" type="number" style="width:85px;padding:4px 7px;" value="${item.price}" onchange="updCart(${idx},'price',this.value)"/></td>
      <td style="color:#52b788;font-weight:700;">${(item.qty*item.price).toLocaleString()} ${cur()}</td>
      <td><button class="btn d" style="padding:3px 7px;" onclick="remCart(${idx})">🗑️</button></td>
    </tr>`).join('') || `<tr><td colspan="5" style="text-align:center;color:#64748b;padding:14px;">لا توجد أصناف — أضف صنفاً من الأعلى</td></tr>`;
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
      <button type="button" class="btn s" style="white-space:nowrap;padding:8px 10px;" onclick="openQuickProduct('editpur')" title="إنشاء منتج جديد الآن">+ جديد</button>
    </div>
    <div id="edit-price-hist" style="font-size:11px;color:#64748b;margin-top:6px;"></div>
  </div>
  <div class="card" style="margin-bottom:14px;">
    <table id="edit-items-table">
      <thead><tr><th>المنتج</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th></th></tr></thead>
      <tbody id="edit-items-body">${cartRows}</tbody>
    </table>
    <div style="text-align:left;padding:10px 16px;font-size:16px;font-weight:800;color:#52b788;border-top:1px solid #1e2537;">
      المجموع: ${tot.toLocaleString()} ${cur()}
    </div>
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
    <div style="font-size:13px;color:#94a3b8;">المورد: ${suppliers.find(s=>parseInt(s.id)===parseInt(p.supplier_id))?.name||'—'} | التاريخ: ${p.date} | الإجمالي: ${(p.total||0).toLocaleString()} ${cur()}</div>
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
          <td style="color:#52b788;">${(item.price||0).toLocaleString()} ${cur()}</td>
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

// ══════════════════════════════════════════════
//  مودالات نظام المصاريف
// ══════════════════════════════════════════════

// ── مودال إضافة/تعديل مصروف عام ──
function expenseFormModal(item){
  const isEdit = !!item.id;
  const today = new Date().toISOString().slice(0,10);
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:520px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">${isEdit?'✏️ تعديل مصروف':'➕ إضافة مصروف'}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2" style="margin-bottom:12px;">
    <div><label class="lbl">التصنيف <span style="color:#f87171;">*</span></label>
      <select class="inp" id="ef-cat">
        ${expenseCategories.map(c=>`<option value="${c.id}"${item.category_id===c.id?' selected':''}>${c.icon} ${esc(c.name)}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">المبلغ <span style="color:#f87171;">*</span></label>
      <input class="inp" type="number" id="ef-amount" min="0.01" step="0.01" value="${item.amount??''}"/>
    </div>
    <div style="grid-column:span 2;"><label class="lbl">الوصف <span style="color:#f87171;">*</span></label>
      <input class="inp" id="ef-desc" placeholder="مثال: صيانة سيارة التوصيل..." value="${esc(item.description)||''}"/>
    </div>
    <div><label class="lbl">التاريخ</label>
      <input class="inp" type="date" id="ef-date" value="${item.date||today}"/>
    </div>
    <div><label class="lbl">طريقة الدفع</label>
      <select class="inp" id="ef-method" onchange="efToggleCheque(this.value)">
        ${['نقدي','شيك','تحويل بنكي','بطاقة'].map(m=>`<option${item.payment_method===m?' selected':''}>${m}</option>`).join('')}
      </select>
    </div>
    <div style="grid-column:span 2;"><label class="lbl">ملاحظات</label>
      <input class="inp" id="ef-notes" value="${esc(item.notes)||''}"/>
    </div>
  </div>
  <div id="ef-cheque-fields" style="display:${item.payment_method==='شيك'?'block':'none'};background:#1a1d27;border-radius:8px;padding:12px;margin-bottom:14px;">
    <div style="font-size:12px;font-weight:700;color:#60a5fa;margin-bottom:8px;">🏦 بيانات الشيك</div>
    <div class="g2">
      <div><label class="lbl">رقم الشيك</label><input class="inp" id="ef-cheque-no" value="${item.cheque_no||''}"/></div>
      <div><label class="lbl">تاريخ الشيك</label><input class="inp" type="date" id="ef-cheque-date" value="${item.cheque_date||today}"/></div>
      <div style="grid-column:span 2"><label class="lbl">اسم البنك</label><input class="inp" id="ef-cheque-bank" value="${item.cheque_bank||''}"/></div>
    </div>
  </div>
  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 ${isEdit?'حفظ التعديل':'إضافة المصروف'}</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}
window.efToggleCheque = function(val){
  const el = document.getElementById('ef-cheque-fields');
  if(el) el.style.display = val==='شيك' ? 'block' : 'none';
};

// ── مودال إضافة/تعديل موظف ──
function employeeFormModal(item){
  const isEdit = !!item.id;
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">${isEdit?'✏️ تعديل موظف':'➕ إضافة موظف'}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2">
    <div style="grid-column:span 2;"><label class="lbl">الاسم <span style="color:#f87171;">*</span></label>
      <input class="inp" id="emf-name" value="${esc(item.name)||''}"/>
    </div>
    <div><label class="lbl">الوظيفة</label><input class="inp" id="emf-position" value="${esc(item.position)||''}"/></div>
    <div><label class="lbl">الهاتف</label><input class="inp" id="emf-phone" value="${esc(item.phone)||''}"/></div>
    <div><label class="lbl">الراتب الأساسي <span style="color:#f87171;">*</span></label>
      <input class="inp" type="number" id="emf-salary" min="0" step="1" value="${item.base_salary??''}"/>
    </div>
    <div><label class="lbl">تاريخ التوظيف</label><input class="inp" type="date" id="emf-hiredate" value="${item.hire_date||''}"/></div>
    <div style="grid-column:span 2;"><label class="lbl">الحالة</label>
      <select class="inp" id="emf-active">
        <option value="1"${(item.is_active===undefined||item.is_active)?' selected':''}>✅ نشط</option>
        <option value="0"${item.is_active===0?' selected':''}>🚫 موقوف</option>
      </select>
    </div>
    <div style="grid-column:span 2;"><label class="lbl">ملاحظات</label>
      <textarea class="inp" id="emf-notes" style="min-height:56px;">${esc(item.notes)||''}</textarea>
    </div>
  </div>
  <div style="display:flex;gap:10px;margin-top:16px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 ${isEdit?'حفظ التعديل':'إضافة الموظف'}</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

// ── مودال إضافة/تعديل مصروف متكرر ──
function recurringFormModal(item){
  const isEdit = !!item.id;
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">${isEdit?'✏️ تعديل مصروف متكرر':'🔁 مصروف متكرر جديد'}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2">
    <div style="grid-column:span 2;"><label class="lbl">الوصف <span style="color:#f87171;">*</span></label>
      <input class="inp" id="rcf-desc" placeholder="مثال: إيجار المحل..." value="${esc(item.description)||''}"/>
    </div>
    <div><label class="lbl">التصنيف</label>
      <select class="inp" id="rcf-cat">
        ${expenseCategories.map(c=>`<option value="${c.id}"${item.category_id===c.id?' selected':''}>${c.icon} ${esc(c.name)}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">المبلغ <span style="color:#f87171;">*</span></label>
      <input class="inp" type="number" id="rcf-amount" min="0.01" step="0.01" value="${item.amount??''}"/>
    </div>
    <div><label class="lbl">يوم الاستحقاق بالشهر (1-28)</label>
      <input class="inp" type="number" id="rcf-day" min="1" max="28" value="${item.day_of_month||1}"/>
    </div>
    <div><label class="lbl">الحالة</label>
      <select class="inp" id="rcf-active">
        <option value="1"${(item.is_active===undefined||item.is_active)?' selected':''}>✅ نشط</option>
        <option value="0"${item.is_active===0?' selected':''}>🚫 موقوف</option>
      </select>
    </div>
    <div style="grid-column:span 2;"><label class="lbl">ملاحظات</label>
      <input class="inp" id="rcf-notes" value="${esc(item.notes)||''}"/>
    </div>
  </div>
  <div style="background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.2);border-radius:8px;padding:10px;margin-top:12px;font-size:12px;color:#94a3b8;">
    ℹ️ لما يوصل يوم الاستحقاق، رح يظهر تنبيه بلوحة التحكم لحد ما تسجّل دفعة هذا المصروف لهذا الشهر.
  </div>
  <div style="display:flex;gap:10px;margin-top:16px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 ${isEdit?'حفظ التعديل':'إضافة'}</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

// ── مودال تسجيل دفعة مصروف متكرر لهذا الشهر ──
function payRecurringModal(rec){
  const today = new Date().toISOString().slice(0,10);
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:480px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div>
      <div style="font-size:16px;font-weight:700;color:#f1f5f9;">💳 تسجيل دفعة: ${esc(rec.description)}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">المبلغ المعتاد: ${(rec.amount||0).toLocaleString()} ${cur()}</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2" style="margin-bottom:12px;">
    <div><label class="lbl">المبلغ الفعلي</label>
      <input class="inp" type="number" id="pr-amount" min="0.01" step="0.01" value="${rec.amount}"/>
    </div>
    <div><label class="lbl">تاريخ الدفع</label>
      <input class="inp" type="date" id="pr-date" value="${today}"/>
    </div>
    <div><label class="lbl">طريقة الدفع</label>
      <select class="inp" id="pr-method">
        ${['نقدي','شيك','تحويل بنكي','بطاقة'].map(m=>`<option>${m}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">ملاحظات</label><input class="inp" id="pr-notes"/></div>
  </div>
  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 تسجيل الدفعة</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

// ── مودال دفع راتب موظف لشهر معيّن ──
function payrollFormModal(d){
  const emp = d.employee;
  const advancesTotal = d.advancesTotal || 0;
  const today = new Date().toISOString().slice(0,10);
  const month = currentMonth();
  const estimatedNet = Math.max(0, (emp.base_salary||0) - advancesTotal);
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:520px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div>
      <div style="font-size:16px;font-weight:700;color:#f1f5f9;">💳 دفع راتب: ${esc(emp.name)}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">شهر ${month}</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px;">
    <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">الراتب الأساسي</div><div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-top:4px;">${(emp.base_salary||0).toLocaleString()} ${cur()}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">سلف غير مخصومة</div><div style="font-size:15px;font-weight:800;color:#f87171;margin-top:4px;">${advancesTotal.toLocaleString()} ${cur()}</div></div>
    <div class="stat" style="text-align:center;"><div style="font-size:11px;color:#64748b;">الصافي المتوقع</div><div style="font-size:15px;font-weight:800;color:#52b788;margin-top:4px;" id="pf-net-preview">${estimatedNet.toLocaleString()} ${cur()}</div></div>
  </div>
  <div id="merr"></div>
  <div class="g2" style="margin-bottom:12px;">
    <div><label class="lbl">تعديل (مكافأة +/خصم -)</label>
      <input class="inp" type="number" id="pf-adjustment" step="0.01" value="0" oninput="pfUpdatePreview(${emp.base_salary||0},${advancesTotal})"/>
    </div>
    <div><label class="lbl">تاريخ الدفع</label>
      <input class="inp" type="date" id="pf-date" value="${today}"/>
    </div>
    <div><label class="lbl">طريقة الدفع</label>
      <select class="inp" id="pf-method">
        ${['نقدي','شيك','تحويل بنكي','بطاقة'].map(m=>`<option>${m}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">سبب التعديل (اختياري)</label><input class="inp" id="pf-adj-notes"/></div>
    <div style="grid-column:span 2;"><label class="lbl">ملاحظات</label><input class="inp" id="pf-notes"/></div>
  </div>
  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;height:44px;font-size:15px;">💾 تأكيد دفع الراتب</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}
window.pfUpdatePreview = function(baseSalary, advancesTotal){
  const adj = parseFloat(document.getElementById('pf-adjustment')?.value||0)||0;
  const net = Math.max(0, baseSalary + adj - advancesTotal);
  const el = document.getElementById('pf-net-preview');
  if(el) el.textContent = net.toLocaleString()+' '+cur();
};

// فتح مودال إدخال السيريالات (يُستدعى من فاتورة شراء جديدة أو من تعديل فاتورة شراء)
window.openSerialsEntry = function(pending){
  MS = {type:'serialsentry', data: pending};
  render();
};

// ── مودال نموذج طلب خدمة (تركيب/صيانة) ──
let _svcParts = [];

function serviceFormModal(item){
  const isEdit = !!item.id;
  const today = new Date().toISOString().slice(0,10);
  if(!isEdit || !MS._svcPartsInit){
    _svcParts = (item.parts||[]).map(p=>({product_id:p.product_id, name:p.product_name, qty:p.qty, price:p.price}));
    MS._svcPartsInit = true;
  }
  const partsTotal = _svcParts.reduce((s,p)=>s+p.qty*p.price,0);
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:680px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div style="font-size:16px;font-weight:700;color:#f1f5f9;">${isEdit?'✏️ تعديل طلب خدمة #'+item.id:'🔧 طلب خدمة جديد'}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div class="g2" style="margin-bottom:12px;">
    <div><label class="lbl">الزبون <span style="color:#f87171;">*</span></label>
      <select class="inp" id="svf-customer">
        <option value="">-- اختر الزبون --</option>
        ${customers.map(c=>`<option value="${c.id}"${item.customer_id===c.id?' selected':''}>${esc(c.name)}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">نوع الخدمة</label>
      <select class="inp" id="svf-type">
        ${['تركيب','صيانة','إصلاح','كشف فني'].map(t=>`<option${item.service_type===t?' selected':''}>${t}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">وصف الجهاز</label>
      <input class="inp" id="svf-device" placeholder="مثال: نظام كاميرات مراقبة (4 كاميرات)" value="${esc(item.device_desc)||''}"/>
    </div>
    <div><label class="lbl">ربط بمنتج من المخزون (اختياري)</label>
      <select class="inp" id="svf-product">
        <option value="">-- بدون ربط --</option>
        ${products.map(p=>`<option value="${p.id}"${item.product_id===p.id?' selected':''}>${esc(p.name)}</option>`).join('')}
      </select>
    </div>
    <div style="grid-column:span 2;"><label class="lbl">وصف العطل / المطلوب تنفيذه</label>
      <textarea class="inp" id="svf-issue" style="min-height:56px;">${esc(item.issue_desc)||''}</textarea>
    </div>
    <div><label class="lbl">الفني المسؤول</label>
      <select class="inp" id="svf-tech">
        <option value="">-- غير محدد --</option>
        ${employees.filter(e=>e.is_active).map(e=>`<option value="${e.id}"${item.technician_id===e.id?' selected':''}>${esc(e.name)}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">الحالة</label>
      <select class="inp" id="svf-status">
        ${SERVICE_STATUSES.map(s=>`<option${item.status===s?' selected':''}>${s}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">تاريخ الاستلام</label>
      <input class="inp" type="date" id="svf-received" value="${item.received_date||today}"/>
    </div>
    <div><label class="lbl">تاريخ التسليم المتوقع</label>
      <input class="inp" type="date" id="svf-expected" value="${item.expected_date||''}"/>
    </div>
    <div><label class="lbl">أجرة الخدمة</label>
      <input class="inp" type="number" id="svf-fee" min="0" step="1" value="${item.service_fee??''}"/>
    </div>
    <div><label class="lbl">مدة الضمان (أيام)</label>
      <input class="inp" type="number" id="svf-warranty" min="0" step="1" value="${item.warranty_days??0}"/>
    </div>
    <div style="grid-column:span 2;"><label class="lbl">ملاحظات</label>
      <input class="inp" id="svf-notes" value="${esc(item.notes)||''}"/>
    </div>
  </div>

  <div style="background:#1a1d27;border:1px solid #2d3349;border-radius:8px;padding:12px;margin-bottom:12px;">
    <div style="font-size:13px;font-weight:700;color:#f87171;margin-bottom:10px;">🔧 قطع الغيار المستخدمة (تُنقَص من المخزون تلقائياً)</div>
    <div style="display:flex;gap:8px;">
      <select class="inp" id="svf-part-prod" style="flex:2;">
        <option value="">-- اختر قطعة --</option>
        ${products.map(p=>`<option value="${p.id}" data-price="${p.buy_price}">${esc(p.name)} (متوفر: ${p.stock})</option>`).join('')}
      </select>
      <input class="inp" type="number" id="svf-part-qty" placeholder="الكمية" value="1" min="1" style="width:80px;"/>
      <input class="inp" type="number" id="svf-part-price" placeholder="السعر" style="width:90px;"/>
      <button class="btn p" id="svf-part-add">+ إضافة</button>
    </div>
  </div>
  <div class="card" style="margin-bottom:14px;">
    <table>
      <thead><tr><th>القطعة</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th></th></tr></thead>
      <tbody id="svf-parts-body">
      ${_svcParts.map((p,idx)=>`<tr>
        <td style="font-weight:600;color:#f1f5f9;">${esc(p.name)}</td>
        <td>${p.qty}</td>
        <td>${p.price.toLocaleString()} ${cur()}</td>
        <td style="color:#f87171;font-weight:700;">${(p.qty*p.price).toLocaleString()} ${cur()}</td>
        <td><button class="btn d" style="padding:3px 7px;" onclick="removeSvcPart(${idx})">🗑️</button></td>
      </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:#64748b;padding:10px;">لا توجد قطع مضافة</td></tr>'}
      </tbody>
    </table>
    <div style="text-align:left;padding:8px 14px;font-size:13px;font-weight:800;color:#f87171;border-top:1px solid #1e2537;">
      إجمالي تكلفة القطع: ${partsTotal.toLocaleString()} ${cur()}
    </div>
  </div>

  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 ${isEdit?'حفظ التعديلات':'إنشاء طلب الخدمة'}</button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

window.removeSvcPart = function(idx){
  _svcParts.splice(idx,1);
  render();
};

function closeM(){
  stopCameraScan();
  if(MS?._fromPurchase && _purDraftStash){
    MS = _purDraftStash; _purDraftStash = null;
    render();
    return;
  }
  MS=null; render();
}

function bindModal(){
  document.getElementById('mover')?.addEventListener('click',e=>{if(e.target.id==='mover')closeM();});
  document.getElementById('mc')?.addEventListener('click',closeM);
  document.getElementById('mc2')?.addEventListener('click',closeM);

  if(MS?.type==='camerascan'){
    startCameraScan();
  }

  if(MS?.type==='serialsentry'){
    const d = MS.data||{};
    const backToContext = ()=>{
      if(d.context==='editpur') MS = {type:'editpur', editId:d.editId, data:d.editData};
      else MS = {type:'purform'};
      render();
    };
    document.getElementById('se-cancel')?.addEventListener('click', backToContext);
    document.getElementById('se-cancel2')?.addEventListener('click', backToContext);
    document.getElementById('se-textarea')?.focus();
    document.getElementById('se-confirm')?.addEventListener('click', ()=>{
      const errEl = document.getElementById('merr');
      const ta = document.getElementById('se-textarea');
      const raw = ta?.value || '';
      const serials = raw.split('\n').map(s=>s.trim()).filter(Boolean);
      if(serials.length !== d.qty){
        if(errEl) errEl.innerHTML = `<div class="err">أدخلت ${serials.length} سيريال بينما الكمية المطلوبة ${d.qty} — يجب أن يتطابق العدد</div>`;
        return;
      }
      const uniqueInInput = new Set(serials);
      if(uniqueInInput.size !== serials.length){
        if(errEl) errEl.innerHTML = `<div class="err">يوجد سيريال مكرر بنفس القائمة المُدخَلة</div>`;
        return;
      }
      const dupInCart = cart.some(ci=>(ci.serials||[]).some(s=>serials.includes(s)));
      if(dupInCart){
        if(errEl) errEl.innerHTML = `<div class="err">أحد السيريالات مضاف مسبقاً بنفس الفاتورة</div>`;
        return;
      }
      // كل قطعة مسلسلة = سطر مستقل بالسلة (لا تُدمج مع أصناف أخرى لنفس المنتج)
      cart.push({product_id:d.product.id, name:d.product.name, qty:d.qty, price:d.price, serials});
      backToContext();
    });
  }

  // ── نموذج طلب خدمة (تركيب/صيانة) ──
  if(MS?.type==='serviceform'){
    document.getElementById('svf-part-add')?.addEventListener('click', ()=>{
      const sel = document.getElementById('svf-part-prod');
      const pid = parseInt(sel?.value||0);
      if(!pid){ alert('اختر قطعة من القائمة'); return; }
      const p = products.find(x=>x.id===pid);
      if(!p) return;
      const qty = parseInt(document.getElementById('svf-part-qty')?.value)||1;
      const price = parseFloat(document.getElementById('svf-part-price')?.value)||p.buy_price;
      const ex = _svcParts.find(sp=>sp.product_id===pid);
      if(ex){ ex.qty+=qty; ex.price=price; }
      else _svcParts.push({product_id:pid, name:p.name, qty, price});
      render();
    });
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const customer_id = document.getElementById('svf-customer')?.value;
      const received_date = document.getElementById('svf-received')?.value;
      if(!customer_id){ errEl.innerHTML='<div class="err">يرجى اختيار الزبون</div>'; return; }
      if(!received_date){ errEl.innerHTML='<div class="err">يرجى تحديد تاريخ الاستلام</div>'; return; }
      const body = {
        customer_id: parseInt(customer_id),
        service_type: document.getElementById('svf-type')?.value||'تركيب',
        device_desc: document.getElementById('svf-device')?.value||'',
        product_id: document.getElementById('svf-product')?.value ? parseInt(document.getElementById('svf-product').value) : null,
        issue_desc: document.getElementById('svf-issue')?.value||'',
        technician_id: document.getElementById('svf-tech')?.value ? parseInt(document.getElementById('svf-tech').value) : null,
        status: document.getElementById('svf-status')?.value||'قيد الانتظار',
        received_date, expected_date: document.getElementById('svf-expected')?.value||'',
        service_fee: parseFloat(document.getElementById('svf-fee')?.value)||0,
        warranty_days: parseInt(document.getElementById('svf-warranty')?.value)||0,
        notes: document.getElementById('svf-notes')?.value||'',
        parts: _svcParts.map(p=>({product_id:p.product_id, qty:p.qty, price:p.price})),
      };
      try{
        if(MS.data?.id) await api('PUT','/api/service_orders/'+MS.data.id, body);
        else await api('POST','/api/service_orders', body);
        _svcParts = [];
        await loadAll();
        page='services'; closeM();
      }catch(e){ errEl.innerHTML='<div class="err">'+e.message+'</div>'; }
    };
  }

  if(MS?.type==='pform'){
    document.getElementById('ms').onclick=async()=>{
      const g=k=>document.getElementById('pf'+k)?.value||'';
      const item=MS.data||{};
      const d={barcode:g('barcode'),serial:g('serial'),name:g('name'),category:g('category'),
               unit:g('unit')||'قطعة',stock:+g('stock')||0,buy_price:+g('buy_price')||0,
               sell_price:+g('sell_price')||0,
               supplier_id:document.getElementById('pfsupp')?.value||null,
               track_serial: document.getElementById('pftrackserial')?.checked ? 1 : 0,
               expiry_date: g('expiry_date')};
      if(!d.name||!d.barcode){document.getElementById('merr').innerHTML='<div class="err">الاسم والباركود مطلوبان</div>';return;}
      try{
        let saved;
        if(item.id) saved = await api('PUT',`/api/products/${item.id}`,d);
        else saved = await api('POST','/api/products',d);
        await loadAll();
        if(MS._fromPurchase){
          // نعود لفاتورة الشراء التي فتحنا منها هذا النموذج، مع تحديد المنتج الجديد تلقائياً
          const stash = _purDraftStash;
          _pendingSelectProductId = saved.id;
          _purDraftStash = null;
          MS = stash;
          render();
        } else {
          closeM();
        }
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

    document.getElementById('pus')?.addEventListener('change', function(){
      if(purSel?.value) showPriceHistory(purSel.value, this.value, 'pur-price-hist');
    });

    // استعادة حقول المورد/التاريخ/الحالة إن كنا عائدين من إنشاء منتج سريع
    if(_pendingPurDraftFields){
      if(_pendingPurDraftFields.sup)    document.getElementById('pus').value = _pendingPurDraftFields.sup;
      if(_pendingPurDraftFields.date)   document.getElementById('pud').value = _pendingPurDraftFields.date;
      if(_pendingPurDraftFields.status) document.getElementById('pust').value = _pendingPurDraftFields.status;
      _pendingPurDraftFields = null;
    }

    // تطبيق اختيار المنتج المُنشأ للتو من داخل الفاتورة (إن وُجد)
    if(_pendingSelectProductId && purSel){
      const np = products.find(x=>x.id===_pendingSelectProductId);
      if(np){
        purSel.value = np.id;
        document.getElementById('pur-price').value = np.buy_price;
        showPriceHistory(np.id, document.getElementById('pus')?.value, 'pur-price-hist');
      }
      _pendingSelectProductId = null;
    }

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
            showPriceHistory(p.id, document.getElementById('pus')?.value, 'pur-price-hist');
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
        showPriceHistory(p.id, document.getElementById('pus')?.value, 'pur-price-hist');
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

      if(p.track_serial){
        openSerialsEntry({product:p, qty, price, context:'purform'});
        return;
      }

      const ex=cart.find(i=>i.product_id===p.id && !(i.serials&&i.serials.length));
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

      MS={type:'purform'}; render();
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
          items: cart.map(i=>({product_id:i.product_id,qty:i.qty,price:i.price,serials:i.serials||[]}))
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
      const sup    = document.getElementById('edit-pus').value;
      const date   = document.getElementById('edit-pud').value;
      const status = document.getElementById('edit-pust').value;
      const notes  = document.getElementById('edit-notes')?.value||'';
      const eid    = MS.editId;
      if(!sup){
        document.getElementById('edit-pus').style.border='2px solid #f87171';
        document.getElementById('edit-pus').focus();
        alert('⚠️ يرجى تحديد المورد أولاً');
        return;
      }
      if(!cart.length){
        alert('⚠️ يرجى إضافة منتج واحد على الأقل');
        return;
      }
      document.getElementById('edit-pus').style.border='';
      try{
        await api('PUT','/api/purchases/'+eid,{
          supplier_id: parseInt(sup), date, status, notes,
          items: cart.map(i=>({product_id:i.product_id,qty:i.qty,price:i.price,serials:i.serials||[]}))
        });
        cart=[]; await loadAll(); closeM();
      }catch(e){alert('خطأ: '+e.message);}
    };

    document.getElementById('edit-pus')?.addEventListener('change', function(){
      const selEl=document.getElementById('edit-prod-sel');
      if(selEl?.value) showPriceHistory(selEl.value, this.value, 'edit-price-hist');
    });

    // تطبيق اختيار المنتج المُنشأ للتو من داخل هذه الفاتورة (إن وُجد)
    if(_pendingSelectProductId){
      const selEl=document.getElementById('edit-prod-sel');
      const np = products.find(x=>x.id===_pendingSelectProductId);
      if(np && selEl){
        selEl.value = np.id;
        document.getElementById('edit-add-price').value = np.buy_price;
        showPriceHistory(np.id, document.getElementById('edit-pus')?.value, 'edit-price-hist');
      }
      _pendingSelectProductId = null;
    }

    document.getElementById('edit-prod-sel')?.addEventListener('change', function(){
      const p = products.find(x=>x.id===parseInt(this.value));
      if(!p) return;
      document.getElementById('edit-add-price').value = p.buy_price;
      showPriceHistory(p.id, document.getElementById('edit-pus')?.value, 'edit-price-hist');
    });

    // نفس منطق إضافة الأصناف كـ purform
    const addItemE=()=>{
      const selEl=document.getElementById('edit-prod-sel');
      let p=null;
      if(selEl&&selEl.value) p=products.find(x=>x.id===parseInt(selEl.value));
      if(!p){alert('اختر منتجاً من القائمة');return;}
      const qty=parseInt(document.getElementById('edit-add-qty')?.value)||1;
      const price=parseFloat(document.getElementById('edit-add-price')?.value)||p.buy_price;

      if(p.track_serial){
        openSerialsEntry({product:p, qty, price, context:'editpur', editId:MS.editId, editData:MS.data});
        return;
      }

      const ex=cart.find(i=>i.product_id===p.id && !(i.serials&&i.serials.length));
      if(ex){ex.qty+=qty;ex.price=price;}
      else cart.push({product_id:p.id,name:p.name,qty,price});

      if(selEl) selEl.value='';
      document.getElementById('edit-add-qty').value='1';
      document.getElementById('edit-add-price').value='';
      MS={type:'editpur',editId:MS.editId,data:MS.data};
      render();
    };
    document.getElementById('edit-add-btn')?.addEventListener('click',addItemE);
  }

  // ── دفعة على الحساب الكلي ──
  if(MS?.type==='accountpay'){
    document.getElementById('ms').onclick = async()=>{
      const errEl  = document.getElementById('merr');
      const amount = parseFloat(document.getElementById('ap-amount')?.value||0);
      const method = document.getElementById('ap-method')?.value||'نقدي';
      const date   = document.getElementById('ap-date')?.value||'';
      const notes  = document.getElementById('ap-notes')?.value||'';
      const cheqNo = document.getElementById('ap-cheque-no')?.value||'';
      const cheqDt = document.getElementById('ap-cheque-date')?.value||'';
      const cheqBk = document.getElementById('ap-cheque-bank')?.value||'';

      if(!amount||amount<=0){ errEl.innerHTML='<div class="err">أدخل مبلغاً أكبر من صفر</div>'; return; }
      if(!date){ errEl.innerHTML='<div class="err">حدد تاريخ الدفعة</div>'; return; }
      if(method==='شيك'&&!cheqNo){ errEl.innerHTML='<div class="err">أدخل رقم الشيك</div>'; return; }

      const btn = document.getElementById('ms');
      btn.disabled=true; btn.textContent='⏳ جاري التسجيل...';
      try{
        const res = await api('POST','/api/pay_account',{
          party_type: MS.data.party_type,
          party_id:   parseInt(MS.data.party_id),
          amount, method, date, notes,
          cheque_no:    cheqNo,
          cheque_date:  cheqDt,
          cheque_bank:  cheqBk,
          cheque_image: method==='شيك' ? (document.getElementById('ap-img-tag')?.src||'') : ''
        });
        await loadAll();
        closeM();
        alert(`✅ تم تسجيل دفعة بقيمة ${res.total_paid.toLocaleString()} ${cur()} على حساب ${MS.data.name}`);
      }catch(e){
        errEl.innerHTML='<div class="err">'+e.message+'</div>';
        btn.disabled=false; btn.textContent='💾 تسجيل الدفعة';
      }
    };
  }

  // ── تعديل دفعة موجودة ──
  if(MS?.type==='editpayment'){
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const amount = parseFloat(document.getElementById('ep-amount')?.value||0);
      const method = document.getElementById('ep-method')?.value||'نقدي';
      const date   = document.getElementById('ep-date')?.value||'';
      const notes  = document.getElementById('ep-notes')?.value||'';
      const cheqNo = document.getElementById('ep-cheque-no')?.value||'';
      const cheqDt = document.getElementById('ep-cheque-date')?.value||'';
      const cheqBk = document.getElementById('ep-cheque-bank')?.value||'';

      if(!amount||amount<=0){ errEl.innerHTML='<div class="err">أدخل مبلغاً أكبر من صفر</div>'; return; }
      if(!date){ errEl.innerHTML='<div class="err">حدد التاريخ</div>'; return; }
      if(method==='شيك'&&!cheqNo){ errEl.innerHTML='<div class="err">أدخل رقم الشيك</div>'; return; }

      // تحديد الصورة: جديدة، محذوفة، أو بدون تغيير
      let imageVal = undefined;
      const imgTag = document.getElementById('ep-img-tag');
      const imgSrc = imgTag?.src || '';
      if(window._epDeleteImage){
        imageVal = '';
      } else if(imgSrc && imgSrc.startsWith('data:image') && imgSrc !== MS.data?.cheque_image){
        imageVal = imgSrc;
      }

      const btn = document.getElementById('ms');
      btn.disabled=true; btn.textContent='⏳ جاري الحفظ...';
      try{
        const body = { amount, method, date, notes,
          cheque_no: cheqNo, cheque_date: cheqDt, cheque_bank: cheqBk };
        if(imageVal !== undefined) body.cheque_image = imageVal;
        await api('PUT','/api/payments/'+MS.data.id, body);
        window._epDeleteImage = false;
        await loadAll();
        closeM();
      }catch(e){
        errEl.innerHTML='<div class="err">'+e.message+'</div>';
        btn.disabled=false; btn.textContent='💾 حفظ التعديل';
      }
    };
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
          cheque_no:    cheqNo,
          cheque_date:  cheqDt,
          cheque_bank:  cheqBnk,
          cheque_image: method==='شيك' ? (document.getElementById('cheque-img-tag')?.src||'') : ''
        });
        await loadAll();
        closeM();
        alert('✅ تم حفظ الدفعة بنجاح');
      }catch(e){
        if(errEl) errEl.innerHTML='<div class="err">خطأ: '+e.message+'</div>';
      }
    };
  }

  // ── تعديل فاتورة بيع ──
  if(MS?.type==='editsale'){
    // ربط تغيير المنتج لجلب السعر
    document.getElementById('es-prod')?.addEventListener('change',function(){
      const opt = this.options[this.selectedIndex];
      const price = opt?.dataset?.price||'';
      document.getElementById('es-price').value = price;
    });
    // ربط زر إضافة صنف
    document.getElementById('es-add-btn')?.addEventListener('click',()=>{
      const sel   = document.getElementById('es-prod');
      const pid   = parseInt(sel?.value||0);
      const qty   = parseInt(document.getElementById('es-qty')?.value||1);
      const price = parseFloat(document.getElementById('es-price')?.value||0);
      if(!pid){ alert('اختر منتجاً'); return; }
      const prod  = products.find(x=>x.id===pid);
      if(!prod) return;
      // إزالة الصنف القديم إن وجد ثم إعادة إضافته
      document.getElementById('esi-row-'+pid)?.remove();
      const tbody = document.getElementById('es-items-body');
      if(!tbody) return;
      const tr = document.createElement('tr');
      tr.id = 'esi-row-'+pid;
      tr.innerHTML = `
        <td style="font-weight:600;color:#f1f5f9;font-size:13px;">${prod.name}</td>
        <td><input class="inp" type="number" min="1" value="${qty}" id="esq-${pid}" style="width:65px;padding:4px 7px;"/></td>
        <td><input class="inp" type="number" min="0" step="0.01" value="${price||prod.sell_price}" id="esp-${pid}" style="width:85px;padding:4px 7px;"/></td>
        <td style="color:#52b788;font-weight:700;">${(qty*(price||prod.sell_price)).toLocaleString()} ${cur()}</td>
        <td><button class="btn d" style="padding:3px 7px;" onclick="removeEsItem(${pid})">🗑️</button></td>`;
      tbody.appendChild(tr);
      sel.value='';
      document.getElementById('es-qty').value='1';
      document.getElementById('es-price').value='';
    });
    // حفظ التعديلات
    document.getElementById('ms').onclick = async()=>{
      const errEl  = document.getElementById('merr');
      const custEl = document.getElementById('es-cust');
      const dateEl = document.getElementById('es-date');
      const payEl  = document.getElementById('es-pay');
      const stEl   = document.getElementById('es-status');
      const notEl  = document.getElementById('es-notes');
      // جمع الأصناف من الجدول
      const rows = document.querySelectorAll('#es-items-body tr');
      const items = [];
      rows.forEach(row=>{
        const pid   = parseInt(row.id.replace('esi-row-',''));
        const qtyEl = row.querySelector('[id^="esq-"]');
        const prEl  = row.querySelector('[id^="esp-"]');
        if(!pid||!qtyEl||!prEl) return;
        items.push({ product_id:pid, qty:parseInt(qtyEl.value)||1, price:parseFloat(prEl.value)||0 });
      });
      if(!items.length){ errEl.innerHTML='<div class="err">أضف صنفاً واحداً على الأقل</div>'; return; }
      try{
        await api('PUT','/api/sales/'+MS.data.id,{
          customer_id: custEl?.value ? parseInt(custEl.value) : null,
          date:    dateEl?.value||'',
          pay_method: payEl?.value||'نقدي',
          status:  stEl?.value||'مدفوع',
          notes:   notEl?.value||'',
          items
        });
        await loadAll();
        MS={type:'saleslist'}; render();
      }catch(e){
        errEl.innerHTML='<div class="err">خطأ: '+e.message+'</div>';
      }
    };
  }

  // ── تحديث حالة الشيك ──
  if(MS?.type==='chequeStatus'){
    _selectedChqStatus = MS.data?.currentStatus || 'قيد التحصيل';
    document.getElementById('ms').onclick = async()=>{
      const status  = _selectedChqStatus || MS.data?.currentStatus;
      const notes   = document.getElementById('cst-notes')?.value||'';
      const errEl   = document.getElementById('merr');
      if(!status){ errEl.innerHTML='<div class="err">اختر حالة الشيك</div>'; return; }

      // تحديد الصورة: جديدة أو محذوفة أو موجودة
      let imageVal = undefined;  // undefined = لا تغيير
      const newImgTag = document.getElementById('cst-img-tag');
      const newImgSrc = newImgTag?.src;
      if(window._cstDeleteImage){
        imageVal = '';  // حذف
      } else if(newImgSrc && newImgSrc.startsWith('data:image') && newImgSrc !== MS.data?.currentImage){
        imageVal = newImgSrc;  // صورة جديدة
      }

      const body = {cheque_status: status, notes};
      if(imageVal !== undefined) body.cheque_image = imageVal;

      try{
        await api('PUT','/api/payments/'+MS.data.id, body);
        _selectedChqStatus = null;
        window._cstDeleteImage = false;
        closeM();
        await loadCheques();
      }catch(e){
        errEl.innerHTML='<div class="err">'+e.message+'</div>';
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

  // ── مودال المستخدم ──
  if(MS?.type==='userform'){
    const isEdit = !!MS.data?.id;
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const fname  = document.getElementById('uf-fullname')?.value?.trim()||'';
      const role   = document.getElementById('uf-role')?.value||'user';
      const active = parseInt(document.getElementById('uf-active')?.value||'1');
      const pw     = document.getElementById('uf-pw')?.value||'';
      const pw2    = document.getElementById('uf-pw2')?.value||'';

      if(pw && pw !== pw2){
        errEl.innerHTML='<div class="err">كلمتا المرور غير متطابقتين</div>'; return;
      }
      if(pw && pw.length < 4){
        errEl.innerHTML='<div class="err">كلمة المرور 4 أحرف على الأقل</div>'; return;
      }

      try{
        let result;
        if(isEdit){
          const body = {full_name:fname, role, is_active:active};
          if(pw) body.password = pw;
          result = await api('PUT','/api/users/'+MS.data.id, body);
          // تحديث القائمة المحلية
          const idx = sysUsers.findIndex(u=>u.id===MS.data.id);
          if(idx>=0) sysUsers[idx] = {...sysUsers[idx], ...result};
        } else {
          const uname = document.getElementById('uf-username')?.value?.trim()||'';
          if(!uname){ errEl.innerHTML='<div class="err">اسم المستخدم مطلوب</div>'; return; }
          if(!pw){ errEl.innerHTML='<div class="err">كلمة المرور مطلوبة</div>'; return; }
          result = await api('POST','/api/users',{username:uname, password:pw, full_name:fname, role});
          sysUsers.push(result);
        }
        closeM();
        // تحديث عرض المستخدمين
        renderSettingsTab('users');
      }catch(e){
        errEl.innerHTML='<div class="err">'+e.message+'</div>';
      }
    };
  }

  // ── إضافة/تعديل مصروف عام ──
  if(MS?.type==='expenseform'){
    const isEdit = !!MS.data?.id;
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const category_id = document.getElementById('ef-cat')?.value;
      const amount = parseFloat(document.getElementById('ef-amount')?.value||0);
      const description = document.getElementById('ef-desc')?.value?.trim()||'';
      const date = document.getElementById('ef-date')?.value||'';
      const method = document.getElementById('ef-method')?.value||'نقدي';
      if(!description){ errEl.innerHTML='<div class="err">الوصف مطلوب</div>'; return; }
      if(!amount||amount<=0){ errEl.innerHTML='<div class="err">المبلغ يجب أن يكون أكبر من صفر</div>'; return; }
      const body = {
        category_id: category_id?parseInt(category_id):null, description, amount, date,
        payment_method: method,
        cheque_no: document.getElementById('ef-cheque-no')?.value||'',
        cheque_date: document.getElementById('ef-cheque-date')?.value||'',
        cheque_bank: document.getElementById('ef-cheque-bank')?.value||'',
        notes: document.getElementById('ef-notes')?.value||'',
      };
      try{
        if(isEdit) await api('PUT','/api/expenses/'+MS.data.id, body);
        else await api('POST','/api/expenses', body);
        await loadAll();
        page='expenses'; _expTab='general'; closeM();
      }catch(e){ errEl.innerHTML='<div class="err">'+e.message+'</div>'; }
    };
  }

  // ── إضافة/تعديل موظف ──
  if(MS?.type==='employeeform'){
    const isEdit = !!MS.data?.id;
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const name = document.getElementById('emf-name')?.value?.trim()||'';
      const salary = parseFloat(document.getElementById('emf-salary')?.value||0);
      if(!name){ errEl.innerHTML='<div class="err">اسم الموظف مطلوب</div>'; return; }
      const body = {
        name, position: document.getElementById('emf-position')?.value||'',
        phone: document.getElementById('emf-phone')?.value||'',
        base_salary: salary, hire_date: document.getElementById('emf-hiredate')?.value||'',
        is_active: parseInt(document.getElementById('emf-active')?.value||'1'),
        notes: document.getElementById('emf-notes')?.value||'',
      };
      try{
        if(isEdit) await api('PUT','/api/employees/'+MS.data.id, body);
        else await api('POST','/api/employees', body);
        await loadAll();
        page='expenses'; _expTab='employees'; closeM();
      }catch(e){ errEl.innerHTML='<div class="err">'+e.message+'</div>'; }
    };
  }

  // ── تفاصيل موظف: تحميل السلف + ربط أزرار الدفع والسلفة ──
  if(MS?.type==='employeedetail'){
    const emp = MS.data;
    loadEmployeeAdvances(emp.id);
    document.getElementById('emp-pay-salary')?.addEventListener('click', async()=>{
      try{
        const advs = await api('GET','/api/salary_advances?employee_id='+emp.id);
        const advancesTotal = advs.filter(a=>!a.payroll_id).reduce((s,a)=>s+a.amount,0);
        MS = {type:'payrollform', data:{employee: emp, advancesTotal}};
        render();
      }catch(e){ alert('خطأ: '+e.message); }
    });
    document.getElementById('emp-add-advance')?.addEventListener('click', async()=>{
      const amount = prompt('أدخل مبلغ السلفة:');
      if(amount===null) return;
      const amt = parseFloat(amount);
      if(!amt || amt<=0){ alert('مبلغ غير صالح'); return; }
      try{
        await api('POST','/api/salary_advances', {
          employee_id: emp.id, amount: amt, date: new Date().toISOString().slice(0,10),
          notes: prompt('ملاحظات (اختياري):')||''
        });
        await loadEmployeeAdvances(emp.id);
      }catch(e){ alert('خطأ: '+e.message); }
    });
  }

  // ── دفع راتب موظف ──
  if(MS?.type==='payrollform'){
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const emp = MS.data.employee;
      const adjustment = parseFloat(document.getElementById('pf-adjustment')?.value||0)||0;
      const date_paid = document.getElementById('pf-date')?.value||'';
      const payment_method = document.getElementById('pf-method')?.value||'نقدي';
      if(!date_paid){ errEl.innerHTML='<div class="err">حدد تاريخ الدفع</div>'; return; }
      const btn = document.getElementById('ms');
      btn.disabled=true; btn.textContent='⏳ جاري الحفظ...';
      try{
        await api('POST','/api/payroll', {
          employee_id: emp.id, month: currentMonth(), date_paid, payment_method,
          adjustment, adjustment_notes: document.getElementById('pf-adj-notes')?.value||'',
          notes: document.getElementById('pf-notes')?.value||'',
        });
        await loadAll();
        page='expenses'; _expTab='employees'; closeM();
      }catch(e){
        errEl.innerHTML='<div class="err">'+e.message+'</div>';
        btn.disabled=false; btn.textContent='💾 تأكيد دفع الراتب';
      }
    };
  }

  // ── إضافة/تعديل مصروف متكرر ──
  if(MS?.type==='recurringform'){
    const isEdit = !!MS.data?.id;
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const description = document.getElementById('rcf-desc')?.value?.trim()||'';
      const amount = parseFloat(document.getElementById('rcf-amount')?.value||0);
      if(!description){ errEl.innerHTML='<div class="err">الوصف مطلوب</div>'; return; }
      if(!amount||amount<=0){ errEl.innerHTML='<div class="err">المبلغ يجب أن يكون أكبر من صفر</div>'; return; }
      const body = {
        category_id: parseInt(document.getElementById('rcf-cat')?.value)||null,
        description, amount,
        day_of_month: parseInt(document.getElementById('rcf-day')?.value||1),
        is_active: parseInt(document.getElementById('rcf-active')?.value||'1'),
        notes: document.getElementById('rcf-notes')?.value||'',
      };
      try{
        if(isEdit) await api('PUT','/api/recurring_expenses/'+MS.data.id, body);
        else await api('POST','/api/recurring_expenses', body);
        await loadAll();
        page='expenses'; _expTab='recurring'; closeM();
      }catch(e){ errEl.innerHTML='<div class="err">'+e.message+'</div>'; }
    };
  }

  // ── تسجيل دفعة مصروف متكرر لهذا الشهر ──
  if(MS?.type==='payrecurring'){
    document.getElementById('ms').onclick = async()=>{
      const errEl = document.getElementById('merr');
      const amount = parseFloat(document.getElementById('pr-amount')?.value||0);
      const date = document.getElementById('pr-date')?.value||'';
      if(!amount||amount<=0){ errEl.innerHTML='<div class="err">المبلغ يجب أن يكون أكبر من صفر</div>'; return; }
      if(!date){ errEl.innerHTML='<div class="err">حدد التاريخ</div>'; return; }
      try{
        await api('POST','/api/recurring_expenses/'+MS.data.id+'/pay', {
          amount, date, payment_method: document.getElementById('pr-method')?.value||'نقدي',
          notes: document.getElementById('pr-notes')?.value||'',
        });
        await loadAll();
        page='expenses'; _expTab='recurring'; closeM();
      }catch(e){ errEl.innerHTML='<div class="err">'+e.message+'</div>'; }
    };
  }
}

// ── فتح مودال إضافة دفعة ──
window.openPay = async function(ref_id, ref_type){
  // جلب الدفعات المسبقة لحساب المتبقي
  const inv = ref_type==='purchase' ? purchases.find(p=>p.id===ref_id)
    : ref_type==='service' ? serviceOrders.find(o=>o.id===ref_id)
    : sales.find(s=>s.id===ref_id);
  if(!inv){ alert('الفاتورة غير موجودة'); return; }
  const invTotal = ref_type==='service' ? inv.service_fee : inv.total;

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
    total: invTotal,
    paid: paidSoFar
  }};
  render();
};

// ── عرض سجل الدفعات ──
window.viewPayHist = async function(ref_id, ref_type){
  const inv = ref_type==='purchase' ? purchases.find(p=>p.id===ref_id)
    : ref_type==='service' ? serviceOrders.find(o=>o.id===ref_id)
    : sales.find(s=>s.id===ref_id);
  if(!inv){ alert('الفاتورة غير موجودة'); return; }
  const invTotal = ref_type==='service' ? inv.service_fee : inv.total;

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
    total: invTotal,
    payments,
    party_type: ref_type==='purchase'?'supplier':'customer',
    party_id
  }};
  render();
};

window.updCart=function(idx,f,v){const i=cart[idx];if(!i)return;if(f==='qty'&&i.serials&&i.serials.length)return;i[f]=+v;};
window.remCart=function(idx){cart.splice(idx,1);MS={type:'purform'};render();};

// ── تعديل فاتورة مشتريات ──
window.editPur = function(id){
  const p = purchases.find(x=>x.id===id);
  if(!p){ alert('الفاتورة غير موجودة'); return; }
  cart = (p.items||[]).map(i=>({
    product_id: i.product_id,
    name: i.product_name || products.find(x=>x.id===i.product_id)?.name || '—',
    qty: i.qty,
    price: i.price,
    serials: []  // السيريالات الأصلية للفاتورة لا تُستعاد هنا؛ الأصناف المسلسلة الجديدة فقط تتطلب سيريال
  }));
  MS = {type:'editpur', editId:id, data:p};
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
      document.getElementById('pur-grand').textContent='الاجمالي: '+fl.reduce((s,p)=>s+p.total,0).toLocaleString()+' '+cur();
    };
    document.getElementById('pfc').onclick=()=>{
      document.getElementById('pur-tb').innerHTML=purRows(purchases);
      document.getElementById('pur-sum').innerHTML=purSum(purchases);
      document.getElementById('pur-grand').textContent='الاجمالي: '+purchases.reduce((s,p)=>s+p.total,0).toLocaleString()+' '+cur();
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
      afterRepRender(btn.dataset.rep);
    };
  });
  if(page==='reports') afterRepRender('sales');

  // Settings
  if(page==='settings'){
    bindSettingsTabs();
  }

  // Expenses
  if(page==='expenses'){
    bindExpensesTab();
  }

  // Services
  if(page==='services'){
    document.getElementById('svc-add-btn')?.addEventListener('click', ()=>{ MS={type:'serviceform', data:{}}; render(); });
    document.getElementById('svc-status-filter')?.addEventListener('change', applySvcFilter);
  }

  bindPOS();
}

// يُستدعى بعد إدراج HTML أي تبويب تقرير، لتفعيل الحساب/الرسم الديناميكي للتبويبات التي تحتاج ذلك
function afterRepRender(type){
  if(type==='sales') renderSalesReport();
  if(type==='top-products') renderTopProducts();
  if(type==='sup-compare') renderSupplierCompare();
  if(type==='expenses-report') renderExpensesReport();
}

// ── POS ────────────────────────────────────────
let pCart=[];
let _posShortcutHandler = null;
function bindPOS(){
  const inp=document.getElementById('pi');
  if(!inp){
    // خرجنا من صفحة نقطة البيع — أزل مستمع الاختصارات إن كان مفعّلاً
    if(_posShortcutHandler){ document.removeEventListener('keydown', _posShortcutHandler); _posShortcutHandler=null; }
    return;
  }
  inp.addEventListener('input', ()=>posSuggest(inp.value));
  inp.addEventListener('keydown', posKeyNav);
  document.getElementById('pco')?.addEventListener('click', posCheckout);
  document.getElementById('pcl')?.addEventListener('click', ()=>{ pCart=[]; renderCart(); });
  document.getElementById('phl-btn')?.addEventListener('click', holdSale);
  document.getElementById('pqc-btn')?.addEventListener('click', openQuickCustomer);

  // بحث الفئات في الشريط الجانبي
  document.getElementById('cat-search')?.addEventListener('input', function(){
    const q = this.value.trim().toLowerCase();
    document.querySelectorAll('[data-cat]').forEach(el=>{
      el.style.display = !q || el.dataset.cat.toLowerCase().includes(q) ? '' : 'none';
    });
  });

  setTimeout(()=>{
    document.addEventListener('click', function(e){
      const box=document.getElementById('pos-suggest');
      if(!box||!inp) return;
      if(!inp.contains(e.target)&&!box.contains(e.target)){ box.style.display='none'; posSugIdx=-1; }
    });
  },100);

  // اختصارات لوحة المفاتيح: F1 تركيز البحث، F2 إتمام البيع، F3 حذف آخر صنف
  if(_posShortcutHandler) document.removeEventListener('keydown', _posShortcutHandler);
  _posShortcutHandler = function(e){
    if(page!=='pos' || MS) return; // تجاهل الاختصارات أثناء وجود نافذة مفتوحة
    if(e.key==='F1'){ e.preventDefault(); document.getElementById('pi')?.focus(); }
    else if(e.key==='F2'){ e.preventDefault(); posCheckout(); }
    else if(e.key==='F3'){ e.preventDefault(); if(pCart.length) remCartItem(pCart.length-1); }
    else if(e.key==='F4'){ e.preventDefault(); holdSale(); }
  };
  document.addEventListener('keydown', _posShortcutHandler);

  inp.focus();
  renderCart();
  // إظهار الفواتير المعلقة من الجلسة السابقة
  window._renderHeldSales();
}

// فلترة الفئة
window.filterCat = function(cat){
  // تحديث الزر المختار
  document.querySelectorAll('[data-cat]').forEach(el=>{
    el.style.background='';
    el.style.color='#94a3b8';
    el.style.border='1px solid transparent';
  });
  const allBtn = document.getElementById('cat-all');
  if(!cat){
    if(allBtn){ allBtn.style.background='rgba(45,106,79,.2)'; allBtn.style.color='#52b788'; allBtn.style.border='1px solid rgba(45,106,79,.3)'; }
  } else {
    if(allBtn){ allBtn.style.background=''; allBtn.style.color='#64748b'; allBtn.style.border='1px solid transparent'; }
    const catEl = document.querySelector(`[data-cat="${cat}"]`);
    if(catEl){ catEl.style.background='rgba(45,106,79,.15)'; catEl.style.color='#52b788'; catEl.style.border='1px solid rgba(45,106,79,.25)'; }
  }

  // فلترة المنتجات
  const filtered = cat ? products.filter(p=>(p.category||'عام')===cat) : products;
  const grid = document.getElementById('pos-grid');
  const title= document.getElementById('pos-cat-title');
  if(grid) grid.innerHTML = filtered.map(p=>posProductCard(p)).join('') || '<div style="color:#475569;text-align:center;padding:28px;font-size:13px;">لا توجد منتجات في هذه الفئة</div>';
  if(title) title.innerHTML = (cat
    ? `<span>فئة: <span style="color:#52b788;font-weight:700;">${cat}</span> — <span style="color:#52b788;">${filtered.length} منتج</span></span>`
    : `<span>عرض جميع المنتجات — <span style="color:#52b788;">${filtered.length} منتج</span></span>`)
    + `<span style="font-size:11px;color:#475569;"><span class="badge b" style="font-size:10px;">F1</span> بحث
       <span class="badge g" style="font-size:10px;margin-right:4px;">F2</span> إتمام البيع
       <span class="badge r" style="font-size:10px;margin-right:4px;">F3</span> حذف آخر صنف
       <span class="badge y" style="font-size:10px;margin-right:4px;">F4</span> تعليق</span>`;

  // إعادة تركيز البحث
  document.getElementById('pi')?.focus();
};

window.addCart=function(id){
  const p=products.find(x=>x.id===id); if(!p) return;
  if(p.track_serial){ openUnitPicker(p); return; }
  const ex=pCart.find(i=>i.id===p.id && !i.unit_serial);
  if(ex){ ex.qty++; }
  else { pCart.push({...p, qty:1, customPrice:p.sell_price, note:'', discount:0}); }
  renderCart();
};

function renderCart(){
  const ci  = document.getElementById('ci');
  const ct  = document.getElementById('ct');
  const cc  = document.getElementById('cc');
  const icu = document.getElementById('pos-unit-count');
  const ics = document.getElementById('pos-items-count');
  if(!ci) return;

  const sumRaw  = pCart.reduce((s,i)=>s + i.qty*(i.customPrice??i.sell_price),0);
  const itemDisc = pCart.reduce((s,i)=>s + (i.discount||0),0);
  const subTot   = sumRaw - itemDisc;
  const tot      = Math.max(0, subTot - (posInvDiscount||0));
  const units    = pCart.reduce((s,i)=>s+i.qty,0);
  const itemsCnt = pCart.length;

  if(ct)  ct.innerHTML  = `${tot.toLocaleString()} <span style="font-size:13px;">${cur()}</span>`;
  if(cc)  { cc.textContent = itemsCnt+' صنف'; cc.style.display = itemsCnt ? 'inline-block':'none'; }
  if(icu) icu.textContent = units + ' وحدة';
  if(ics) ics.textContent = itemsCnt + ' صنف';

  if(!pCart.length){
    const heldCount = (window._heldSales||[]).length;
    ci.innerHTML = `
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#334155;padding:30px;text-align:center;">
      <div style="font-size:48px;margin-bottom:12px;opacity:.4;">🛒</div>
      <div style="font-size:14px;font-weight:600;color:#475569;margin-bottom:6px;">السلة فارغة</div>
      <div style="font-size:12px;color:#334155;">اضغط على منتج من القائمة أو ابحث بالأعلى</div>
      ${heldCount ? `<div style="margin-top:12px;font-size:12px;color:#52b788;">⏸️ ${heldCount} فاتورة معلقة — استعدها من الأعلى</div>` : ''}
    </div>`;
    window._renderHeldSales();
    return;
  }

  ci.innerHTML = `
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr style="position:sticky;top:0;z-index:10;background:#1a1d27;">
        <th style="padding:8px 10px;text-align:right;font-size:11px;font-weight:700;color:#64748b;border-bottom:2px solid #2d3349;width:30%;">المنتج</th>
        <th style="padding:8px 4px;text-align:center;font-size:11px;font-weight:700;color:#64748b;border-bottom:2px solid #2d3349;width:16%;">الكمية</th>
        <th style="padding:8px 4px;text-align:center;font-size:11px;font-weight:700;color:#64748b;border-bottom:2px solid #2d3349;width:16%;">السعر</th>
        <th style="padding:8px 4px;text-align:center;font-size:11px;font-weight:700;color:#fbbf24;border-bottom:2px solid #2d3349;width:14%;">خصم</th>
        <th style="padding:8px 4px;text-align:center;font-size:11px;font-weight:700;color:#52b788;border-bottom:2px solid #2d3349;width:14%;">الإجمالي</th>
        <th style="padding:8px 4px;border-bottom:2px solid #2d3349;width:10%;"></th>
      </tr>
    </thead>
    <tbody>
    ${pCart.map((item,idx)=>{
      const price     = item.customPrice ?? item.sell_price;
      const discount  = item.discount || 0;
      const lineTotal = item.qty * price - discount;
      const rowBg     = idx%2===0 ? '#0f1117' : '#111520';
      return `
      <tr style="background:${rowBg};" id="cart-row-${idx}">
        <!-- المنتج + ملاحظة -->
        <td style="padding:8px 10px;vertical-align:top;border-bottom:1px solid #1a1d27;">
          <div style="font-size:12px;font-weight:700;color:#f1f5f9;line-height:1.3;
            overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;"
            title="${item.name}">${item.name}</div>
          <div style="font-size:10px;color:#334155;font-family:monospace;margin-top:2px;">${item.unit_serial ? '📟 '+item.unit_serial : (item.barcode||'')}</div>
          <input type="text" placeholder="ملاحظة..." value="${item.note||''}"
            onchange="setItemNote(${idx},this.value)"
            style="margin-top:4px;width:100%;background:transparent;border:none;border-bottom:1px solid #1e2537;
                   color:#64748b;font-size:10px;padding:2px 0;font-family:inherit;outline:none;"
            onfocus="this.style.borderColor='#2d6a4f'" onblur="this.style.borderColor='#1e2537'"/>
        </td>
        <!-- الكمية -->
        <td style="padding:8px 4px;text-align:center;border-bottom:1px solid #1a1d27;vertical-align:middle;">
          ${item.unit_serial ? `<span class="badge g" style="font-size:10px;">قطعة واحدة</span>` : `
          <div style="display:flex;align-items:center;justify-content:center;gap:2px;">
            <button onclick="pCQ(${idx},-1)"
              style="width:24px;height:24px;background:#1a1d27;border:1px solid #2d3349;border-radius:4px;
                     color:#94a3b8;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;"
              onmouseover="this.style.background='#252839';this.style.color='#f87171'"
              onmouseout="this.style.background='#1a1d27';this.style.color='#94a3b8'">−</button>
            <input type="number" min="1" value="${item.qty}"
              onchange="setQty(${idx},this.value)"
              style="width:30px;height:24px;background:#161923;border:1px solid #2d3349;border-radius:4px;
                     color:#f1f5f9;text-align:center;font-size:12px;font-weight:800;font-family:inherit;padding:0;"/>
            <button onclick="pCQ(${idx},1)"
              style="width:24px;height:24px;background:#1a1d27;border:1px solid #2d3349;border-radius:4px;
                     color:#94a3b8;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;"
              onmouseover="this.style.background='#252839';this.style.color='#52b788'"
              onmouseout="this.style.background='#1a1d27';this.style.color='#94a3b8'">+</button>
          </div>`}
        </td>
        <!-- السعر -->
        <td style="padding:8px 4px;text-align:center;border-bottom:1px solid #1a1d27;vertical-align:middle;">
          <input type="number" min="0" step="0.01" value="${price}"
            onchange="setPrice(${idx},this.value)"
            style="width:64px;height:24px;background:#161923;border:1px solid ${price < item.sell_price ? '#5c2323':'#2d3349'};
                   border-radius:4px;color:${price !== item.sell_price ? '#fbbf24':'#94a3b8'};
                   text-align:center;font-size:11px;font-weight:700;font-family:inherit;padding:0 2px;"/>
          ${price !== item.sell_price ? `<div style="font-size:9px;color:#64748b;margin-top:1px;">أصلي: ${item.sell_price}</div>`:''}
        </td>
        <!-- خصم الصنف -->
        <td style="padding:8px 4px;text-align:center;border-bottom:1px solid #1a1d27;vertical-align:middle;">
          <input type="number" min="0" step="1" value="${discount}"
            onchange="setItemDiscount(${idx},this.value)"
            style="width:56px;height:24px;background:#161923;border:1px solid ${discount>0?'#5c4f1e':'#2d3349'};
                   border-radius:4px;color:${discount>0?'#fbbf24':'#94a3b8'};
                   text-align:center;font-size:11px;font-weight:700;font-family:inherit;padding:0 2px;"
            placeholder="0"/>
        </td>
        <!-- الإجمالي -->
        <td style="padding:8px 4px;text-align:center;border-bottom:1px solid #1a1d27;vertical-align:middle;">
          <div style="font-size:12px;font-weight:800;color:${discount>0?'#fbbf24':'#52b788'};">${Math.max(0,lineTotal).toLocaleString()}</div>
        </td>
        <!-- حذف -->
        <td style="padding:8px 2px;text-align:center;border-bottom:1px solid #1a1d27;vertical-align:middle;">
          <button onclick="remCartItem(${idx})"
            style="width:24px;height:24px;background:transparent;border:1px solid #3d1515;border-radius:4px;
                   color:#f87171;cursor:pointer;font-size:11px;display:flex;align-items:center;justify-content:center;"
            onmouseover="this.style.background='#3d1515'"
            onmouseout="this.style.background='transparent'">✕</button>
        </td>
      </tr>`;
    }).join('')}
    </tbody>
    <!-- صف الإجمالي الفرعي + خصم الفاتورة -->
    <tfoot>
      <tr style="background:#1a1d27;border-top:2px solid #2d3349;">
        <td colspan="2" style="padding:8px 10px;font-size:11px;color:#64748b;">
          ${itemsCnt} صنف — ${units} وحدة
        </td>
        <td style="padding:8px 4px;text-align:center;font-size:11px;color:#64748b;">المجموع</td>
        <td colspan="2" style="padding:8px 6px;text-align:center;font-size:14px;font-weight:900;color:#52b788;">
          ${subTot.toLocaleString()} ${cur()}
        </td>
      </tr>
      ${posInvDiscount>0?`
      <tr style="background:#1a1d27;">
        <td colspan="2" style="padding:6px 10px;font-size:11px;color:#64748b;"></td>
        <td style="padding:6px 4px;text-align:center;font-size:11px;color:#f87171;">خصم فاتورة</td>
        <td colspan="2" style="padding:6px 6px;text-align:center;font-size:12px;font-weight:700;color:#f87171;">
          -${posInvDiscount.toLocaleString()} ${cur()}
        </td>
      </tr>`:''}
      ${(posInvDiscount>0 || pCart.some(i=>(i.discount||0)>0))?`
      <tr style="background:#0f1117;border-top:1px solid #2d3349;">
        <td colspan="2" style="padding:8px 10px;font-size:11px;color:#64748b;"></td>
        <td style="padding:8px 4px;text-align:center;font-size:12px;color:#f1f5f9;font-weight:700;">الصافي</td>
        <td colspan="2" style="padding:8px 6px;text-align:center;font-size:16px;font-weight:900;color:#52b788;">
          ${tot.toLocaleString()} ${cur()}
        </td>
      </tr>`:''}
    </tfoot>
  </table>`;
  // تحديث قائمة الفواتير المعلقة
  window._renderHeldSales();
}

window.pCQ = function(idx,d){
  const item=pCart[idx]; if(!item||item.unit_serial) return;
  item.qty = Math.max(1, item.qty+d);
  renderCart();
};
window.setQty = function(idx,v){
  const item=pCart[idx]; if(!item||item.unit_serial) return;
  item.qty = Math.max(1, parseInt(v)||1);
  renderCart();
};
window.setPrice = function(idx,v){
  const item=pCart[idx]; if(!item) return;
  item.customPrice = parseFloat(v)||0;
  renderCart();
};
window.setItemNote = function(idx,v){
  const item=pCart[idx]; if(!item) return;
  item.note = v;
};
window.setItemDiscount = function(idx,v){
  const item=pCart[idx]; if(!item) return;
  item.discount = Math.max(0, parseFloat(v)||0);
  renderCart();
};
window.posInvDiscount = 0;
window.setInvDiscount = function(v){
  posInvDiscount = Math.max(0, parseFloat(v)||0);
  renderCart();
};
window.remCartItem = function(idx){
  pCart.splice(idx,1);
  renderCart();
};

// ══════════════════════════════════════════════
//  تعليق واستعادة الفواتير (Hold / Restore)
// ══════════════════════════════════════════════
window._heldSales = JSON.parse(localStorage.getItem('pos_held')||'[]');

window._saveHeldSales = function(){
  localStorage.setItem('pos_held', JSON.stringify(window._heldSales));
};

window._renderHeldSales = function(){
  const area  = document.getElementById('phl-area');
  const list  = document.getElementById('phl-list');
  const count = document.getElementById('phl-count');
  if(!area || !list) return;

  if(!window._heldSales.length){
    area.style.display = 'none';
    return;
  }
  area.style.display = 'block';
  if(count) count.textContent = window._heldSales.length;

  list.innerHTML = window._heldSales
    .sort((a,b)=>b.timestamp - a.timestamp)
    .map(h=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 10px;
                border-bottom:1px solid #1a1d27;background:#0f1117;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:12px;font-weight:700;color:#f1f5f9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${h.label||'فاتورة معلقة'} — <span style="color:#52b788;">${h.total.toLocaleString()} ${cur()}</span>
        </div>
        <div style="font-size:10px;color:#64748b;margin-top:1px;">
          ${h.itemCount} صنف — ${h.date} ${h.time}
          ${h.custName?` — 👤 ${h.custName}`:''}
        </div>
      </div>
      <div style="display:flex;gap:4px;margin-right:8px;flex-shrink:0;">
        <button class="btn p" style="padding:3px 9px;font-size:11px;" onclick="restoreHeld('${h.id}')">↩️ استعادة</button>
        <button class="btn d" style="padding:3px 7px;font-size:11px;" onclick="deleteHeld('${h.id}')">🗑️</button>
      </div>
    </div>`).join('');
};

window.holdSale = function(){
  if(!pCart.length){ alert('السلة فارغة — لا يوجد شيء لتعليقه'); return; }
  const custName = document.getElementById('pc')?.selectedOptions?.[0]?.text||'';
  const notes    = document.getElementById('pos-notes')?.value||'';
  const now      = new Date();
  const heldItem = {
    id:         Date.now().toString(36) + Math.random().toString(36).slice(2,6),
    timestamp:  now.getTime(),
    date:       now.toISOString().slice(0,10),
    time:       now.toTimeString().slice(0,5),
    label:      notes ? notes.slice(0,30) : '',
    custName:   custName === '-- زبون عام --' ? '' : custName,
    cart:       JSON.parse(JSON.stringify(pCart)),
    customer:   document.getElementById('pc')?.value||null,
    pay_method: document.getElementById('pm')?.value||'نقدي',
    notes:      notes,
    total:      Math.max(0, pCart.reduce((s,i)=>s+i.qty*(i.customPrice??i.sell_price),0) - pCart.reduce((s,i)=>s+(i.discount||0),0) - (posInvDiscount||0)),
    itemCount:  pCart.reduce((s,i)=>s+i.qty,0),
    invDiscount: posInvDiscount||0
  };
  window._heldSales.push(heldItem);
  window._saveHeldSales();
  pCart = [];
  posInvDiscount = 0;
  const discInp = document.getElementById('pos-inv-disc');
  if(discInp) discInp.value = '0';
  renderCart();
  window._renderHeldSales();
};

window.restoreHeld = function(id){
  const idx = window._heldSales.findIndex(h=>h.id===id);
  if(idx===-1) return;
  const h = window._heldSales[idx];
  pCart = JSON.parse(JSON.stringify(h.cart));
  if(h.customer){
    const sel = document.getElementById('pc');
    if(sel){ sel.value = h.customer; }
  }
  if(h.pay_method){
    const sel = document.getElementById('pm');
    if(sel){ sel.value = h.pay_method; }
  }
  if(h.notes !== undefined){
    const inp = document.getElementById('pos-notes');
    if(inp) inp.value = h.notes;
  }
  if(h.invDiscount !== undefined){
    posInvDiscount = h.invDiscount;
    const discInp = document.getElementById('pos-inv-disc');
    if(discInp) discInp.value = h.invDiscount;
  }
  window._heldSales.splice(idx,1);
  window._saveHeldSales();
  renderCart();
  window._renderHeldSales();
};

window.deleteHeld = function(id){
  window._heldSales = window._heldSales.filter(h=>h.id!==id);
  window._saveHeldSales();
  window._renderHeldSales();
};

window.clearAllHeld = function(){
  if(window._heldSales.length && !confirm('حذف جميع الفواتير المعلقة؟')) return;
  window._heldSales = [];
  window._saveHeldSales();
  window._renderHeldSales();
};

async function posCheckout(){
  if(!pCart.length){ alert('السلة فارغة'); return; }
  const cust   = document.getElementById('pc')?.value||null;
  const pay    = document.getElementById('pm')?.value||'نقدي';
  const notes  = document.getElementById('pos-notes')?.value||'';
  const btn    = document.getElementById('pco');
  if(btn){ btn.disabled=true; btn.textContent='⏳ جاري الحفظ...'; }
  try{
    const rawTotal = pCart.reduce((s,i)=>s + i.qty*(i.customPrice??i.sell_price),0);
    const itemDiscTotal = pCart.reduce((s,i)=>s + (i.discount||0),0);
    const invDiscount = posInvDiscount||0;
    const finalTotal = Math.max(0, rawTotal - itemDiscTotal - invDiscount);
    const res = await api('POST','/api/sales',{
      customer_id: cust ? +cust : null,
      date: new Date().toISOString().slice(0,10),
      status: pay==='آجل' ? 'معلق' : 'مدفوع',
      pay_method: pay,
      notes: notes,
      discount: invDiscount,
      items: pCart.map(i=>({
        product_id: i.id,
        qty: i.qty,
        price: i.customPrice ?? i.sell_price,
        discount: i.discount||0,
        note: i.note||'',
        serials: i.unit_serial ? [i.unit_serial] : []
      }))
    });
    pCart=[];
    posInvDiscount = 0;
    const discInp = document.getElementById('pos-inv-disc');
    if(discInp) discInp.value = '0';
    await loadAll();
    MS={type:'done', data:res};
    render();
  }catch(e){
    alert('خطأ: '+e.message);
    if(btn){ btn.disabled=false; btn.textContent='✅ إتمام البيع'; }
  }
}

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
        <div style="font-weight:800;color:#52b788;font-size:14px;">${p.sell_price.toLocaleString()} ${cur()}</div>
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
  // إغلاق القائمة وتنظيف الحقل
  const box = document.getElementById('pos-suggest');
  const inp = document.getElementById('pi');
  if(box) box.style.display = 'none';
  if(inp){ inp.value = ''; inp.focus(); }
  posSugIdx = -1;
  posAddResolved(p, null);
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
async function posAdd(){
  const inp = document.getElementById('pi');
  const q   = inp?.value?.trim()||'';
  if(!q) return;

  // إغلاق قائمة الاقتراحات
  const box = document.getElementById('pos-suggest');
  if(box) box.style.display = 'none';

  // 1) مسار سريع لقارئ الباركود/السيريال: مطابقة دقيقة عبر السيرفر
  //    (يغطي باركود المنتج، سيريال المنتج العام، وأيضاً سيريال قطعة فريدة إن وُجدت)
  try{
    const r = await api('GET', '/api/products/barcode/'+encodeURIComponent(q));
    posAddResolved(r, r.matched_unit||null);
    if(inp){ inp.value=''; inp.focus(); }
    posSugIdx=-1;
    return;
  }catch(e){ /* لا توجد مطابقة دقيقة — نكمل للبحث النصي المحلي */ }

  // 2) بحث نصي محلي (اسم جزئي)
  const p = products.find(x=>
    x.barcode===q || x.serial===q ||
    x.name===q    || x.name.toLowerCase().includes(q.toLowerCase())
  );
  if(!p){
    if(inp){ inp.style.borderColor='#f87171'; setTimeout(()=>inp.style.borderColor='',1500); }
    alert('المنتج غير موجود — جرب البحث بالاسم أو الباركود');
    return;
  }
  posAddResolved(p, null);
  if(inp){ inp.value=''; inp.focus(); }
  posSugIdx=-1;
}

// إضافة منتج تم التعرف عليه (عن طريق باركود عام أو وحدة سيريال فريدة) إلى السلة
function posAddResolved(p, matchedUnit){
  if(matchedUnit){
    // قطعة سيريال فريدة — سطر مستقل بالسلة بكمية ثابتة = 1
    const already = pCart.find(i=>i.unit_serial===matchedUnit.serial);
    if(already){ alert('هذه القطعة مضافة للسلة مسبقاً'); return; }
    pCart.push({...p, qty:1, unit_id:matchedUnit.id, unit_serial:matchedUnit.serial});
    renderCart();
    return;
  }
  if(p.stock===0){
    if(!confirm('تحذير: المخزون نفد! هل تريد الإضافة للسلة؟')) return;
  }
  if(p.track_serial){
    // منتج يتطلب اختيار قطعة محددة — التوجيه لاختيار السيريال بدل الإضافة العامة
    openUnitPicker(p);
    return;
  }
  const ex=pCart.find(i=>i.id===p.id && !i.unit_serial);
  if(ex) ex.qty++; else pCart.push({...p,qty:1});
  renderCart();
}

// نافذة اختيار قطعة محددة (سيريال) من مخزون منتج يتطلب تتبعاً فريداً
window.openUnitPicker = async function(p){
  let units = [];
  try{ units = await api('GET','/api/units?product_id='+p.id+'&status=in_stock'); }catch(e){}
  if(!units.length){ alert('لا توجد قطع متاحة بالمخزون لهذا المنتج'); return; }
  MS = {type:'unitpicker', data:{product:p, units}};
  render();
};
// ══════════════════════════════════════════════
//  سجل المبيعات + تعديل الفاتورة
// ══════════════════════════════════════════════

window.openSalesList = function(){
  MS={type:'saleslist'}; render();
};

function salesListModal(){
  const list = [...sales].sort((a,b)=>b.id-a.id).slice(0,50);
  return `<div class="overlay" id="mover"><div class="modal" style="max-width:820px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div style="font-size:16px;font-weight:800;color:#f1f5f9;">📋 سجل المبيعات</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div class="card" style="overflow:hidden;">
  <table>
    <thead><tr><th>#</th><th>التاريخ</th><th>الزبون</th><th>الإجمالي</th><th>المدفوع</th><th>المتبقي</th><th>الحالة</th><th>إجراءات</th></tr></thead>
    <tbody>
    ${list.map(s=>{
      const custName = s.customer_id ? (customers.find(c=>c.id===parseInt(s.customer_id))?.name||'—') : 'زبون عام';
      const paid = s.paid||0;
      const rem  = Math.max(0,(s.total||0)-paid);
      return `<tr>
        <td style="color:#64748b;">#${s.id}</td>
        <td style="font-weight:600;">${s.date}</td>
        <td style="color:#52b788;font-weight:600;">${custName}</td>
        <td style="font-weight:700;">${(s.total||0).toLocaleString()} ${cur()}</td>
        <td style="color:#52b788;">${paid.toLocaleString()} ${cur()}</td>
        <td style="color:${rem>0?'#f87171':'#52b788'};">${rem.toLocaleString()} ${cur()}</td>
        <td><span class="badge ${s.status==='مدفوع'?'g':s.status==='مدفوع جزئياً'?'b':'y'}">${s.status}</span></td>
        <td><div style="display:flex;gap:4px;">
          <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="openEditSale(${s.id})">✏️ تعديل</button>
          <button class="btn p" style="padding:3px 8px;font-size:11px;background:linear-gradient(135deg,#1e40af,#1e3a8a);" onclick="openPay(${s.id},'sale')">💳</button>
          <button class="btn d" style="padding:3px 8px;font-size:11px;" onclick="deleteSale(${s.id})">🗑️</button>
        </div></td>
      </tr>`;
    }).join('')}
    </tbody>
  </table>
  </div>
  </div></div>`;
}

window.deleteSale = async function(id){
  if(!confirm('حذف هذه الفاتورة؟ سيتم إرجاع المخزون تلقائياً')) return;
  try{
    await api('DELETE','/api/sales/'+id);
    await loadAll();
    MS={type:'saleslist'}; render();
  }catch(e){ alert('خطأ: '+e.message); }
};

window.openEditSale = async function(id){
  const s = sales.find(x=>x.id===id);
  if(!s){ alert('الفاتورة غير موجودة'); return; }
  MS={type:'editsale', data: JSON.parse(JSON.stringify(s))};
  render();
};

function editSaleModal(s){
  const custOpts = customers.map(c=>`<option value="${c.id}"${parseInt(s.customer_id)===c.id?' selected':''}>${c.name}</option>`).join('');
  const itemRows = (s.items||[]).map(item=>`
  <tr id="esi-row-${item.product_id}">
    <td style="font-weight:600;color:#f1f5f9;font-size:13px;">${item.product_name||products.find(x=>x.id===item.product_id)?.name||'—'}</td>
    <td><input class="inp" type="number" min="1" value="${item.qty}" id="esq-${item.product_id}" style="width:65px;padding:4px 7px;"/></td>
    <td><input class="inp" type="number" min="0" step="0.01" value="${item.price}" id="esp-${item.product_id}" style="width:85px;padding:4px 7px;"/></td>
    <td style="color:#52b788;font-weight:700;">${((item.qty||0)*(item.price||0)).toLocaleString()} ${cur()}</td>
    <td><button class="btn d" style="padding:3px 7px;" onclick="removeEsItem(${item.product_id})">🗑️</button></td>
  </tr>`).join('');

  const prodOpts = products.map(p=>`<option value="${p.id}" data-price="${p.sell_price}">${p.name} — ${p.barcode}</option>`).join('');

  return `<div class="overlay" id="mover"><div class="modal" style="max-width:720px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div style="font-size:16px;font-weight:800;color:#f1f5f9;">✏️ تعديل فاتورة بيع #${s.id}</div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>
  <div id="merr"></div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;">
    <div><label class="lbl">الزبون</label>
      <select class="inp" id="es-cust">
        <option value="">-- زبون عام --</option>${custOpts}
      </select>
    </div>
    <div><label class="lbl">تاريخ</label>
      <input class="inp" type="date" id="es-date" value="${s.date}"/>
    </div>
    <div><label class="lbl">طريقة الدفع</label>
      <select class="inp" id="es-pay">
        ${['نقدي','بطاقة','تحويل','آجل'].map(m=>`<option${s.pay_method===m?' selected':''}>${m}</option>`).join('')}
      </select>
    </div>
    <div><label class="lbl">الحالة</label>
      <select class="inp" id="es-status">
        ${['مدفوع','معلق','مدفوع جزئياً'].map(st=>`<option${s.status===st?' selected':''}>${st}</option>`).join('')}
      </select>
    </div>
    <div style="grid-column:span 2"><label class="lbl">ملاحظات</label>
      <input class="inp" id="es-notes" value="${s.notes||''}"/>
    </div>
  </div>

  <!-- إضافة صنف -->
  <div style="background:#1a1d27;border:1px solid #2d3349;border-radius:8px;padding:10px;margin-bottom:10px;">
    <div style="font-size:12px;font-weight:700;color:#52b788;margin-bottom:8px;">+ إضافة صنف</div>
    <div style="display:flex;gap:7px;">
      <select class="inp" id="es-prod" style="flex:2;font-size:13px;">
        <option value="">-- اختر منتج --</option>${prodOpts}
      </select>
      <input class="inp" type="number" id="es-qty" placeholder="الكمية" value="1" min="1" style="width:70px;font-size:13px;"/>
      <input class="inp" type="number" id="es-price" placeholder="السعر" step="0.01" style="width:85px;font-size:13px;"/>
      <button class="btn p" id="es-add-btn" style="white-space:nowrap;font-size:13px;">+ إضافة</button>
    </div>
  </div>

  <!-- جدول الأصناف -->
  <div class="card" style="margin-bottom:12px;">
    <table>
      <thead><tr><th>المنتج</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th></th></tr></thead>
      <tbody id="es-items-body">${itemRows}</tbody>
    </table>
  </div>

  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;">💾 حفظ التعديلات</button>
    <button class="btn s" onclick="MS={type:'saleslist'};render();">← رجوع للقائمة</button>
    <button class="btn s" id="mc2">إغلاق</button>
  </div>
  </div></div>`;
}

window.removeEsItem = function(pid){
  const row=document.getElementById('esi-row-'+pid);
  if(row) row.remove();
};

// ══════════════════════════════════════════════
//  صفحة الإعدادات
// ══════════════════════════════════════════════
function settingsHTML(){
  const isAdmin = USER?.role==='admin';
  const roleLabel = {admin:'مدير',user:'مستخدم',cashier:'كاشير'};
  return `
  <div class="ti">الإعدادات</div>
  <div class="sub">إعدادات النظام والمستخدمين</div>

  <div style="display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap;" id="set-tabs">
    <button class="btn p" data-stab="general">⚙️ عام</button>
    <button class="btn s" data-stab="currency">💰 العملة</button>
    <button class="btn s" data-stab="expcats">🧾 تصنيفات المصاريف</button>
    ${isAdmin?'<button class="btn s" data-stab="users">👥 المستخدمون</button>':''}
    ${isAdmin?'<button class="btn s" data-stab="backup">💾 النسخ الاحتياطي</button>':''}
    <button class="btn s" data-stab="myaccount">👤 حسابي</button>
  </div>

  <div id="set-content">
  <!-- ── إعدادات عامة ── -->
  <div class="card" style="padding:22px;max-width:560px;">
    <div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:18px;">⚙️ إعدادات عامة</div>
    <div id="set-err"></div>
    <div style="margin-bottom:14px;"><label class="lbl">اسم النظام</label>
      <input class="inp" id="cfg-sysname" value="${(sysSettings.system_name||'').replace(/"/g,'&quot;')}"/>
    </div>
    <div style="margin-bottom:14px;"><label class="lbl">حد المخزون المنخفض (تنبيه عند الوصول لهذا الرقم)</label>
      <input class="inp" type="number" id="cfg-lowstock" value="${sysSettings.low_stock_threshold||20}" min="1"/>
    </div>
    <div style="margin-bottom:14px;"><label class="lbl">حد الزبون المميز (إجمالي المشتريات بـ${cur()})</label>
      <input class="inp" type="number" id="cfg-vipthreshold" value="${sysSettings.vip_customer_threshold||5000}" min="0"/>
    </div>
    <div style="margin-bottom:14px;"><label class="lbl">مدة التأخر بالسداد (أيام) — تنبيه الزبائن المتأخرين</label>
      <input class="inp" type="number" id="cfg-overduedays" value="${sysSettings.overdue_days_threshold||30}" min="1"/>
    </div>
    <div style="margin-bottom:14px;"><label class="lbl">حد تنبيه مستحقات المورد (${cur()}) — تنبيه عند وصول المستحق لهذا الحد</label>
      <input class="inp" type="number" id="cfg-supalert" value="${sysSettings.supplier_payable_alert_threshold||5000}" min="0"/>
    </div>
    ${isAdmin?'<button class="btn p" id="save-general" style="margin-top:4px;">💾 حفظ الإعدادات</button>':'<div style="color:#64748b;font-size:13px;">فقط المدير يمكنه تعديل الإعدادات</div>'}
  </div>
  </div>`;
}

// ── تبويبات الإعدادات ──
function bindSettingsTabs(){
  document.querySelectorAll('[data-stab]').forEach(btn=>{
    btn.onclick=()=>{
      document.querySelectorAll('[data-stab]').forEach(b=>b.className='btn s');
      btn.className='btn p';
      renderSettingsTab(btn.dataset.stab);
    };
  });
  // ربط حفظ الإعدادات العامة
  document.getElementById('save-general')?.addEventListener('click', saveGeneralSettings);
}

async function saveGeneralSettings(){
  const name  = document.getElementById('cfg-sysname')?.value?.trim();
  const low   = document.getElementById('cfg-lowstock')?.value;
  const vip   = document.getElementById('cfg-vipthreshold')?.value;
  const overdue = document.getElementById('cfg-overduedays')?.value;
  const supAlert = document.getElementById('cfg-supalert')?.value;
  const errEl = document.getElementById('set-err');
  if(!name){ if(errEl) errEl.innerHTML='<div class="err">اسم النظام مطلوب</div>'; return; }
  try{
    await api('POST','/api/settings',{system_name:name, low_stock_threshold:low||'20',
      vip_customer_threshold:vip||'5000', overdue_days_threshold:overdue||'30',
      supplier_payable_alert_threshold:supAlert||'5000'});
    sysSettings.system_name = name;
    sysSettings.low_stock_threshold = low;
    sysSettings.vip_customer_threshold = vip;
    sysSettings.overdue_days_threshold = overdue;
    sysSettings.supplier_payable_alert_threshold = supAlert;
    if(errEl) errEl.innerHTML='<div style="background:rgba(45,106,79,.15);border:1px solid rgba(45,106,79,.3);border-radius:8px;padding:10px;color:#52b788;font-size:13px;margin-bottom:10px;text-align:center;">✅ تم الحفظ</div>';
    setTimeout(()=>{ if(errEl) errEl.innerHTML=''; },2500);
  }catch(e){
    if(errEl) errEl.innerHTML='<div class="err">'+e.message+'</div>';
  }
}

function renderSettingsTab(tab){
  const el = document.getElementById('set-content');
  if(!el) return;
  const isAdmin = USER?.role==='admin';
  const roleLabel = {admin:'مدير',user:'مستخدم',cashier:'كاشير'};

  if(tab==='general'){
    el.innerHTML=`
    <div class="card" style="padding:22px;max-width:560px;">
      <div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:18px;">⚙️ إعدادات عامة</div>
      <div id="set-err"></div>
      <div style="margin-bottom:14px;"><label class="lbl">اسم النظام</label>
        <input class="inp" id="cfg-sysname" value="${(sysSettings.system_name||'').replace(/"/g,'&quot;')}"/>
      </div>
      <div style="margin-bottom:14px;"><label class="lbl">حد المخزون المنخفض</label>
        <input class="inp" type="number" id="cfg-lowstock" value="${sysSettings.low_stock_threshold||20}" min="1"/>
      </div>
      <div style="margin-bottom:14px;"><label class="lbl">حد الزبون المميز (إجمالي المشتريات بـ${cur()})</label>
        <input class="inp" type="number" id="cfg-vipthreshold" value="${sysSettings.vip_customer_threshold||5000}" min="0"/>
      </div>
      <div style="margin-bottom:14px;"><label class="lbl">مدة التأخر بالسداد (أيام)</label>
        <input class="inp" type="number" id="cfg-overduedays" value="${sysSettings.overdue_days_threshold||30}" min="1"/>
      </div>
      <div style="margin-bottom:14px;"><label class="lbl">حد تنبيه مستحقات المورد (${cur()})</label>
        <input class="inp" type="number" id="cfg-supalert" value="${sysSettings.supplier_payable_alert_threshold||5000}" min="0"/>
      </div>
      ${isAdmin?'<button class="btn p" id="save-general">💾 حفظ الإعدادات</button>':'<div style="color:#64748b;font-size:13px;">فقط المدير يمكنه تعديل الإعدادات</div>'}
    </div>`;
    document.getElementById('save-general')?.addEventListener('click', saveGeneralSettings);
    return;
  }

  if(tab==='currency'){
    const currencies=[
      {sym:'₪',name:'شيكل إسرائيلي'},
      {sym:'$',name:'دولار أمريكي'},
      {sym:'€',name:'يورو'},
      {sym:'£',name:'جنيه إسترليني'},
      {sym:'¥',name:'ين ياباني'},
      {sym:'د.إ',name:'درهم إماراتي'},
      {sym:'ر.س',name:'ريال سعودي'},
      {sym:'ر.ع',name:'ريال عماني'},
      {sym:'د.ك',name:'دينار كويتي'},
      {sym:'د.ب',name:'دينار بحريني'},
      {sym:'ج.م',name:'جنيه مصري'},
      {sym:'د.ج',name:'دينار جزائري'},
      {sym:'د.ت',name:'دينار تونسي'},
      {sym:'د.م',name:'درهم مغربي'},
      {sym:'ل.ل',name:'ليرة لبنانية'},
      {sym:'ل.س',name:'ليرة سورية'},
    ];
    el.innerHTML=`
    <div class="card" style="padding:22px;max-width:560px;">
      <div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">💰 إعداد العملة</div>
      <div style="font-size:13px;color:#64748b;margin-bottom:18px;">اختر العملة التي ستظهر في جميع أرجاء النظام</div>
      <div id="cur-err"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;">
        ${currencies.map(c=>`
        <div onclick="selectCurrency('${c.sym}','${c.name}')"
          id="cur-${c.sym.replace(/[^a-zA-Z0-9]/g,'x')}"
          style="display:flex;align-items:center;gap:10px;padding:12px 14px;border-radius:10px;cursor:pointer;
                 border:2px solid ${sysSettings.currency===c.sym?'#2d6a4f':'#1e2537'};
                 background:${sysSettings.currency===c.sym?'rgba(45,106,79,.15)':'#1a1d27'};
                 transition:all .15s;">
          <span style="font-size:20px;font-weight:900;color:#52b788;min-width:32px;text-align:center;">${c.sym}</span>
          <span style="font-size:13px;color:#cbd5e1;">${c.name}</span>
          ${sysSettings.currency===c.sym?'<span style="margin-right:auto;color:#52b788;">✓</span>':''}
        </div>`).join('')}
      </div>
      <div style="margin-bottom:14px;">
        <label class="lbl">أو أدخل رمز عملة مخصص</label>
        <div style="display:flex;gap:8px;">
          <input class="inp" id="cur-custom-sym" placeholder="رمز العملة (مثال: TL)" style="width:120px;"/>
          <input class="inp" id="cur-custom-name" placeholder="اسم العملة (مثال: ليرة تركية)" style="flex:1;"/>
          <button class="btn s" onclick="selectCustomCurrency()">تطبيق</button>
        </div>
      </div>
      <div style="background:#1a1d27;border-radius:10px;padding:14px;margin-bottom:16px;display:flex;align-items:center;gap:14px;">
        <span style="font-size:24px;font-weight:900;color:#52b788;" id="cur-preview">${sysSettings.currency}</span>
        <div>
          <div style="font-size:13px;color:#94a3b8;">المعاينة</div>
          <div style="font-size:14px;color:#f1f5f9;margin-top:2px;">١٢٣٤٥ <span id="cur-preview-name">${sysSettings.currency_name||''}</span></div>
        </div>
      </div>
      ${isAdmin?'<button class="btn p" id="save-currency" style="width:100%;justify-content:center;height:42px;">💾 حفظ العملة</button>':'<div style="color:#64748b;font-size:13px;">فقط المدير يمكنه تغيير العملة</div>'}
    </div>`;
    document.getElementById('save-currency')?.addEventListener('click', saveCurrencySettings);
    return;
  }

  if(tab==='expcats'){
    el.innerHTML = `
    <div style="max-width:560px;">
      <div class="card" style="padding:22px;margin-bottom:14px;">
        <div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">🧾 تصنيفات المصاريف</div>
        <div style="font-size:13px;color:#64748b;margin-bottom:16px;">أضف أو عدّل تصنيفات المصاريف المستخدمة بصفحة المصاريف</div>
        <div id="ec-err"></div>
        <div style="display:flex;gap:8px;margin-bottom:16px;">
          <input class="inp" id="ec-icon" placeholder="🏷️" style="width:60px;text-align:center;"/>
          <input class="inp" id="ec-name" placeholder="اسم التصنيف الجديد..." style="flex:1;"/>
          <button class="btn p" id="ec-add">+ إضافة</button>
        </div>
        <div id="ec-list"></div>
      </div>
    </div>`;
    renderExpCatsList();
    document.getElementById('ec-add')?.addEventListener('click', addExpenseCategory);
    return;
  }

  if(tab==='users' && isAdmin){
    el.innerHTML=`
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <div style="font-size:15px;font-weight:800;color:#f1f5f9;">👥 إدارة المستخدمين</div>
      <button class="btn p" onclick="openUserForm()">+ إضافة مستخدم</button>
    </div>
    <div id="users-err"></div>
    <div class="card">
    <table>
      <thead><tr><th>#</th><th>اسم المستخدم</th><th>الاسم الكامل</th><th>الصلاحية</th><th>الحالة</th><th>تاريخ الإنشاء</th><th>إجراءات</th></tr></thead>
      <tbody>
      ${sysUsers.map(usr=>`<tr>
        <td style="color:#64748b;">${usr.id}</td>
        <td style="font-weight:700;color:#60a5fa;font-family:monospace;">${usr.username}</td>
        <td style="color:#f1f5f9;">${usr.full_name||'—'}</td>
        <td><span class="badge ${usr.role==='admin'?'r':usr.role==='cashier'?'b':'g'}">${{admin:'مدير',user:'مستخدم',cashier:'كاشير'}[usr.role]||usr.role}</span></td>
        <td><span class="badge ${usr.is_active?'g':'r'}">${usr.is_active?'نشط':'موقوف'}</span></td>
        <td style="color:#64748b;font-size:12px;">${(usr.created_at||'').slice(0,10)}</td>
        <td><div style="display:flex;gap:5px;">
          <button class="btn s" style="padding:4px 9px;" onclick="openUserForm(${usr.id})">✏️ تعديل</button>
          ${usr.id!==USER?.id?`<button class="btn d" style="padding:4px 9px;" onclick="deleteUser(${usr.id})">🗑️</button>`:'<span style="font-size:11px;color:#64748b;padding:4px;">أنت</span>'}
        </div></td>
      </tr>`).join('')||'<tr><td colspan="7" style="text-align:center;color:#475569;padding:24px;">لا يوجد مستخدمون</td></tr>'}
      </tbody>
    </table>
    </div>`;
    return;
  }

  if(tab==='backup'){
    el.innerHTML=`
    <div style="max-width:700px;">
      <!-- زر إنشاء نسخة جديدة -->
      <div class="card" style="padding:20px;margin-bottom:14px;">
        <div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:6px;">💾 النسخ الاحتياطي</div>
        <div style="font-size:13px;color:#64748b;margin-bottom:16px;">
          أنشئ نسخة احتياطية من قاعدة البيانات أو استعدها من ملف سابق.<br/>
          يتم حفظ آخر 10 نسخ تلقائياً على السيرفر.
        </div>
        <div id="bk-msg"></div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <button class="btn p" id="bk-create" style="height:42px;">
            📦 إنشاء نسخة احتياطية الآن
          </button>
          <label class="btn s" style="height:42px;cursor:pointer;">
            📂 استعادة من ملف
            <input type="file" id="bk-file-inp" accept=".db" style="display:none;" onchange="bkRestoreFile(this)"/>
          </label>
        </div>
      </div>

      <!-- قائمة النسخ المحفوظة -->
      <div class="card" style="padding:0;overflow:hidden;">
        <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;display:flex;justify-content:space-between;align-items:center;">
          <div style="font-size:14px;font-weight:800;color:#f1f5f9;">📋 النسخ المحفوظة على السيرفر</div>
          <button class="btn s" style="padding:4px 12px;font-size:12px;" onclick="bkLoadList()">🔄 تحديث</button>
        </div>
        <div id="bk-list"><div style="text-align:center;padding:30px;"><div class="spin"></div></div></div>
      </div>
    </div>`;
    // تحميل القائمة
    bkLoadList();
    document.getElementById('bk-create').onclick = bkCreate;
    return;
  }

  if(tab==='myaccount'){
    el.innerHTML=`
    <div class="card" style="padding:22px;max-width:480px;">
      <div style="font-size:15px;font-weight:800;color:#f1f5f9;margin-bottom:18px;">👤 حسابي الشخصي</div>
      <div style="background:#1a1d27;border-radius:10px;padding:14px;margin-bottom:18px;">
        <div style="display:flex;align-items:center;gap:14px;">
          <div style="width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#2d6a4f,#1b4332);display:flex;align-items:center;justify-content:center;font-size:20px;">
            ${(USER?.full_name||USER?.username||'؟')[0]}
          </div>
          <div>
            <div style="font-size:15px;font-weight:800;color:#f1f5f9;">${USER?.full_name||'—'}</div>
            <div style="font-size:13px;color:#60a5fa;font-family:monospace;">@${USER?.username||''}</div>
            <span class="badge ${USER?.role==='admin'?'r':USER?.role==='cashier'?'b':'g'}" style="margin-top:4px;display:inline-block;">
              ${{admin:'مدير',user:'مستخدم',cashier:'كاشير'}[USER?.role]||''}
            </span>
          </div>
        </div>
      </div>
      <div style="font-size:14px;font-weight:700;color:#94a3b8;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid #1e2537;">🔑 تغيير كلمة المرور</div>
      <div id="pw-err"></div>
      <div style="margin-bottom:12px;"><label class="lbl">كلمة المرور الحالية</label>
        <input class="inp" type="password" id="pw-old" placeholder="أدخل كلمة المرور الحالية..."/>
      </div>
      <div style="margin-bottom:12px;"><label class="lbl">كلمة المرور الجديدة</label>
        <input class="inp" type="password" id="pw-new" placeholder="4 أحرف على الأقل..."/>
      </div>
      <div style="margin-bottom:16px;"><label class="lbl">تأكيد كلمة المرور الجديدة</label>
        <input class="inp" type="password" id="pw-confirm" placeholder="أعد إدخال كلمة المرور..."/>
      </div>
      <button class="btn p" id="save-pw" style="width:100%;justify-content:center;height:42px;">🔑 تغيير كلمة المرور</button>
    </div>`;
    document.getElementById('save-pw')?.addEventListener('click', changeMyPassword);
    return;
  }
}

// ── اختيار العملة ──
let _selectedCurrency = null;
window.selectCurrency = function(sym, name){
  _selectedCurrency = {sym, name};
  document.querySelectorAll('[id^="cur-"]').forEach(el=>{
    if(el.id.startsWith('cur-') && el.tagName==='DIV'){
      el.style.border='2px solid #1e2537';
      el.style.background='#1a1d27';
      el.innerHTML=el.innerHTML.replace(/<span style="margin-right:auto[^"]*"[^>]*>✓<\/span>/,'');
    }
  });
  const key = 'cur-'+sym.replace(/[^a-zA-Z0-9]/g,'x');
  const el = document.getElementById(key);
  if(el){
    el.style.border='2px solid #2d6a4f';
    el.style.background='rgba(45,106,79,.15)';
    if(!el.querySelector('.cur-check'))
      el.innerHTML += '<span class="cur-check" style="margin-right:auto;color:#52b788;">✓</span>';
  }
  const prev = document.getElementById('cur-preview');
  const prevN= document.getElementById('cur-preview-name');
  if(prev) prev.textContent=sym;
  if(prevN) prevN.textContent=name;
};

window.selectCustomCurrency = function(){
  const sym  = document.getElementById('cur-custom-sym')?.value?.trim();
  const name = document.getElementById('cur-custom-name')?.value?.trim();
  if(!sym){ alert('أدخل رمز العملة'); return; }
  selectCurrency(sym, name||sym);
};

function renderExpCatsList(){
  const el = document.getElementById('ec-list');
  if(!el) return;
  el.innerHTML = expenseCategories.map(c=>`
    <div style="display:flex;align-items:center;gap:10px;padding:9px 12px;background:#1a1d27;border-radius:8px;margin-bottom:6px;">
      <span style="font-size:18px;">${c.icon}</span>
      <span style="flex:1;color:#f1f5f9;font-weight:600;">${esc(c.name)}</span>
      ${c.is_default?'<span class="badge b" style="font-size:10px;">افتراضي</span>':''}
      <button class="btn s" style="padding:3px 8px;font-size:11px;" onclick="editExpenseCategory(${c.id})">✏️</button>
      ${!c.is_default?`<button class="btn d" style="padding:3px 8px;font-size:11px;" onclick="deleteExpenseCategory(${c.id})">🗑️</button>`:''}
    </div>`).join('') || '<div style="color:#64748b;text-align:center;padding:16px;">لا توجد تصنيفات</div>';
}

window.addExpenseCategory = async function(){
  const icon = document.getElementById('ec-icon')?.value?.trim()||'🏷️';
  const name = document.getElementById('ec-name')?.value?.trim()||'';
  const errEl = document.getElementById('ec-err');
  if(!name){ if(errEl) errEl.innerHTML='<div class="err">اسم التصنيف مطلوب</div>'; return; }
  try{
    const cat = await api('POST','/api/expense_categories', {name, icon});
    expenseCategories.push(cat);
    document.getElementById('ec-name').value=''; document.getElementById('ec-icon').value='';
    if(errEl) errEl.innerHTML='';
    renderExpCatsList();
  }catch(e){ if(errEl) errEl.innerHTML='<div class="err">'+e.message+'</div>'; }
};

window.editExpenseCategory = async function(id){
  const cat = expenseCategories.find(c=>c.id===id);
  if(!cat) return;
  const newName = prompt('اسم التصنيف:', cat.name);
  if(newName===null) return;
  const newIcon = prompt('الأيقونة (إيموجي):', cat.icon) || cat.icon;
  try{
    const updated = await api('PUT','/api/expense_categories/'+id, {name:newName, icon:newIcon});
    const idx = expenseCategories.findIndex(c=>c.id===id);
    if(idx>=0) expenseCategories[idx] = updated;
    renderExpCatsList();
  }catch(e){ alert('خطأ: '+e.message); }
};

window.deleteExpenseCategory = async function(id){
  if(!confirm('حذف هذا التصنيف؟')) return;
  try{
    await api('DELETE','/api/expense_categories/'+id);
    expenseCategories = expenseCategories.filter(c=>c.id!==id);
    renderExpCatsList();
  }catch(e){ alert('خطأ: '+e.message); }
};

async function saveCurrencySettings(){
  const sym  = _selectedCurrency?.sym || sysSettings.currency;
  const name = _selectedCurrency?.name || sysSettings.currency_name;
  const errEl= document.getElementById('cur-err');
  try{
    await api('POST','/api/settings',{currency:sym, currency_name:name});
    sysSettings.currency      = sym;
    sysSettings.currency_name = name;
    _selectedCurrency = null;
    if(errEl) errEl.innerHTML='<div style="background:rgba(45,106,79,.15);border:1px solid rgba(45,106,79,.3);border-radius:8px;padding:10px;color:#52b788;font-size:13px;margin-bottom:10px;text-align:center;">✅ تم حفظ العملة: '+sym+'</div>';
    setTimeout(()=>{ if(errEl) errEl.innerHTML=''; },2500);
  }catch(e){
    if(errEl) errEl.innerHTML='<div class="err">'+e.message+'</div>';
  }
}

async function changeMyPassword(){
  const oldPw  = document.getElementById('pw-old')?.value||'';
  const newPw  = document.getElementById('pw-new')?.value||'';
  const confPw = document.getElementById('pw-confirm')?.value||'';
  const errEl  = document.getElementById('pw-err');
  if(!oldPw||!newPw){ if(errEl) errEl.innerHTML='<div class="err">جميع الحقول مطلوبة</div>'; return; }
  if(newPw.length<4){ if(errEl) errEl.innerHTML='<div class="err">كلمة المرور الجديدة 4 أحرف على الأقل</div>'; return; }
  if(newPw!==confPw){ if(errEl) errEl.innerHTML='<div class="err">كلمة المرور الجديدة غير متطابقة</div>'; return; }
  try{
    await api('POST','/api/auth/change-password',{old_password:oldPw, new_password:newPw});
    if(errEl) errEl.innerHTML='<div style="background:rgba(45,106,79,.15);border:1px solid rgba(45,106,79,.3);border-radius:8px;padding:10px;color:#52b788;font-size:13px;margin-bottom:10px;text-align:center;">✅ تم تغيير كلمة المرور — سيتم تسجيل الخروج</div>';
    setTimeout(()=>{ TOKEN=null; USER=null; localStorage.removeItem('token'); render(); },2000);
  }catch(e){
    if(errEl) errEl.innerHTML='<div class="err">'+e.message+'</div>';
  }
}

// ── إضافة / تعديل مستخدم ──
window.openUserForm = function(uid){
  const usr = uid ? sysUsers.find(u=>u.id===uid)||{} : {};
  MS={type:'userform', data:usr}; render();
};

window.deleteUser = async function(uid){
  const usr = sysUsers.find(u=>u.id===uid);
  if(!usr) return;
  if(!confirm(`حذف المستخدم "${usr.username}"؟`)) return;
  try{
    await api('DELETE','/api/users/'+uid);
    sysUsers = sysUsers.filter(u=>u.id!==uid);
    renderSettingsTab('users');
  }catch(e){ alert('خطأ: '+e.message); }
};

// ══════════════════════════════════════════════
//  دوال كشف الشيكات
// ══════════════════════════════════════════════

window.loadCheques = async function(){
  const dir    = document.getElementById('chq-dir')?.value    || 'all';
  const status = document.getElementById('chq-status')?.value || 'all';
  const from   = document.getElementById('chq-from')?.value   || '';
  const to     = document.getElementById('chq-to')?.value     || '';
  const resEl  = document.getElementById('chq-result');
  const btn    = document.getElementById('chq-search');

  if(resEl) resEl.innerHTML='<div style="text-align:center;padding:30px;"><div class="spin"></div></div>';
  if(btn){ btn.disabled=true; btn.textContent='⏳ جاري التحميل...'; }

  try{
    let url = `/api/reports/cheques?direction=${dir}&status=${encodeURIComponent(status)}&date_from=${from}&date_to=${to}`;
    const data = await api('GET', url);
    if(resEl) resEl.innerHTML = chequesHTML(data);
  }catch(e){
    if(resEl) resEl.innerHTML=`<div class="err">خطأ: ${e.message}</div>`;
  }finally{
    if(btn){ btn.disabled=false; btn.textContent='🔍 عرض الشيكات'; }
  }
};

function chequesHTML(d){
  const {cheques, total_outgoing, total_incoming, count, date_from, date_to} = d;

  const statusStyle = {
    'قيد التحصيل': {cls:'y', icon:'⏳'},
    'محصّل':       {cls:'g', icon:'✅'},
    'مرتجع':       {cls:'r', icon:'↩️'},
    'مؤجل':        {cls:'b', icon:'📅'},
  };

  if(!cheques.length) return `
    <div class="card" style="padding:28px;text-align:center;color:#64748b;">
      <div style="font-size:32px;margin-bottom:10px;">🔍</div>
      لا توجد شيكات في هذه الفترة أو المعايير المحددة
    </div>`;

  return `
  <!-- ملخص -->
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px;">
    <div class="stat" style="text-align:center;">
      <div style="font-size:12px;color:#64748b;">إجمالي الشيكات</div>
      <div style="font-size:20px;font-weight:800;color:#60a5fa;margin-top:5px;">${count}</div>
    </div>
    <div class="stat" style="text-align:center;">
      <div style="font-size:12px;color:#64748b;">إجمالي الصادرة</div>
      <div style="font-size:16px;font-weight:800;color:#f87171;margin-top:5px;">${total_outgoing.toLocaleString()} ${cur()}</div>
    </div>
    <div class="stat" style="text-align:center;">
      <div style="font-size:12px;color:#64748b;">إجمالي الواردة</div>
      <div style="font-size:16px;font-weight:800;color:#52b788;margin-top:5px;">${total_incoming.toLocaleString()} ${cur()}</div>
    </div>
    <div class="stat" style="text-align:center;">
      <div style="font-size:12px;color:#64748b;">الصافي</div>
      <div style="font-size:16px;font-weight:800;color:${total_incoming-total_outgoing>=0?'#52b788':'#f87171'};margin-top:5px;">
        ${(total_incoming-total_outgoing).toLocaleString()} ${cur()}
      </div>
    </div>
  </div>

  <!-- جدول الشيكات -->
  <div class="card" style="overflow:hidden;" id="chq-table-wrap">
    <div style="background:#1a1d27;padding:12px 16px;border-bottom:1px solid #1e2537;display:flex;justify-content:space-between;align-items:center;">
      <div style="font-size:14px;font-weight:800;color:#f1f5f9;">📋 تفاصيل الشيكات — ${date_from} إلى ${date_to}</div>
      <div style="display:flex;gap:8px;">
        <button class="btn s" style="padding:4px 12px;font-size:12px;" onclick="printCheques()">🖨️ طباعة</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>النوع</th>
        <th>رقم الشيك</th>
        <th>تاريخ الشيك</th>
        <th>البنك</th>
        <th>الجهة</th>
        <th>الهاتف</th>
        <th>المبلغ</th>
        <th>تاريخ الدفعة</th>
        <th>الحالة</th>
        <th>📷 صورة</th>
        <th>ملاحظات</th>
        <th>تعديل الحالة</th>
      </tr></thead>
      <tbody>
      ${cheques.map(ch => {
        const st = statusStyle[ch.cheque_status] || {cls:'b', icon:'❓'};
        const hasImg = ch.cheque_image && ch.cheque_image.startsWith('data:image');
        const safeNotes = (ch.notes||'').replace(/'/g,"'").replace(/"/g,'&quot;');
        const safeImg   = hasImg ? 'HAS_IMAGE' : '';
        return `<tr id="chq-row-${ch.id}">
          <td>
            <span class="badge ${ch.direction==='صادر'?'r':'g'}">
              ${ch.direction==='صادر'?'⬆️ صادر':'⬇️ وارد'}
            </span>
          </td>
          <td style="font-family:monospace;font-weight:800;color:#60a5fa;font-size:14px;">${ch.cheque_no}</td>
          <td style="font-weight:700;color:#f1f5f9;">${ch.cheque_date||'—'}</td>
          <td style="color:#94a3b8;">${ch.cheque_bank||'—'}</td>
          <td style="font-weight:600;color:#f1f5f9;">${ch.party_name}</td>
          <td style="font-size:12px;color:#64748b;">${ch.party_phone||'—'}</td>
          <td style="font-weight:800;color:${ch.direction==='صادر'?'#f87171':'#52b788'};font-size:14px;">
            ${ch.amount.toLocaleString()} ${cur()}
          </td>
          <td style="color:#64748b;font-size:12px;">${ch.date}</td>
          <td>
            <span class="badge ${st.cls}">${st.icon} ${ch.cheque_status}</span>
          </td>
          <td style="text-align:center;">
            ${hasImg
              ? `<img src="${ch.cheque_image}" onclick="window.open(this.src,'_blank')"
                  style="width:48px;height:36px;object-fit:cover;border-radius:4px;border:1px solid #2d3349;cursor:zoom-in;"/>`
              : `<span style="color:#334155;font-size:11px;">—</span>`}
          </td>
          <td style="font-size:12px;color:#64748b;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${safeNotes}">${ch.notes||'—'}</td>
          <td>
            <button class="btn s" style="padding:3px 8px;font-size:11px;white-space:nowrap;"
              onclick="chqOpenUpdate(${ch.id})">
              ✏️ تحديث
            </button>
          </td>
        </tr>`;
      }).join('')}
      </tbody>
    </table>
    <!-- إجمالي الحالات -->
    <div style="display:flex;gap:10px;padding:12px 16px;border-top:1px solid #1e2537;flex-wrap:wrap;">
      ${['قيد التحصيل','محصّل','مرتجع','مؤجل'].map(s=>{
        const grp = cheques.filter(c=>c.cheque_status===s);
        if(!grp.length) return '';
        const st = statusStyle[s]||{cls:'b',icon:'❓'};
        return `<div class="stat" style="padding:8px 14px;flex:1;min-width:140px;text-align:center;">
          <div style="font-size:11px;color:#64748b;">${st.icon} ${s}</div>
          <div style="font-size:14px;font-weight:800;margin-top:3px;">${grp.length} شيك</div>
          <div style="font-size:12px;color:#94a3b8;">${grp.reduce((t,c)=>t+c.amount,0).toLocaleString()} ${cur()}</div>
        </div>`;
      }).join('')}
    </div>
  </div>`;
}

// مودال تحديث حالة الشيك
window.openChequeStatus = function(id, currentStatus, currentNotes, currentImage){
  window._cstDeleteImage = false;
  MS = {type:'chequeStatus', data:{id, currentStatus, currentNotes, currentImage: currentImage||''}};
  render();
};

// جلب بيانات الشيك كاملة ثم فتح مودال التحديث
window.chqOpenUpdate = async function(id){
  try{
    // نجلب الدفعة من السيرفر للحصول على الصورة الكاملة
    const pays = await api('GET', '/api/payments?ref_id=0&ref_type=_all_');
    // نبحث في قائمة آخر 100 دفعة
    let ch = null;
    try{
      const all = await api('GET','/api/payments');
      ch = all.find(p=>p.id===id);
    }catch(e){}
    if(ch){
      openChequeStatus(id, ch.cheque_status||'قيد التحصيل', ch.notes||'', ch.cheque_image||'');
    } else {
      openChequeStatus(id, '', '', '');
    }
  }catch(e){
    openChequeStatus(id, '', '', '');
  }
};

window.printCheques = function(){
  const el = document.getElementById('chq-table-wrap');
  if(!el) return;
  const w = window.open('','_blank','width=1000,height=700');
  w.document.write(`<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8">
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;800&display=swap" rel="stylesheet">
  <style>*{font-family:'Tajawal',sans-serif;box-sizing:border-box}body{padding:20px;color:#111;direction:rtl}
  table{width:100%;border-collapse:collapse}th{background:#e8f5e9;padding:7px 9px;text-align:right;border:1px solid #aaa;font-size:12px}
  td{padding:6px 8px;border:1px solid #ddd;font-size:12px}
  @page{size:A4 landscape;margin:10mm}</style></head>
  <body onload="window.print()">${el.innerHTML}</body></html>`);
  w.document.close();
};

// ══════════════════════════════════════════════
//  دوال النسخ الاحتياطي
// ══════════════════════════════════════════════

// عرض رسالة في قسم النسخ الاحتياطي
function bkMsg(html, type='info'){
  const el = document.getElementById('bk-msg');
  if(!el) return;
  const colors = {
    ok:   'background:rgba(45,106,79,.15);border:1px solid rgba(45,106,79,.3);color:#52b788;',
    err:  'background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#f87171;',
    info: 'background:rgba(96,165,250,.1);border:1px solid rgba(96,165,250,.3);color:#60a5fa;',
  };
  el.innerHTML=`<div style="${colors[type]||colors.info}border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:14px;">${html}</div>`;
  if(type==='ok') setTimeout(()=>{ if(el) el.innerHTML=''; }, 4000);
}

// تحميل قائمة النسخ من السيرفر
window.bkLoadList = async function(){
  const el = document.getElementById('bk-list');
  if(!el) return;
  el.innerHTML='<div style="text-align:center;padding:30px;"><div class="spin"></div></div>';
  try{
    const data = await api('GET','/api/backup');
    const list = data.backups||[];
    if(!list.length){
      el.innerHTML='<div style="text-align:center;padding:28px;color:#64748b;font-size:13px;">لا توجد نسخ احتياطية محفوظة بعد</div>';
      return;
    }
    el.innerHTML=`
    <table>
      <thead><tr>
        <th>اسم الملف</th><th>التاريخ</th><th>الحجم</th><th>إجراءات</th>
      </tr></thead>
      <tbody>
      ${list.map((b,i)=>`<tr>
        <td style="font-family:monospace;font-size:12px;color:#60a5fa;">${b.name}</td>
        <td style="color:#94a3b8;font-size:13px;">${b.date}</td>
        <td><span class="badge b">${b.size_kb} KB</span></td>
        <td><div style="display:flex;gap:6px;">
          <button class="btn p" style="padding:4px 10px;font-size:12px;background:linear-gradient(135deg,#1e40af,#1e3a8a);"
            onclick="bkDownloadSaved('${b.name}')">⬇️ تنزيل</button>
          <button class="btn p" style="padding:4px 10px;font-size:12px;background:linear-gradient(135deg,#b45309,#92400e);"
            onclick="bkRestoreSaved('${b.name}')">↩️ استعادة</button>
          <button class="btn d" style="padding:4px 10px;font-size:12px;"
            onclick="bkDelete('${b.name}')">🗑️</button>
        </div></td>
      </tr>`).join('')}
      </tbody>
    </table>
    <div style="padding:10px 16px;font-size:12px;color:#475569;border-top:1px solid #1e2537;">
      📁 مسار الحفظ: ${data.backup_dir||'—'} &nbsp;|&nbsp; إجمالي النسخ: ${list.length}
    </div>`;
  }catch(e){
    el.innerHTML=`<div style="text-align:center;padding:20px;color:#f87171;font-size:13px;">خطأ: ${e.message}</div>`;
  }
};

// إنشاء نسخة احتياطية جديدة + تنزيلها تلقائياً
window.bkCreate = async function(){
  const btn = document.getElementById('bk-create');
  if(btn){ btn.disabled=true; btn.textContent='⏳ جاري الإنشاء...'; }
  bkMsg('⏳ جاري إنشاء النسخة الاحتياطية...','info');
  try{
    const data = await api('POST','/api/backup');
    // تنزيل تلقائي
    bkDownloadBase64(data.data, data.name);
    bkMsg(`✅ تم إنشاء النسخة وتنزيلها: <strong>${data.name}</strong> — الحجم: ${data.size_kb} KB`,'ok');
    // تحديث القائمة
    await bkLoadList();
  }catch(e){
    bkMsg('❌ خطأ: '+e.message,'err');
  }finally{
    if(btn){ btn.disabled=false; btn.textContent='📦 إنشاء نسخة احتياطية الآن'; }
  }
};

// تنزيل نسخة محفوظة على السيرفر
window.bkDownloadSaved = async function(name){
  bkMsg('⏳ جاري تجهيز الملف للتنزيل...','info');
  try{
    // نطلب من السيرفر إرسال النسخة كـ base64
    const data = await api('POST','/api/backup',{download:name});
    bkDownloadBase64(data.data, data.name);
    bkMsg(`✅ تم تنزيل: <strong>${name}</strong>`,'ok');
  }catch(e){
    bkMsg('❌ خطأ في التنزيل: '+e.message,'err');
  }
};

// تحويل base64 → تنزيل ملف في المتصفح
function bkDownloadBase64(b64, filename){
  const bin  = atob(b64);
  const arr  = new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
  const blob = new Blob([arr],{type:'application/octet-stream'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href=url; a.download=filename; a.click();
  setTimeout(()=>URL.revokeObjectURL(url),2000);
}

// استعادة من ملف مرفوع
window.bkRestoreFile = async function(input){
  const file = input.files[0];
  if(!file) return;
  if(!file.name.endsWith('.db')){
    bkMsg('❌ يجب اختيار ملف بامتداد .db','err'); return;
  }
  if(!confirm(`⚠️ سيتم استبدال قاعدة البيانات الحالية بالكامل بملف:\n"${file.name}"\n\nسيتم إنشاء نسخة احتياطية تلقائية قبل الاستعادة.\n\nهل تريد المتابعة؟`)) return;
  bkMsg('⏳ جاري قراءة الملف والاستعادة...','info');
  try{
    const b64 = await new Promise((res,rej)=>{
      const r=new FileReader();
      r.onload=e=>res(e.target.result.split(',')[1]);
      r.onerror=rej;
      r.readAsDataURL(file);
    });
    const result = await api('POST','/api/restore',{data:b64});
    bkMsg(`✅ تمت الاستعادة بنجاح! تم حفظ نسخة احتياطية تلقائية: <strong>${result.auto_backup}</strong><br/>
      <span style="color:#fbbf24;">⚠️ سيتم إعادة تحميل الصفحة خلال 3 ثوانٍ...</span>`,'ok');
    setTimeout(()=>location.reload(),3000);
  }catch(e){
    bkMsg('❌ خطأ في الاستعادة: '+e.message,'err');
  }finally{
    input.value='';
  }
};

// استعادة من نسخة محفوظة على السيرفر
window.bkRestoreSaved = async function(name){
  if(!confirm(`⚠️ سيتم استعادة قاعدة البيانات من النسخة:\n"${name}"\n\nسيتم إنشاء نسخة احتياطية تلقائية من الوضع الحالي قبل الاستعادة.\n\nهل تريد المتابعة؟`)) return;
  bkMsg('⏳ جاري الاستعادة...','info');
  try{
    const result = await api('POST','/api/restore',{name});
    bkMsg(`✅ تمت الاستعادة من: <strong>${name}</strong><br/>نسخة احتياطية تلقائية: <strong>${result.auto_backup}</strong><br/>
      <span style="color:#fbbf24;">⚠️ سيتم إعادة تحميل الصفحة خلال 3 ثوانٍ...</span>`,'ok');
    setTimeout(()=>location.reload(),3000);
  }catch(e){
    bkMsg('❌ خطأ في الاستعادة: '+e.message,'err');
  }
};

// حذف نسخة من السيرفر
window.bkDelete = async function(name){
  if(!confirm(`حذف النسخة الاحتياطية:\n"${name}"؟`)) return;
  try{
    await api('DELETE','/api/backup/'+encodeURIComponent(name));
    bkMsg(`🗑️ تم حذف: ${name}`,'ok');
    await bkLoadList();
  }catch(e){
    bkMsg('❌ خطأ: '+e.message,'err');
  }
};

// ══════════════════════════════════════════════
//  دفعة على الحساب الكلي
// ══════════════════════════════════════════════

window.openAccountPay = async function(entityType, id, name){
  const party_type = entityType==='suppliers' ? 'supplier' : 'customer';
  // جلب ملخص الحساب
  let summary = null;
  try{
    summary = await api('GET', `/api/payments_summary?party_type=${party_type}&party_id=${id}`);
  }catch(e){ alert('خطأ: '+e.message); return; }
  MS = {type:'accountpay', data:{
    party_type, party_id: id, name,
    total_invoices:  summary.total_invoices  || 0,
    total_paid:      summary.total_paid      || 0,
    total_remaining: summary.total_remaining || 0,
    invoices:        summary.invoices        || []
  }};
  render();
};

function accountPayModal(d){
  const today = new Date().toISOString().slice(0,10);
  const isSupplier = d.party_type === 'supplier';

  return `<div class="overlay" id="mover"><div class="modal" style="max-width:580px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
    <div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;">💳 دفعة على حساب ${d.name}</div>
      <div style="font-size:12px;color:#64748b;margin-top:2px;">${isSupplier?'مورد':'زبون'} — تُخصَم من إجمالي الحساب مباشرة</div>
    </div>
    <button class="btn s" style="padding:4px 9px;" id="mc">✕</button>
  </div>

  <!-- ملخص الحساب -->
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px;">
    <div class="stat" style="text-align:center;">
      <div style="font-size:11px;color:#64748b;">إجمالي الفواتير</div>
      <div style="font-size:16px;font-weight:800;color:#f1f5f9;margin-top:4px;">${(d.total_invoices||0).toLocaleString()} ${cur()}</div>
    </div>
    <div class="stat" style="text-align:center;">
      <div style="font-size:11px;color:#64748b;">إجمالي المدفوع</div>
      <div style="font-size:16px;font-weight:800;color:#52b788;margin-top:4px;">${(d.total_paid||0).toLocaleString()} ${cur()}</div>
    </div>
    <div class="stat" style="text-align:center;">
      <div style="font-size:11px;color:#64748b;">المتبقي</div>
      <div style="font-size:16px;font-weight:800;color:${(d.total_remaining||0)>0?'#f87171':'#52b788'};margin-top:4px;">${(d.total_remaining||0).toLocaleString()} ${cur()}</div>
    </div>
  </div>

  <div style="background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.2);border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:#94a3b8;">
    ℹ️ هذه الدفعة تُسجَّل على الحساب الكلي وتُخصَم من إجمالي المتبقي، دون ربطها بفاتورة محددة أو تغيير حالة أي فاتورة.
  </div>

  <!-- بيانات الدفعة -->
  <div id="merr"></div>
  <div class="g2" style="margin-bottom:12px;">
    <div><label class="lbl">المبلغ <span style="color:#f87171;">*</span></label>
      <input class="inp" type="number" id="ap-amount" min="0.01" step="0.01"
        value="${(d.total_remaining||0).toFixed(2)}" style="font-size:16px;font-weight:700;color:#52b788;"/>
      <div style="margin-top:4px;display:flex;gap:6px;">
        <button class="btn s" style="font-size:11px;padding:3px 8px;" onclick="document.getElementById('ap-amount').value='${(d.total_remaining||0).toFixed(2)}'">الكل</button>
      </div>
    </div>
    <div><label class="lbl">طريقة الدفع <span style="color:#f87171;">*</span></label>
      <select class="inp" id="ap-method" onchange="apToggleCheque(this.value)">
        <option value="نقدي">💵 نقدي</option>
        <option value="شيك">🏦 شيك</option>
        <option value="تحويل بنكي">🔄 تحويل بنكي</option>
        <option value="بطاقة">💳 بطاقة</option>
      </select>
    </div>
    <div><label class="lbl">التاريخ <span style="color:#f87171;">*</span></label>
      <input class="inp" type="date" id="ap-date" value="${today}"/>
    </div>
    <div><label class="lbl">ملاحظات</label>
      <input class="inp" id="ap-notes" placeholder="ملاحظات اختيارية..."/>
    </div>
  </div>

  <!-- حقول الشيك -->
  <div id="ap-cheque-fields" style="display:none;background:#1a1d27;border-radius:8px;padding:12px;margin-bottom:12px;">
    <div style="font-size:12px;font-weight:700;color:#60a5fa;margin-bottom:8px;">🏦 بيانات الشيك</div>
    <div class="g2">
      <div><label class="lbl">رقم الشيك</label><input class="inp" id="ap-cheque-no" placeholder="رقم الشيك..."/></div>
      <div><label class="lbl">تاريخ الشيك</label><input class="inp" type="date" id="ap-cheque-date" value="${today}"/></div>
      <div style="grid-column:span 2"><label class="lbl">اسم البنك</label><input class="inp" id="ap-cheque-bank" placeholder="اسم البنك..."/></div>
    </div>
    <div style="margin-top:12px;">
      <label class="lbl">📷 صورة الشيك</label>
      <div id="ap-img-wrap" style="margin-top:6px;">
        <label id="ap-upload-btn" style="display:flex;align-items:center;gap:10px;background:#161923;border:2px dashed #2d3349;border-radius:8px;padding:12px 16px;cursor:pointer;transition:border .2s;" onmouseover="this.style.borderColor='#2d6a4f'" onmouseout="this.style.borderColor='#2d3349'">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          <div><div style="font-size:13px;font-weight:600;color:#94a3b8;">اضغط لرفع صورة الشيك</div>
          <div style="font-size:11px;color:#475569;margin-top:2px;">JPG, PNG, WEBP — حتى 5MB</div></div>
          <input type="file" id="ap-cheque-img" accept="image/*" style="display:none;" onchange="apPreviewImg(this)"/>
        </label>
        <div id="ap-img-preview" style="display:none;margin-top:8px;position:relative;">
          <img id="ap-img-tag" style="width:100%;max-height:200px;object-fit:contain;border-radius:8px;border:1px solid #2d3349;background:#0f1018;"/>
          <button onclick="apRemoveImg()" style="position:absolute;top:6px;left:6px;background:#3d1515;border:none;color:#f87171;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:12px;">✕ حذف</button>
        </div>
      </div>
    </div>
  </div>

  <div style="display:flex;gap:10px;">
    <button class="btn p" id="ms" style="flex:1;justify-content:center;height:44px;font-size:15px;">
      💾 تسجيل الدفعة
    </button>
    <button class="btn s" id="mc2">إلغاء</button>
  </div>
  </div></div>`;
}

window.apToggleCheque = function(val){
  const el = document.getElementById('ap-cheque-fields');
  if(el) el.style.display = val==='شيك' ? 'block' : 'none';
};

// معاينة صورة الشيك في مودال دفعة الحساب الكلي
window.apPreviewImg = function(input){
  const file = input.files[0];
  if(!file) return;
  if(file.size > 5*1024*1024){ alert('الصورة أكبر من 5MB'); input.value=''; return; }
  const reader = new FileReader();
  reader.onload = function(e){
    const tag  = document.getElementById('ap-img-tag');
    const prev = document.getElementById('ap-img-preview');
    if(tag)  tag.src = e.target.result;
    if(prev) prev.style.display = 'block';
    const btn = document.getElementById('ap-upload-btn');
    if(btn) btn.style.display = 'none';
  };
  reader.readAsDataURL(file);
};

window.apRemoveImg = function(){
  const inp  = document.getElementById('ap-cheque-img');
  const tag  = document.getElementById('ap-img-tag');
  const prev = document.getElementById('ap-img-preview');
  const btn  = document.getElementById('ap-upload-btn');
  if(inp)  inp.value = '';
  if(tag)  tag.src = '';
  if(prev) prev.style.display = 'none';
  if(btn)  btn.style.display = 'flex';
};
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
            self.send_header("Cache-Control","no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma","no-cache")
            self.send_header("Expires","0")
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
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"✅ Server running on port {PORT}")
    print(f"📁 Database: {DB_PATH}")
    print(f"⚠️  Note: On Railway, data resets on each deploy unless using a volume")
    
    def shutdown(sig, frame):
        print("\n⛔ Shutting down...")
        server.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    
    server.serve_forever()

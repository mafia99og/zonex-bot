# main.py — ZONE X v5 (Profile + Wallet + AddBalance + Tickets + MyOrders)
import os, asyncio, aiosqlite, json, uuid, httpx, hmac, hashlib
from datetime import datetime, timezone
from typing import Dict, Optional, Any

from dotenv import load_dotenv
load_dotenv()

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH   = os.getenv("DB_PATH", "zonex.db")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS","7697204672").split(",") if x.strip()}

NOWPAYMENTS_API_KEY     = os.getenv("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET  = os.getenv("NOWPAYMENTS_IPN_SECRET", "")
NOWPAYMENTS_SANDBOX     = os.getenv("NOWPAYMENTS_SANDBOX","true").lower() in ("1","true","yes")
NOW_BASE = "https://api-sandbox.nowpayments.io/v1" if NOWPAYMENTS_SANDBOX else "https://api.nowpayments.io/v1"
NOW_IPN_ENDPOINT_PUBLIC = os.getenv("NOW_IPN_ENDPOINT_PUBLIC","https://zonex-bot.onrender.com/nowpayments_webhook")

# ================== DB ==================
INIT_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  username TEXT,
  city TEXT,
  first_seen TEXT,
  ref_by INTEGER,
  balance REAL DEFAULT 0,
  referrals_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products(
  id TEXT PRIMARY KEY,
  name TEXT,
  alias TEXT,
  price REAL,
  stock INTEGER,
  description TEXT
);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY,
  user_id INTEGER,
  items_json TEXT,
  amount REAL,
  status TEXT,
  invoice_id TEXT,
  payment_url TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  product_id TEXT,
  rating INTEGER,
  text TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  title TEXT,
  body TEXT,
  status TEXT,
  assigned_to INTEGER,
  created_at TEXT
);
"""

PRODUCTS = [
  ("apl001","Măr","weedulescu",1.50,40,"Mere crocante."),
  ("ban001","Banane","coxoleanu",2.40,30,"Banane bio."),
  ("cps001","Căpșună","3cemecescu",3.00,50,"Căpșuni aromate."),
  ("mnk001","Mango Kent","coxoleanu",4.50,20,"Mango dulce, copt."),
  ("pep001","Pepene","madalina",5.50,15,"Pepene roșu mare."),
  ("per001","Pere","ketaminescu",2.20,30,"Pere zemoase."),
  ("str001","Struguri","bobitele",2.80,35,"Struguri dulci.")
]

REVIEWS = [
  ("General","⭐⭐⭐⭐⭐ Gust fin, calitate top. Recomand!"),
  ("General","⭐⭐⭐⭐⭐ Ambalaj discret, livrare rapidă."),
  ("General","⭐⭐⭐⭐⭐ Produsele sunt bine ascunse și proaspete."),
  ("Cluj","⭐⭐⭐⭐⭐ Cluj — rapid și discret, aroma e exactă."),
  ("Constanța","⭐⭐⭐⭐⭐ Constanța — ambalaj perfect, mulțumesc!"),
  ("General","⭐⭐⭐⭐⭐ Aroma intensă, o surpriză plăcută."),
  ("Ploiești","⭐⭐⭐⭐⭐ Ploiești — sosit curat, 5/5."),
  ("General","⭐⭐⭐⭐⭐ Cantitate bună, calitate premium."),
  ("Brașov","⭐⭐⭐⭐⭐ Brașov — gust excelent și comunicare ok."),
  ("General","⭐⭐⭐⭐⭐ Totul discret și foarte bine pus."),
  ("Galați","⭐⭐⭐⭐⭐ Galați — impresionant calitatea."),
  ("General","⭐⭐⭐⭐⭐ Rapid, discreet și gustos."),
  ("Craiova","⭐⭐⭐⭐⭐ Craiova — recomandă!"),
  ("Alexandria","⭐⭐⭐⭐⭐ Alexandria — prezentare impecabilă."),
  ("Călărași","⭐⭐⭐⭐⭐ Călărași — a meritat așteptarea."),
  ("General","⭐⭐⭐⭐⭐ Perfect ambalat, gust autentic."),
  ("Cluj","⭐⭐⭐⭐⭐ Cluj — excelent raport calitate/preț."),
  ("General","⭐⭐⭐⭐⭐ Merită toți banii, recomand sincer."),
  ("Brăila","⭐⭐⭐⭐⭐ Brăila — totul ok."),
  ("General","⭐⭐⭐⭐⭐ Experiență de top, mulțumesc!")
]

CART: Dict[int, Dict[str,int]] = {}

def money(x: float) -> str: return f"{x:.2f} EUR"
def now() -> str: return datetime.now(timezone.utc).isoformat()

async def db():
    con = await aiosqlite.connect(DB_PATH)
    con.row_factory = aiosqlite.Row
    return con

async def init_db():
    con = await db()
    for stmt in [s.strip() for s in INIT_SQL.split(";") if s.strip()]:
        await con.execute(stmt)
    cur = await con.execute("SELECT COUNT(*) c FROM products"); c = (await cur.fetchone())["c"]
    if c == 0:
        await con.executemany("INSERT INTO products(id,name,alias,price,stock,description) VALUES(?,?,?,?,?,?)", PRODUCTS)
    cur = await con.execute("SELECT COUNT(*) c FROM reviews"); c = (await cur.fetchone())["c"]
    if c == 0:
        for city, text in REVIEWS:
            await con.execute("INSERT INTO reviews(user_id,product_id,rating,text,created_at) VALUES(?,?,?,?,?)",
                              (0, "", 5, text, now()))
    await con.commit(); await con.close()

async def ensure_user(u, ref: Optional[int] = None):
    con = await db()
    await con.execute("""INSERT OR IGNORE INTO users(user_id,username,first_seen,ref_by,balance,referrals_count)
                         VALUES(?,?,?,?,0,0)""", (u.id, u.username or "", now(), ref))
    if ref and ref != u.id:
        await con.execute("UPDATE users SET referrals_count = referrals_count + 1, balance = balance + 1 WHERE user_id=?",(ref,))
    await con.commit(); await con.close()

async def typing(chat_id:int, context:ContextTypes.DEFAULT_TYPE, sec:float=0.2):
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(sec)
    except Exception:
        pass

# ================== NOWPAYMENTS ==================
async def create_invoice(order_id: str, amount_eur: float, description: str) -> dict:
    url = f"{NOW_BASE}/invoice"
    headers = {"x-api-key": NOWPAYMENTS_API_KEY, "Content-Type":"application/json"}
    payload = {
        "price_amount": round(amount_eur,2),
        "price_currency": "eur",
        "order_id": order_id,
        "order_description": description,
        "ipn_callback_url": NOW_IPN_ENDPOINT_PUBLIC
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        # dacă e 403, arătăm mesaj clar
        if r.status_code == 403:
            raise RuntimeError("NOWPayments a respins cheia (403). Verifică: Sandbox key + IPN URL + IPN secret.")
        r.raise_for_status()
        return r.json()

# ================== UI TEXTS ==================
def welcome_text(u):
    return (
        "🟩 <b>ZONE X – Exotic Fruits (v5)</b>\n"
        f"Bun venit, {u.full_name}!\n\n"
        "🔗 <b>Linkuri utile:</b>\n"
        "• Main: <a href='https://t.me/zonexhub'>link</a>\n"
        "• Support: <a href='https://t.me/zonex_supportteam'>link</a>\n\n"
        "💡 /menu pentru produse, /profile pentru profil complet."
    )

# ================== HANDLERS ==================
async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ref = None
    if update.message and update.message.text and "start=ref_" in update.message.text:
        try: ref = int(update.message.text.split("start=ref_")[1])
        except: pass
    await ensure_user(u, ref)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Vezi produsele", callback_data="p:open"),
         InlineKeyboardButton("👤 Profile", callback_data="profile:open")]
    ])
    await typing(update.effective_chat.id, context)
    await update.message.reply_text(welcome_text(u), parse_mode=ParseMode.HTML, reply_markup=kb)

async def menu_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await open_products(update.effective_message, context)

async def open_products(msg, context):
    con = await db()
    cur = await con.execute("SELECT * FROM products ORDER BY name")
    items = await cur.fetchall(); await con.close()
    rows = []
    for r in items:
        rows.append([InlineKeyboardButton(f"{r['name']} ({r['alias']}) — {money(r['price'])} — stoc {r['stock']}",
                                          callback_data=f"p:add:{r['id']}")])
    rows.append([InlineKeyboardButton("🧺 Coș", callback_data="cart:open"),
                 InlineKeyboardButton("⬅️ Înapoi", callback_data="home")])
    await msg.reply_text("🛒 <b>Produse disponibile:</b>", parse_mode=ParseMode.HTML,
                         reply_markup=InlineKeyboardMarkup(rows))

def cart_summary(uid:int):
    c = CART.get(uid,{})
    if not c: return "🧺 Coșul este gol."
    lines = ["🧺 <b>Coșul tău:</b>"]
    for pid, qty in c.items(): lines.append(f"• <code>{pid}</code> x{qty}")
    return "\n".join(lines)

async def profile_open(msg, context, uid:int):
    con = await db()
    cur = await con.execute("SELECT balance, referrals_count, city FROM users WHERE user_id=?", (uid,))
    u = await cur.fetchone(); await con.close()
    me = await context.bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{uid}"
    text = (
        "👤 <b>Profil</b>\n"
        f"• City: <b>{u['city'] or '-'}</b>\n"
        f"• Balance: <b>{u['balance']:.2f}</b> puncte\n"
        f"• Referrals: <b>{u['referrals_count']}</b>\n\n"
        f"🎯 Referral link:\n<code>{ref_link}</code>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Add balance", callback_data="wallet:add")],
        [InlineKeyboardButton("🧾 My orders", callback_data="orders:mine")],
        [InlineKeyboardButton("🎟️ Tickets", callback_data="tickets:open")],
        [InlineKeyboardButton("⬅️ Înapoi", callback_data="home")]
    ])
    await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def wallet_add(q, context):
    # facem o „comandă” de top-up (order special)
    uid = q.from_user.id
    amount = 5.0  # top-up fix (poți schimba; sau poți cere user-ului o sumă)
    order_id = "TOPUP_" + uuid.uuid4().hex[:10]
    con = await db()
    await con.execute("INSERT INTO orders(id,user_id,items_json,amount,status,created_at) VALUES(?,?,?,?,?,?)",
                      (order_id, uid, json.dumps([("balance_topup","",1,amount)]), amount, "pending", now()))
    await con.commit()
    try:
        inv = await create_invoice(order_id, amount, f"ZoneX top-up {order_id}")
        inv_id = inv.get("id") or inv.get("invoice_id") or inv.get("data",{}).get("id")
        url = inv.get("invoice_url") or inv.get("payment_url") or inv.get("url") or inv.get("data",{}).get("invoice_url")
        await con.execute("UPDATE orders SET invoice_id=?, payment_url=? WHERE id=?", (inv_id, url, order_id))
        await con.commit(); await con.close()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Plătește top-up", url=url)],
                                   [InlineKeyboardButton("🧾 My orders", callback_data="orders:mine")]])
        await q.message.reply_text(
            f"💰 <b>Add balance</b>\nSuma: <b>{money(amount)}</b>\n\nLink plată:\n{url}",
            parse_mode=ParseMode.HTML, reply_markup=kb
        )
    except Exception as e:
        await con.execute("UPDATE orders SET status='error' WHERE id=?", (order_id,))
        await con.commit(); await con.close()
        await q.message.reply_text(f"❌ Eroare la creare factură: {e}")

async def orders_mine(msg, uid:int):
    con = await db()
    cur = await con.execute("SELECT id, amount, status, created_at FROM orders WHERE user_id=? ORDER BY datetime(created_at) DESC LIMIT 10", (uid,))
    rows = await cur.fetchall(); await con.close()
    if not rows:
        await msg.reply_text("🧾 Nu ai comenzi încă.")
        return
    lines = ["🧾 <b>Ultimele tale comenzi</b>"]
    for r in rows:
        lines.append(f"• <code>{r['id']}</code> — {money(r['amount'])} — <b>{r['status']}</b> — {r['created_at'][:19]}")
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

# Tickets – very simple flow: list/create
USER_NEW_TICKET: Dict[int, Dict[str,str]] = {}

async def tickets_open(msg, uid:int):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Create ticket", callback_data="tickets:new")],
        [InlineKeyboardButton("📋 My tickets", callback_data="tickets:list")]
    ])
    await msg.reply_text("🎟️ <b>Tickets</b> — creează sau vizualizează.", parse_mode=ParseMode.HTML, reply_markup=kb)

async def tickets_new_start(q):
    USER_NEW_TICKET[q.from_user.id] = {"stage":"title"}
    await q.message.reply_text("📝 Trimite <b>titlul</b> ticket-ului:", parse_mode=ParseMode.HTML)

async def tickets_list(msg, uid:int):
    con = await db()
    cur = await con.execute("SELECT id,title,status,created_at FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = await cur.fetchall(); await con.close()
    if not rows:
        await msg.reply_text("📋 Nu ai tickets încă.")
        return
    lines = ["📋 <b>Tickets</b>"]
    for r in rows:
        lines.append(f"• #{r['id']} — <b>{r['title']}</b> — <code>{r['status']}</code> — {r['created_at'][:19]}")
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def on_message(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in USER_NEW_TICKET:
        st = USER_NEW_TICKET[uid]
        if st["stage"] == "title":
            st["title"] = update.message.text[:100]
            st["stage"] = "body"
            await update.message.reply_text("✍️ Acum trimite <b>descrierea</b> (poți adăuga link imgur dacă ai poză).", parse_mode=ParseMode.HTML)
            return
        if st["stage"] == "body":
            st["body"] = update.message.text[:2000]
            con = await db()
            await con.execute("INSERT INTO tickets(user_id,title,body,status,assigned_to,created_at) VALUES(?,?,?,?,?,?)",
                              (uid, st["title"], st["body"], "open", None, now()))
            await con.commit(); await con.close()
            USER_NEW_TICKET.pop(uid, None)
            await update.message.reply_text("✅ Ticket creat. Un admin te va contacta aici.")
            # notificăm adminii
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(aid, f"🆕 Ticket nou de la {uid}\nTitlu: {st['title']}\nBody:\n{st['body']}")
                except: pass

# ================== CALLBACKS ==================
async def on_cb(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "home":
        await q.message.reply_text("🏠 Home. /menu sau /profile")
        return

    if data == "p:open":
        await open_products(q.message, context); return

    if data.startswith("p:add:"):
        pid = data.split(":")[2]
        c = CART.setdefault(q.from_user.id,{})
        c[pid] = c.get(pid,0)+1
        await q.message.reply_text("➕ Adăugat în coș.")
        return

    if data == "cart:open":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Checkout (total & plată)", callback_data="cart:checkout")],
            [InlineKeyboardButton("⬅️ Înapoi", callback_data="p:open")]
        ])
        await q.message.reply_text(cart_summary(q.from_user.id), parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "cart:checkout":
        uid = q.from_user.id
        c = CART.get(uid,{})
        if not c:
            await q.message.reply_text("Coșul e gol."); return
        con = await db()
        total = 0.0; detail = []
        for pid, qty in c.items():
            cur = await con.execute("SELECT id,name,price,stock FROM products WHERE id=?", (pid,))
            r = await cur.fetchone()
            if not r: await q.message.reply_text(f"Produsul {pid} nu există."); await con.close(); return
            if r["stock"] < qty: await q.message.reply_text(f"Stoc insuficient pentru {r['name']} (disponibil {r['stock']})."); await con.close(); return
            total += r["price"]*qty; detail.append((r["id"], r["name"], qty, r["price"]))
        order_id = uuid.uuid4().hex[:12]
        await con.execute("INSERT INTO orders(id,user_id,items_json,amount,status,created_at) VALUES(?,?,?,?,?,?)",
                          (order_id, uid, json.dumps(detail), total, "pending", now()))
        await con.commit()
        try:
            inv = await create_invoice(order_id, total, f"Order {order_id} - ZONEX")
            inv_id = inv.get("id") or inv.get("invoice_id") or inv.get("data",{}).get("id")
            url = inv.get("invoice_url") or inv.get("payment_url") or inv.get("url") or inv.get("data",{}).get("invoice_url")
            await con.execute("UPDATE orders SET invoice_id=?, payment_url=? WHERE id=?", (inv_id, url, order_id))
            await con.commit(); await con.close()
            CART[uid] = {}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Plătește acum", url=url)],
                                       [InlineKeyboardButton("🧾 My orders", callback_data="orders:mine")]])
            await q.message.reply_text(
                f"🧾 Comanda <code>{order_id}</code>\nTotal: <b>{money(total)}</b>\n\nLink plată:\n{url}",
                parse_mode=ParseMode.HTML, reply_markup=kb
            )
        except Exception as e:
            await con.execute("UPDATE orders SET status='error' WHERE id=?", (order_id,))
            await con.commit(); await con.close()
            await q.message.reply_text(f"❌ Eroare la creare factură: {e}")
        return

    if data == "profile:open":
        await profile_open(q.message, context, q.from_user.id); return

    if data == "wallet:add":
        await wallet_add(q, context); return

    if data == "orders:mine":
        await orders_mine(q.message, q.from_user.id); return

    if data == "tickets:open":
        await tickets_open(q.message, q.from_user.id); return
    if data == "tickets:new":
        await tickets_new_start(q); return
    if data == "tickets:list":
        await tickets_list(q.message, q.from_user.id); return

# ================== COMMANDS ==================
async def profile_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await profile_open(update.effective_message, context, update.effective_user.id)

async def wallet_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    # redirecționez către profile (acolo e și add balance)
    await profile_open(update.effective_message, context, update.effective_user.id)

async def markpaid_cmd(update:Update, context:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("Nu ai drepturi.")
    if not context.args: return await update.message.reply_text("Usage: /markpaid <order_id>")
    oid = context.args[0].strip()
    con = await db()
    cur = await con.execute("SELECT user_id, amount, status FROM orders WHERE id=?", (oid,))
    row = await cur.fetchone()
    if not row: await update.message.reply_text("Comanda nu există."); await con.close(); return
    await con.execute("UPDATE orders SET status='paid' WHERE id=?", (oid,))
    # opțional: adaugă puncte când se plătește top-up
    if oid.startswith("TOPUP_"):
        await con.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (row["amount"], row["user_id"]))
    await con.commit(); await con.close()
    try:
        await context.bot.send_message(row["user_id"], f"✅ Plata pentru <code>{oid}</code> confirmată. Mulțumim!", parse_mode=ParseMode.HTML)
    except: pass
    await update.message.reply_text("✅ Marcat ca paid.")

# ================== APP ==================
async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN lipsă.")
    await init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("wallet", wallet_cmd))
    app.add_handler(CommandHandler("markpaid", markpaid_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    await app.bot.set_my_commands([
        BotCommand("start","Pornește botul"),
        BotCommand("menu","Vezi produsele"),
        BotCommand("profile","Profil / Wallet / Orders / Tickets"),
        BotCommand("wallet","Portofel & Add balance"),
    ])
    print("ZONE X bot v5 online.")
    await app.run_polling()

if __name__ == "__main__":
    import platform, nest_asyncio
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    nest_asyncio.apply()
    asyncio.run(main())

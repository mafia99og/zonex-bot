# webhook_nowpayments.py
import os, json, aiosqlite, hmac, hashlib, asyncio
from fastapi import FastAPI, Request, Header, HTTPException
from telegram import Bot
from dotenv import load_dotenv
load_dotenv()

app = FastAPI()
IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET","")
DB_PATH = os.getenv("DB_PATH","zonex.db")
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(BOT_TOKEN)

def verify_nowpayments_signature(body_bytes: bytes, header_sig: str) -> bool:
    if not IPN_SECRET:
        return False
    try:
        body_json = json.loads(body_bytes)
    except Exception:
        return False
    ordered = {k: body_json[k] for k in sorted(body_json.keys())}
    ordered_str = json.dumps(ordered, separators=(',', ':'), ensure_ascii=False)
    computed = hmac.new(IPN_SECRET.encode(), ordered_str.encode('utf-8'), hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, header_sig)

async def mark_order_paid_in_db(order_id: str):
    con = await aiosqlite.connect(DB_PATH)
    await con.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
    await con.commit()
    # get user id
    cur = await con.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
    row = await cur.fetchone()
    await con.close()
    return row["user_id"] if row else None

@app.post("/nowpayments_webhook")
async def nowpayments_webhook(request: Request, x_nowpayments_sig: str = Header(None), x_signature: str = Header(None)):
    body = await request.body()
    header_sig = x_nowpayments_sig or x_signature
    if not header_sig:
        raise HTTPException(status_code=400, detail="Missing signature header")
    if not verify_nowpayments_signature(body, header_sig):
        raise HTTPException(status_code=400, detail="Invalid signature")
    data = await request.json()
    # inspect payload fields in sandbox to confirm names
    # NowPayments usually returns fields like: invoice_id/id, payment_status/status, order_id
    order_id = data.get("order_id") or data.get("order") or data.get("invoice_id") or data.get("id")
    status = data.get("payment_status") or data.get("status") or data.get("pay_status")
    # treat paid statuses
    ok_statuses = ("confirmed","finished","paid","success")
    if status and status.lower() in ok_statuses:
        uid = await mark_order_paid_in_db(order_id)
        if uid:
            try:
                await bot.send_message(uid, f"✅ Plata pentru comanda <code>{order_id}</code> a fost confirmată. Comanda este procesată.", parse_mode="HTML")
            except Exception:
                pass
    return {"ok": True}

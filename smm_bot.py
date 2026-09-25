"""
SMM Service Shop Bot (Telegram)
--------------------------------
Menu-driven bot for selling followers/likes/views services.
- Manual deposit approval (bKash/Nagad + Transaction ID -> admin approves)
- Manual order delivery (admin fulfills orders by hand, bot just collects & notifies)

SETUP:
1. pip install python-telegram-bot==21.4
2. Fill in BOT_TOKEN and ADMIN_ID below.
3. Edit PRICES and PAYMENT_INFO to match your business.
4. Run: python smm_bot.py

Data is stored in data.json in the same folder (users, balances, orders, deposits).
"""

import json
import os
import logging
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ CONFIG — EDIT THESE ============
BOT_TOKEN = "8529798413:AAFe2AKthTv_CPKgxhU9N8jEut8GDk_yla4"
ADMIN_ID = 40200898  # Your numeric Telegram user ID (get it from @userinfobot)

PAYMENT_INFO = (
    "💰 *Deposit করার নিয়ম*\n\n"
    "বিকাশ (Personal): 01822348279\n"
    "নগদ (Personal): 01XXXXXXXXX\n\n"
    "টাকা পাঠানোর পর Transaction ID (TrxID) এখানে পাঠান।\n"
    "উদাহরণ: `TRX123ABC456`"
)

SUPPORT_TEXT = (
    "📞 *Support*\n\n"
    "যেকোনো সমস্যায় যোগাযোগ করুন:\n"
    "Telegram: @your_username\n"
    "WhatsApp: 01822348279"
)

# price per 1000 units, in Taka — edit freely
PRICES = {
    "Facebook Follower": 70,
    "Facebook Post React": 85,
    "Facebook Video View": 30,
    "TikTok Like": 60,
    "TikTok Views": 6,
    "TikTok Follower": 220,
    "TikTok Share": 30,
    "Instagram Follower": 70,
    "Instagram Like": 25,
    "Telegram Member": 40,
    "Telegram Lifetime Member": 170,
    "Telegram Post View": 2,
    "Telegram Post React": 20,
    "YouTube Views": 140,
    "YouTube Subscriber": 200,
    "Premium Service": 60,
    "Twitter Follower": 80,
}

# minimum order quantity per service — edit freely
MIN_ORDER = {
    "Facebook Follower": 100,
    "Facebook Post React": 10,
    "Facebook Video View": 500,
    "TikTok Like": 100,
    "TikTok Views": 1000,
    "TikTok Follower": 100,
    "TikTok Share": 100,
    "Instagram Follower": 100,
    "Instagram Like": 100,
    "Telegram Member": 100,
    "Telegram Lifetime Member": 100,
    "Telegram Post View": 10,
    "Telegram Post React": 10,
    "YouTube Views": 100,
    "YouTube Subscriber": 100,
    "Premium Service": 100,
    "Twitter Follower": 100,
}

PLATFORM_SERVICES = {
    "🎵 TikTok": ["TikTok Like", "TikTok Views", "TikTok Follower", "TikTok Share"],
    "🔵 Facebook": ["Facebook Follower", "Facebook Post React", "Facebook Video View"],
    "📸 Instagram": ["Instagram Follower", "Instagram Like"],
    "✈️ Telegram": ["Telegram Member", "Telegram Lifetime Member", "Telegram Post View", "Telegram Post React"],
    "🎥 YouTube": ["YouTube Views", "YouTube Subscriber", "Premium Service"],
    "🐦 Twitter": ["Twitter Follower"],
}

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

# ============ DATA STORAGE ============

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "orders": [], "deposits": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user(data, user_id, name=""):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {"name": name, "balance": 0}
        save_data(data)
    return data["users"][uid]


# ============ STATE (in-memory, simple) ============
# tracks what each user is currently doing: awaiting link, awaiting quantity, awaiting trxid, etc.
user_state = {}

# ============ KEYBOARDS ============

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🟢 Buy Service"), KeyboardButton("💰 Deposit")],
        [KeyboardButton("📜 Service Price"), KeyboardButton("👤 My Profile")],
        [KeyboardButton("📞 Support")],
    ],
    resize_keyboard=True,
)

PLATFORM_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🎵 TikTok"), KeyboardButton("🔵 Facebook")],
        [KeyboardButton("📸 Instagram"), KeyboardButton("✈️ Telegram")],
        [KeyboardButton("🎥 YouTube"), KeyboardButton("🐦 Twitter")],
        [KeyboardButton("⬅️ BACK মেইন মেনু")],
    ],
    resize_keyboard=True,
)


def service_menu_for(platform_label):
    services = PLATFORM_SERVICES[platform_label]
    rows = []
    for i in range(0, len(services), 2):
        chunk = services[i:i + 2]
        rows.append([KeyboardButton(s) for s in chunk])
    rows.append([KeyboardButton("⬅️ ব্যাক করুন")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ============ HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    get_user(data, user.id, user.full_name)
    user_state[user.id] = {"step": None}
    await update.message.reply_text(
        f"স্বাগতম, {user.full_name}! 👋\nনিচের মেনু থেকে সিলেক্ট করুন।",
        reply_markup=MAIN_MENU,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    data = load_data()
    urec = get_user(data, user.id, user.full_name)
    state = user_state.setdefault(user.id, {"step": None})

    # ---- Multi-step flows first ----
    if state.get("step") == "awaiting_trxid":
        trx_id = text
        deposit = {
            "user_id": user.id,
            "name": user.full_name,
            "trx_id": trx_id,
            "status": "pending",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        data["deposits"].append(deposit)
        save_data(data)
        state["step"] = None
        await update.message.reply_text(
            "✅ আপনার Transaction ID জমা হয়েছে। Admin ভেরিফাই করে ব্যালেন্স যোগ করবেন।",
            reply_markup=MAIN_MENU,
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 *নতুন Deposit রিকোয়েস্ট*\n"
            f"User: {user.full_name} (`{user.id}`)\n"
            f"TrxID: `{trx_id}`\n\n"
            f"Approve করতে পাঠান:\n`/approve {user.id} <amount>`",
            parse_mode="Markdown",
        )
        return

    if state.get("step") == "awaiting_quantity":
        if not text.isdigit():
            await update.message.reply_text("দয়া করে শুধু সংখ্যা দিন (যেমন: 500)")
            return
        qty = int(text)
        service = state["service"]
        min_qty = MIN_ORDER.get(service, 1)
        if qty < min_qty:
            await update.message.reply_text(
                f"❌ সর্বনিম্ন অর্ডার {min_qty}। আবার একটি সংখ্যা লিখুন (কমপক্ষে {min_qty}):"
            )
            return
        price_per_1000 = PRICES.get(service, 0)
        cost = round(price_per_1000 * qty / 1000, 2)
        if urec["balance"] < cost:
            await update.message.reply_text(
                f"❌ ব্যালেন্স অপর্যাপ্ত। প্রয়োজন: ৳{cost}, আপনার আছে: ৳{urec['balance']}\n"
                f"আগে Deposit করুন।",
                reply_markup=MAIN_MENU,
            )
            state["step"] = None
            return
        state["step"] = "awaiting_link"
        state["quantity"] = qty
        state["cost"] = cost
        await update.message.reply_text(
            f"পরিমাণ: {qty}\nমূল্য: ৳{cost}\n\n🔗 এখন আপনার প্রোফাইল/পোস্ট/ভিডিওর লিংক পাঠান:"
        )
        return

    if state.get("step") == "awaiting_link":
        link = text
        service = state["service"]
        qty = state["quantity"]
        cost = state["cost"]
        urec["balance"] = round(urec["balance"] - cost, 2)
        save_data(data)
        order = {
            "user_id": user.id,
            "name": user.full_name,
            "service": service,
            "quantity": qty,
            "cost": cost,
            "link": link,
            "status": "pending",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        data["orders"].append(order)
        save_data(data)
        state["step"] = None
        await update.message.reply_text(
            f"✅ অর্ডার সফল হয়েছে!\n\n"
            f"Service: {service}\nপরিমাণ: {qty}\nমূল্য: ৳{cost}\nলিংক: {link}\n\n"
            f"আপনার নতুন ব্যালেন্স: ৳{urec['balance']}\n"
            f"শীঘ্রই ডেলিভারি করা হবে।",
            reply_markup=MAIN_MENU,
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"🛒 *নতুন অর্ডার*\n"
            f"User: {user.full_name} (`{user.id}`)\n"
            f"Service: {service}\n"
            f"পরিমাণ: {qty}\n"
            f"মূল্য: ৳{cost}\n"
            f"লিংক: {link}",
            parse_mode="Markdown",
        )
        return

    # ---- Menu navigation ----
    if text == "🟢 Buy Service":
        await update.message.reply_text("প্ল্যাটফর্ম সিলেক্ট করুন:", reply_markup=PLATFORM_MENU)
        return

    if text in PLATFORM_SERVICES:
        state["platform"] = text
        await update.message.reply_text(
            f"{text} — সার্ভিস সিলেক্ট করুন:", reply_markup=service_menu_for(text)
        )
        return

    if text in PRICES:
        state["step"] = "awaiting_quantity"
        state["service"] = text
        price = PRICES[text]
        min_qty = MIN_ORDER.get(text, 1)
        await update.message.reply_text(
            f"{text}\n💰 প্রতি ১০০০ = ৳{price}\n📉 সর্বনিম্ন অর্ডার = {min_qty}\n\n"
            f"🔢 আপনি কতগুলো নিতে চান? (শুধু সংখ্যাটি লিখুন)"
        )
        return

    if text in ("⬅️ ব্যাক করুন",):
        await update.message.reply_text("প্ল্যাটফর্ম সিলেক্ট করুন:", reply_markup=PLATFORM_MENU)
        return

    if text in ("⬅️ BACK মেইন মেনু",):
        await update.message.reply_text("মেইন মেনু:", reply_markup=MAIN_MENU)
        return

    if text == "💰 Deposit":
        state["step"] = "awaiting_trxid"
        await update.message.reply_text(PAYMENT_INFO, parse_mode="Markdown")
        return

    if text == "📜 Service Price":
        lines = ["📜 *সার্ভিস প্রাইস লিস্ট* (প্রতি ১০০০)\n"]
        for name, price in PRICES.items():
            min_qty = MIN_ORDER.get(name, 1)
            lines.append(f"• {name}: ৳{price} (min: {min_qty})")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    if text == "👤 My Profile":
        await update.message.reply_text(
            f"👤 *প্রোফাইল*\n\nনাম: {user.full_name}\nID: `{user.id}`\nব্যালেন্স: ৳{urec['balance']}",
            parse_mode="Markdown",
        )
        return

    if text == "📞 Support":
        await update.message.reply_text(SUPPORT_TEXT, parse_mode="Markdown")
        return

    await update.message.reply_text("মেনু থেকে একটি অপশন সিলেক্ট করুন।", reply_markup=MAIN_MENU)


# ============ ADMIN COMMANDS ============

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("ব্যবহার: /approve <user_id> <amount>")
        return

    data = load_data()
    urec = get_user(data, target_id)
    urec["balance"] = round(urec["balance"] + amount, 2)
    for dep in reversed(data["deposits"]):
        if dep["user_id"] == target_id and dep["status"] == "pending":
            dep["status"] = "approved"
            break
    save_data(data)

    await update.message.reply_text(f"✅ Approved. User {target_id} নতুন ব্যালেন্স: ৳{urec['balance']}")
    await context.bot.send_message(
        target_id, f"✅ আপনার Deposit Approve হয়েছে। ৳{amount} যোগ হয়েছে।\nনতুন ব্যালেন্স: ৳{urec['balance']}"
    )


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_data()
    pend = [d for d in data["deposits"] if d["status"] == "pending"]
    if not pend:
        await update.message.reply_text("কোনো Pending deposit নেই।")
        return
    lines = ["🕒 *Pending Deposits*\n"]
    for d in pend:
        lines.append(f"User: {d['name']} (`{d['user_id']}`) — TrxID: `{d['trx_id']}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    data = load_data()
    pend = [o for o in data["orders"] if o["status"] == "pending"]
    if not pend:
        await update.message.reply_text("কোনো Pending অর্ডার নেই।")
        return
    lines = ["🛒 *Pending Orders*\n"]
    for o in pend:
        lines.append(
            f"User: {o['name']} — {o['service']} x{o['quantity']} — ৳{o['cost']}\nলিংক: {o['link']}\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark the most recent pending order for a user as delivered: /done <user_id>"""
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("ব্যবহার: /done <user_id>")
        return
    data = load_data()
    for order in reversed(data["orders"]):
        if order["user_id"] == target_id and order["status"] == "pending":
            order["status"] = "delivered"
            save_data(data)
            await update.message.reply_text("✅ Order marked as delivered.")
            await context.bot.send_message(target_id, f"✅ আপনার {order['service']} অর্ডার ডেলিভারি সম্পন্ন হয়েছে!")
            return
    await update.message.reply_text("এই ইউজারের কোনো Pending অর্ডার পাওয়া যায়নি।")


def main():
    if BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        print("⚠️  BOT_TOKEN সেট করুন smm_bot.py ফাইলের উপরে!")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("orders", orders_cmd))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot চালু হয়েছে...")
    app.run_polling()


if __name__ == "__main__":
    main()

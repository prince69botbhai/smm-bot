"""
SMM Service Shop Bot (Telegram) — v2
-------------------------------------
Menu-driven bot for selling followers/likes/views services.

What's new in v2:
- Inline buttons everywhere (no more reply-keyboard text matching -> "Back"
  button now always works correctly, since every button has a fixed id).
- User state (what step someone is on, mid-order) is saved to data.json,
  so a server restart does not lose someone's in-progress order.
- /cancel command — abandons whatever the user was doing and returns to
  the main menu.
- Link validation — rejects text that isn't a real http(s) link before
  accepting it as the order's profile/post/video link.

SETUP:
1. pip install python-telegram-bot==21.4 Flask==3.0.3
2. Fill in BOT_TOKEN and ADMIN_ID below.
3. Edit PRICES, MIN_ORDER and PAYMENT_INFO to match your business.
4. Run: python smm_bot_v2.py

Data is stored in data.json in the same folder (users, orders, deposits, state).
"""

import json
import os
import re
import logging
import threading
from datetime import datetime

from flask import Flask
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ KEEP-ALIVE WEB SERVER (for Render free Web Service) ============
keep_alive_app = Flask(__name__)


@keep_alive_app.route("/")
def home():
    return "Bot is running!"


def run_keep_alive():
    port = int(os.environ.get("PORT", 8080))
    keep_alive_app.run(host="0.0.0.0", port=port)


# ============ CONFIG — EDIT THESE ============
BOT_TOKEN = "8529798413:AAFe2AKthTv_CPKgxhU9N8jEut8GDk_yla4"
ADMIN_ID = 7190437569  # Your numeric Telegram user ID (get it from @userinfobot)

PAYMENT_INFO = (
    "💰 *Deposit করার নিয়ম*\n\n"
    "বিকাশ (Personal): 01822348279\n"
    "নগদ (Personal): 01XXXXXXXXX\n\n"
    "টাকা পাঠানোর পর Transaction ID (TrxID) এখানে লিখে পাঠান।\n"
    "উদাহরণ: `TRX123ABC456`"
)

SUPPORT_TEXT = (
    "📞 *Support*\n\n"
    "যেকোনো সমস্যায় যোগাযোগ করুন:\n"
    "Telegram: @ZEROX9TX\n"
    "WhatsApp: 01822348279"
)

# platform key -> {label, emoji, services: [service names]}
PLATFORMS = {
    "tiktok": {
        "label": "TikTok",
        "emoji": "🎵",
        "services": ["TikTok Like", "TikTok Views", "TikTok Follower", "TikTok Share"],
    },
    "facebook": {
        "label": "Facebook",
        "emoji": "🔵",
        "services": ["Facebook Follower", "Facebook Post React", "Facebook Video View"],
    },
    "instagram": {
        "label": "Instagram",
        "emoji": "📸",
        "services": ["Instagram Follower", "Instagram Like"],
    },
    "telegram": {
        "label": "Telegram",
        "emoji": "✈️",
        "services": [
            "Telegram Member",
            "Telegram Lifetime Member",
            "Telegram Post View",
            "Telegram Post React",
        ],
    },
    "youtube": {
        "label": "YouTube",
        "emoji": "🎥",
        "services": ["YouTube Views", "YouTube Subscriber", "Premium Service"],
    },
    "twitter": {
        "label": "Twitter",
        "emoji": "🐦",
        "services": ["Twitter Follower"],
    },
}

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

# a basic but solid http(s) URL check
URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

# ============ DATA STORAGE ============

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "orders": [], "deposits": [], "state": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("state", {})
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user(data, user_id, name=""):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {"name": name, "balance": 0}
        save_data(data)
    return data["users"][uid]


def get_state(data, user_id):
    return data["state"].get(str(user_id), {"step": None})


def set_state(data, user_id, state):
    data["state"][str(user_id)] = state
    save_data(data)


def clear_state(data, user_id):
    data["state"].pop(str(user_id), None)
    save_data(data)


# ============ INLINE KEYBOARDS ============

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Buy Service", callback_data="buy"),
         InlineKeyboardButton("💰 Deposit", callback_data="deposit")],
        [InlineKeyboardButton("📜 Service Price", callback_data="price"),
         InlineKeyboardButton("👤 My Profile", callback_data="profile")],
        [InlineKeyboardButton("📞 Support", callback_data="support")],
    ])


def platforms_kb():
    keys = list(PLATFORMS.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = []
        for k in keys[i:i + 2]:
            p = PLATFORMS[k]
            row.append(InlineKeyboardButton(f"{p['emoji']} {p['label']}", callback_data=f"platform:{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ মেইন মেনু", callback_data="main")])
    return InlineKeyboardMarkup(rows)


def services_kb(platform_key):
    services = PLATFORMS[platform_key]["services"]
    rows = []
    for i in range(0, len(services), 2):
        row = [InlineKeyboardButton(s, callback_data=f"service:{s}") for s in services[i:i + 2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="buy")])
    return InlineKeyboardMarkup(rows)


def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]])


# ============ TEXT BUILDERS ============

def price_list_text():
    lines = ["📜 *সার্ভিস প্রাইস লিস্ট* (প্রতি ১০০০)\n"]
    for name, price in PRICES.items():
        min_qty = MIN_ORDER.get(name, 1)
        lines.append(f"• {name}: ৳{price} (min: {min_qty})")
    return "\n".join(lines)


def profile_text(user, urec):
    return (
        f"👤 *প্রোফাইল*\n\n"
        f"নাম: {user.full_name}\n"
        f"ID: `{user.id}`\n"
        f"ব্যালেন্স: ৳{urec['balance']}"
    )


# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    get_user(data, user.id, user.full_name)
    clear_state(data, user.id)
    await update.message.reply_text(
        f"স্বাগতম, {user.full_name}! 👋\nনিচের মেনু থেকে সিলেক্ট করুন।",
        reply_markup=main_menu_kb(),
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    clear_state(data, user.id)
    await update.message.reply_text(
        "❌ বর্তমান কাজ বাতিল করা হয়েছে।",
        reply_markup=main_menu_kb(),
    )


# ============ CALLBACK (INLINE BUTTON) HANDLER ============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    user = query.from_user
    urec = get_user(data, user.id, user.full_name)
    action = query.data

    if action == "main":
        clear_state(data, user.id)
        await query.edit_message_text("মেইন মেনু:", reply_markup=main_menu_kb())
        return

    if action == "cancel":
        clear_state(data, user.id)
        await query.edit_message_text("❌ বাতিল হয়েছে।\n\nমেইন মেনু:", reply_markup=main_menu_kb())
        return

    if action == "buy":
        clear_state(data, user.id)
        await query.edit_message_text("প্ল্যাটফর্ম সিলেক্ট করুন:", reply_markup=platforms_kb())
        return

    if action.startswith("platform:"):
        platform_key = action.split(":", 1)[1]
        platform = PLATFORMS.get(platform_key)
        if not platform:
            await query.edit_message_text("প্ল্যাটফর্ম পাওয়া যায়নি।", reply_markup=platforms_kb())
            return
        await query.edit_message_text(
            f"{platform['emoji']} {platform['label']} — সার্ভিস সিলেক্ট করুন:",
            reply_markup=services_kb(platform_key),
        )
        return

    if action.startswith("service:"):
        service = action.split(":", 1)[1]
        if service not in PRICES:
            await query.edit_message_text("সার্ভিস পাওয়া যায়নি।", reply_markup=platforms_kb())
            return
        set_state(data, user.id, {"step": "awaiting_quantity", "service": service})
        price = PRICES[service]
        min_qty = MIN_ORDER.get(service, 1)
        await query.edit_message_text(
            f"🛒 {service}\n💰 প্রতি ১০০০ = ৳{price}\n📉 সর্বনিম্ন অর্ডার = {min_qty}\n\n"
            f"🔢 কতগুলো নিতে চান? নিচে সংখ্যাটি লিখে পাঠান।",
            reply_markup=cancel_kb(),
        )
        return

    if action == "deposit":
        set_state(data, user.id, {"step": "awaiting_trxid"})
        await query.edit_message_text(
            PAYMENT_INFO + "\n\n(TrxID লিখে পাঠান)",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return

    if action == "price":
        await query.edit_message_text(
            price_list_text(), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ মেইন মেনু", callback_data="main")]]),
        )
        return

    if action == "profile":
        await query.edit_message_text(
            profile_text(user, urec), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ মেইন মেনু", callback_data="main")]]),
        )
        return

    if action == "support":
        await query.edit_message_text(
            SUPPORT_TEXT, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ মেইন মেনু", callback_data="main")]]),
        )
        return


# ============ TEXT MESSAGE HANDLER (multi-step flows) ============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    data = load_data()
    urec = get_user(data, user.id, user.full_name)
    state = get_state(data, user.id)
    step = state.get("step")

    if step == "awaiting_trxid":
        trx_id = text
        deposit = {
            "user_id": user.id,
            "name": user.full_name,
            "trx_id": trx_id,
            "status": "pending",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        data["deposits"].append(deposit)
        clear_state(data, user.id)
        await update.message.reply_text(
            "✅ আপনার Transaction ID জমা হয়েছে। Admin ভেরিফাই করে ব্যালেন্স যোগ করবেন।",
            reply_markup=main_menu_kb(),
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

    if step == "awaiting_quantity":
        if not text.isdigit():
            await update.message.reply_text(
                "দয়া করে শুধু সংখ্যা দিন (যেমন: 500)", reply_markup=cancel_kb()
            )
            return
        qty = int(text)
        service = state["service"]
        min_qty = MIN_ORDER.get(service, 1)
        if qty < min_qty:
            await update.message.reply_text(
                f"❌ সর্বনিম্ন অর্ডার {min_qty}। আবার একটি সংখ্যা লিখুন (কমপক্ষে {min_qty}):",
                reply_markup=cancel_kb(),
            )
            return
        price_per_1000 = PRICES.get(service, 0)
        cost = round(price_per_1000 * qty / 1000, 2)
        if urec["balance"] < cost:
            await update.message.reply_text(
                f"❌ ব্যালেন্স অপর্যাপ্ত। প্রয়োজন: ৳{cost}, আপনার আছে: ৳{urec['balance']}\n"
                f"আগে Deposit করুন।",
                reply_markup=main_menu_kb(),
            )
            clear_state(data, user.id)
            return
        set_state(data, user.id, {
            "step": "awaiting_link", "service": service, "quantity": qty, "cost": cost,
        })
        await update.message.reply_text(
            f"পরিমাণ: {qty}\nমূল্য: ৳{cost}\n\n🔗 এখন আপনার প্রোফাইল/পোস্ট/ভিডিওর লিংক (http/https সহ) পাঠান:",
            reply_markup=cancel_kb(),
        )
        return

    if step == "awaiting_link":
        link = text
        if not URL_RE.match(link):
            await update.message.reply_text(
                "❌ এটা একটা সঠিক লিংক মনে হচ্ছে না।\n"
                "লিংক অবশ্যই `http://` অথবা `https://` দিয়ে শুরু হতে হবে।\n"
                "যেমন: `https://facebook.com/yourpage`\n\nআবার লিংক পাঠান:",
                parse_mode="Markdown",
                reply_markup=cancel_kb(),
            )
            return
        service = state["service"]
        qty = state["quantity"]
        cost = state["cost"]
        urec["balance"] = round(urec["balance"] - cost, 2)
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
        clear_state(data, user.id)
        await update.message.reply_text(
            f"✅ অর্ডার সফল হয়েছে!\n\n"
            f"Service: {service}\nপরিমাণ: {qty}\nমূল্য: ৳{cost}\nলিংক: {link}\n\n"
            f"আপনার নতুন ব্যালেন্স: ৳{urec['balance']}\n"
            f"শীঘ্রই ডেলিভারি করা হবে।",
            reply_markup=main_menu_kb(),
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

    # no active step -> nudge them to use the menu
    await update.message.reply_text(
        "মেনু থেকে একটি অপশন সিলেক্ট করুন, অথবা /start লিখুন।",
        reply_markup=main_menu_kb(),
    )


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


# ============ MAIN ============

def main():
    if BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        print("⚠️  BOT_TOKEN সেট করুন smm_bot_v2.py ফাইলের উপরে!")
        return

    # Ensure an asyncio event loop exists in the main thread
    # (some hosts run a Python version that no longer auto-creates one).
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # start the keep-alive web server in a background thread
    threading.Thread(target=run_keep_alive, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("orders", orders_cmd))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot চালু হয়েছে...")
    app.run_polling()


if __name__ == "__main__":
    main()

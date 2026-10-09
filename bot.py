import asyncio
import datetime
import json
import os
import re
import aiohttp
import pytz
from telegram import Bot, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = "8823333396:AAGhZC3Y2NGfZawZO-mdluPD-vS87sahqV8"
DB_FILE = "wallets.json"
QR_DB_FILE = "qr_codes.json"
CHINA_TZ = pytz.timezone("Asia/Shanghai")
TRONGRID_API_KEY = ""

def load_wallets():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_wallets(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_qr_codes():
    if os.path.exists(QR_DB_FILE):
        try:
            with open(QR_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_qr_codes(data):
    with open(QR_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

async def get_binance_p2p_list(fiat_currency: str, limit: int = 10):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    payload = {
        "asset": "USDT",
        "fiat": fiat_currency,
        "merchantCheck": False,
        "page": 1,
        "payTypes": [],
        "publisherType": None,
        "rows": limit,
        "tradeType": "BUY",
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    items = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=5)
            ) as res:
                if res.status == 200:
                    data = await res.json()
                    advs = data.get("data", [])
                    for item in advs:
                        price = float(item["adv"]["price"])
                        nickname = item.get("advertiser", {}).get("nickName", "Unknown")
                        items.append((price, nickname))
    except Exception as e:
        print(f"Lỗi lấy giá Binance P2P {fiat_currency}: {e}")
    return items

async def get_wallet_balance(address: str):
    if not address or len(address) != 34 or not address.startswith("T"):
        return None, None
    headers_gen = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with aiohttp.ClientSession() as session:
        try:
            url1 = f"https://apilist.tronscanapi.com/api/account/tokens?address={address}"
            async with session.get(url1, headers=headers_gen, timeout=aiohttp.ClientTimeout(total=5)) as res:
                if res.status == 200:
                    data = await res.json()
                    tokens = data.get("data", [])
                    usdt, trx = 0.0, 0.0
                    for tk in tokens:
                        if tk.get("tokenAbbr") == "trx":
                            trx = float(tk.get("balance", 0)) / (10 ** int(tk.get("tokenDecimal", 6)))
                        elif tk.get("tokenId") == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t" or tk.get("tokenAbbr") == "USDT":
                            usdt = float(tk.get("balance", 0)) / (10 ** int(tk.get("tokenDecimal", 6)))
                    return usdt, trx
        except Exception:
            pass

        try:
            url2 = f"https://api.trongrid.io/v1/accounts/{address}"
            h2 = {"Accept": "application/json", **headers_gen}
            if TRONGRID_API_KEY:
                h2["TRON-PRO-API-KEY"] = TRONGRID_API_KEY
            async with session.get(url2, headers=h2, timeout=aiohttp.ClientTimeout(total=5)) as res:
                if res.status == 200:
                    data = await res.json()
                    if data.get("data"):
                        acc = data["data"][0]
                        trx = float(acc.get("balance", 0)) / 1_000_000.0
                        usdt = 0.0
                        for token in acc.get("trc20", []):
                            if "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t" in token:
                                usdt = float(token["TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"]) / 1_000_000.0
                                break
                        return usdt, trx
        except Exception:
            pass
    return None, None

async def get_latest_transaction_details(address: str):
    url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=1"
    headers = {"Accept": "application/json"}
    if TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONGRID_API_KEY
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as res:
                if res.status == 200:
                    data = await res.json()
                    tx_list = data.get("data", [])
                    if tx_list:
                        tx = tx_list[0]
                        sender = tx.get("from") or tx.get("from_address") or "未知地址"
                        receiver = tx.get("to") or tx.get("to_address") or "未知地址"
                        tx_hash = tx.get("transaction_id", "")
                        block = "N/A"
                        if tx_hash:
                            tronscan_url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}"
                            headers_gen = {"User-Agent": "Mozilla/5.0"}
                            async with session.get(tronscan_url, headers=headers_gen, timeout=aiohttp.ClientTimeout(total=4)) as scan_res:
                                if scan_res.status == 200:
                                    scan_data = await scan_res.json()
                                    block = scan_data.get("block") or scan_data.get("blockNumber") or "N/A"
                        masked_hash = f"{tx_hash[:8]}...{tx_hash[-6:]}" if tx_hash and len(tx_hash) > 14 else (tx_hash or "N/A")
                        ts = tx.get("block_timestamp", 0)
                        if ts > 0:
                            dt = datetime.datetime.fromtimestamp(ts / 1000.0, tz=pytz.utc).astimezone(CHINA_TZ)
                            tx_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            tx_time_str = datetime.datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
                        return sender, receiver, str(block), masked_hash, tx_time_str
    except Exception as e:
        print(f"Lỗi lấy chi tiết giao dịch {address}: {e}")
    now_cn = datetime.datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return "未知地址", "未知地址", "N/A", "N/A", now_cn

async def recalculate_today_from_chain(address: str):
    url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=100"
    headers = {"Accept": "application/json"}
    if TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONGRID_API_KEY
    total_in = 0.0
    total_out = 0.0
    try:
        now_local = datetime.datetime.now(CHINA_TZ)
        start_of_day = datetime.datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0, tzinfo=CHINA_TZ)
        end_of_day = datetime.datetime(now_local.year, now_local.month, now_local.day, 23, 59, 59, tzinfo=CHINA_TZ)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as res:
                if res.status == 200:
                    data = await res.json()
                    for tx in data.get("data", []):
                        ts = tx.get("block_timestamp", 0)
                        dt = datetime.datetime.fromtimestamp(ts / 1000.0, tz=pytz.utc).astimezone(CHINA_TZ) if ts > 0 else None
                        if dt and start_of_day <= dt <= end_of_day:
                            to_addr = tx.get("to") or tx.get("to_address") or ""
                            from_addr = tx.get("from") or tx.get("from_address") or ""
                            raw_val = float(tx.get("value", 0))
                            token_info = tx.get("token_info", {})
                            decimals = int(token_info.get("decimals", 6)) if isinstance(token_info, dict) else 6
                            value = raw_val / (10**decimals)
                            if to_addr.lower() == address.lower():
                                total_in += value
                            elif from_addr.lower() == address.lower():
                                total_out += value
    except Exception as e:
        print(f"Lỗi tính toán lại blockchain cho {address}: {e}")
    profit = total_in - total_out
    return total_in, total_out, profit

async def get_recent_transactions_today(address: str, limit=5):
    url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=20"
    headers = {"Accept": "application/json"}
    if TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONGRID_API_KEY
    tx_list = []
    try:
        now_local = datetime.datetime.now(CHINA_TZ)
        start_of_day = datetime.datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0, tzinfo=CHINA_TZ)
        end_of_day = datetime.datetime(now_local.year, now_local.month, now_local.day, 23, 59, 59, tzinfo=CHINA_TZ)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as res:
                if res.status == 200:
                    data = await res.json()
                    for tx in data.get("data", []):
                        ts = tx.get("block_timestamp", 0)
                        dt = datetime.datetime.fromtimestamp(ts / 1000.0, tz=pytz.utc).astimezone(CHINA_TZ) if ts > 0 else None
                        if dt and start_of_day <= dt <= end_of_day:
                            to_addr = tx.get("to") or tx.get("to_address") or ""
                            raw_val = float(tx.get("value", 0))
                            token_info = tx.get("token_info", {})
                            decimals = int(token_info.get("decimals", 6)) if isinstance(token_info, dict) else 6
                            symbol = token_info.get("symbol", "USDT").upper() if isinstance(token_info, dict) else "USDT"
                            value = raw_val / (10**decimals)
                            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                            tx_type = "今日转入" if to_addr.lower() == address.lower() else "今日转出"
                            tx_list.append(f"{tx_type}：{value:,.2f} {symbol}    （{time_str}）")
                            if len(tx_list) >= limit:
                                break
    except Exception as e:
        print(f"Lỗi lấy giao dịch {address}: {e}")
    return tx_list

async def monitor_wallets_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        wallets = load_wallets()
        for chat_id, user_wallets in list(wallets.items()):
            for address, info in list(user_wallets.items()):
                curr_usdt, curr_trx = await get_wallet_balance(address)
                if curr_usdt is not None and curr_trx is not None:
                    last_usdt = info.get("last_usdt")
                    memo = info.get("memo", "")
                    memo_str = f" {memo} 入" if memo else " 入"
                    memo_str_out = f" {memo} 出" if memo else " 出"
                    notify_msg = ""
                    total_in, total_out, profit = 0.0, 0.0, 0.0

                    if last_usdt is not None and curr_usdt > last_usdt + 0.01:
                        amount = curr_usdt - last_usdt
                        sender, _, block, masked_hash, tx_time_str = await get_latest_transaction_details(address)
                        total_in, total_out, profit = await recalculate_today_from_chain(address)
                        notify_msg = (
                            f"🔺 <b>收入通知</b>\n\n"
                            f"链：<b>TRC (Tron)</b>\n"
                            f"交易金额: <b>{amount:,.2f} USDT</b>\n"
                            f"地址: <code>{address}</code>{memo_str}\n"
                            f"来自: <code>{sender}</code>\n\n"
                            f"时间: <b>{tx_time_str}</b>\n"
                            f"区块: <b>{block}</b>\n"
                            f"交易哈希：<code>{masked_hash}</code>\n\n"
                            f"今日收入：<b>{total_in:,.2f} USDT / 0 TRX</b>\n"
                            f"今日支出：<b>{total_out:,.2f} USDT / 0 TRX</b>\n"
                            f"今日利润：<b>{profit:,.2f} USDT / 0 TRX</b>\n\n"
                            f"💰 USDT 余额: <b>{curr_usdt:,.2f}</b>\n"
                            f"⚡️ TRX 余额: <b>{curr_trx:,.2f}</b>"
                        )
                    elif last_usdt is not None and curr_usdt < last_usdt - 0.01:
                        amount = last_usdt - curr_usdt
                        _, receiver, block, masked_hash, tx_time_str = await get_latest_transaction_details(address)
                        total_in, total_out, profit = await recalculate_today_from_chain(address)
                        notify_msg = (
                            f"🔻 <b>转出通知</b>\n\n"
                            f"链：<b>TRC (Tron)</b>\n"
                            f"交易金额: <b>{amount:,.2f} USDT</b>\n"
                            f"地址: <code>{address}</code>{memo_str_out}\n"
                            f"发往: <code>{receiver}</code>\n\n"
                            f"时间: <b>{tx_time_str}</b>\n"
                            f"区块: <b>{block}</b>\n"
                            f"交易哈希：<code>{masked_hash}</code>\n\n"
                            f"今日收入：<b>{total_in:,.2f} USDT / 0 TRX</b>\n"
                            f"今日支出：<b>{total_out:,.2f} USDT / 0 TRX</b>\n"
                            f"今日利润：<b>{profit:,.2f} USDT / 0 TRX</b>\n\n"
                            f"💰 USDT 余额: <b>{curr_usdt:,.2f}</b>\n"
                            f"⚡ TRX 余额: <b>{curr_trx:,.2f}</b>"
                        )

                    if notify_msg:
                        try:
                            await context.bot.send_message(chat_id=int(chat_id), text=notify_msg, parse_mode="HTML")
                        except Exception as e:
                            print(f"Lỗi gửi tin nhắn: {e}")

                    wallets[chat_id][address]["last_usdt"] = curr_usdt
                    wallets[chat_id][address]["last_trx"] = curr_trx
                    today_str = datetime.datetime.now(CHINA_TZ).strftime("%Y-%m-%d")
                    wallets[chat_id][address]["last_date"] = today_str
                    if notify_msg:
                        wallets[chat_id][address]["total_in"] = total_in
                        wallets[chat_id][address]["total_out"] = total_out
                    save_wallets(wallets)
    except Exception as e:
        print(f"Lỗi monitor loop: {e}")

async def all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    wallets = load_wallets()
    if chat_id not in wallets or not wallets[chat_id]:
        await update.message.reply_text("📋 Danh sách ví đang trống.")
        return
    msg_lines = [f"{idx}. <code>{addr}</code>" for idx, addr in enumerate(wallets[chat_id].keys(), 1)]
    await update.message.reply_text("\n".join(msg_lines), parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    raw_text = (update.message.text or update.message.caption or "").strip()
    text = raw_text.split("\n")[-1].strip() if raw_text else ""
    chat_id = str(update.effective_chat.id)
    wallets = load_wallets()
    qr_codes = load_qr_codes()

    match_del_qr = re.search(r"^(?:/)?del\+码\+(.+)$", text, re.IGNORECASE)
    if match_del_qr:
        target_addr = match_del_qr.group(1).strip()
        if chat_id in qr_codes and target_addr in qr_codes[chat_id]:
            del qr_codes[chat_id][target_addr]
            save_qr_codes(qr_codes)
            await update.message.reply_text("✅ 已成功删除该地址的二维码图片！")
        else:
            await update.message.reply_text("❌ 未找到该地址的二维码记录。")
        return

    match_save_qr = re.search(r"^(?:/)?记\+(.+)$", text, re.IGNORECASE)
    if match_save_qr:
        target_addr = match_save_qr.group(1).strip()
        photo_obj = update.message.photo[-1] if update.message.photo else (update.message.reply_to_message.photo[-1] if update.message.reply_to_message and update.message.reply_to_message.photo else None)
        if photo_obj and target_addr:
            if chat_id not in qr_codes:
                qr_codes[chat_id] = {}
            qr_codes[chat_id][target_addr] = photo_obj.file_id
            save_qr_codes(qr_codes)
            await update.message.reply_text("✅ 已成功保存该地址的二维码图片！")
        else:
            await update.message.reply_text("❌ 保存失败，请确保发送了图片并附带正确的地址格式。")
        return

    match_get_qr = re.search(r"^码\+(.+)$", text, re.IGNORECASE)
    if match_get_qr:
        target_addr = match_get_qr.group(1).strip()
        if chat_id in qr_codes and target_addr in qr_codes[chat_id]:
            await update.message.reply_photo(photo=qr_codes[chat_id][target_addr], caption=f"<code>{target_addr}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ 未找到该地址的二维码图片。")
        return

    if not text:
        return
    text_lower = text.lower()

    if text_lower.endswith("uj"):
        try:
            amount = float(text_lower.replace("uj", "").strip() or 1.0)
        except ValueError:
            return
        p2p_list = await get_binance_p2p_list("CNY", limit=10)
        if not p2p_list:
            await update.message.reply_text("❌ 无法从 Binance P2P 获取 CNY 数据。")
            return
        prices = [price for price, _ in p2p_list]
        lines = ["<b>[ 币安 P2P 实时报价 - 支付宝/微信 ]</b>"]
        for price, name in p2p_list:
            lines.append(f"{price:.2f}    <code>{name}</code>")
        top_3 = prices[:3] if len(prices) >= 3 else prices
        avg_price = sum(top_3) / len(top_3) if top_3 else 0.0
        total_cny = amount * avg_price
        result_text = "\n".join(lines) + f"\n\n<b>实时价格 (三档) :</b>\n{amount:,.0f} * {avg_price:.2f} = {total_cny:.2f} CNY"
        await update.message.reply_text(result_text, parse_mode="HTML")
        return

    if text_lower.endswith("u"):
        try:
            amount = float(text_lower.replace("u", "").strip() or 0.0)
        except ValueError:
            return
        if amount <= 0:
            return
        p2p_list = await get_binance_p2p_list("VND", limit=10)
        if not p2p_list:
            await update.message.reply_text("❌ 无法从 Binance P2P 获取数据。")
            return
        prices = [price for price, _ in p2p_list]
        lines = ["<b>[ 币安 P2P 实时报价 - 银行卡 ]</b>"]
        for price, name in p2p_list:
            lines.append(f"{round(price):,}    <code>{name}</code>")
        top_3 = prices[:3] if len(prices) >= 3 else prices
        avg_price_int = round(sum(top_3) / len(top_3)) if top_3 else 0
        total_vnd = amount * avg_price_int
        result_text = "\n".join(lines) + f"\n\n<b>实时价格 (三档) :</b>\n{amount:,.0f} * {avg_price_int:,} = {total_vnd:,.0f} VNĐ"
        await update.message.reply_text(result_text, parse_mode="HTML")
        return

    match_del = re.search(r"^(?:/)?del\+(.+)$", text, re.IGNORECASE)
    if match_del:
        param = match_del.group(1).strip()
        parts = [p.strip() for p in param.split("+") if p.strip()]
        found_addr = None
        if chat_id in wallets:
            for addr, info in wallets[chat_id].items():
                memo = info.get("memo", "")
                for p in parts:
                    if addr.lower() == p.lower() or memo.lower() == p.lower():
                        found_addr = addr
                        break
                if found_addr:
                    break
        if found_addr:
            memo_del = wallets[chat_id][found_addr].get("memo", "")
            del wallets[chat_id][found_addr]
            save_wallets(wallets)
            await update.message.reply_text(f"🗑 <b>已删除监听地址</b>{'（备注：' + memo_del + '）' if memo_del else ''}\n<code>{found_addr}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ 未找到对应的地址或备注。")
        return

    match_add = re.search(r"^(?:/)?add\+([T][a-zA-Z0-9]{33})(?:\+([^\n\s]+))?", text, re.IGNORECASE)
    if match_add:
        address = match_add.group(1).strip()
        memo = match_add.group(2).strip() if match_add.group(2) else ""
        usdt, trx = await get_wallet_balance(address)
        if usdt is None:
            await update.message.reply_text("⚠️ API 查询余额超时或出错。")
            return
        if chat_id not in wallets:
            wallets[chat_id] = {}
        now_str = datetime.datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        wallets[chat_id][address] = {
            "memo": memo, "last_usdt": usdt, "last_trx": trx,
            "added_at": now_str, "last_date": datetime.datetime.now(CHINA_TZ).strftime("%Y-%m-%d"),
            "total_in": 0.0, "total_out": 0.0
        }
        save_wallets(wallets)
        await update.message.reply_text(f"✅ 已添加监听地址{'（备注：' + memo + '）' if memo else ''}\n<code>{address}</code>\n\n🕒 创建时间：{now_str}\n💰 USDT：{usdt:,.2f}\n⚡️ TRX：{trx:,.2f}", parse_mode="HTML")
        return

    match_stat = re.search(r"^(.+?)\s*(?:统计|tong)$", text, re.IGNORECASE)
    if match_stat:
        query = match_stat.group(1).strip()
        found_addr = None
        if chat_id in wallets:
            for addr, info in wallets[chat_id].items():
                if addr.lower() == query.lower() or info.get("memo", "").lower() == query.lower():
                    found_addr = addr
                    break
        if not found_addr and re.match(r"^T[a-zA-Z0-9]{33}$", query):
            found_addr = query
        if not found_addr:
            await update.message.reply_text("❌ 未找到指定地址。")
            return
        total_in, total_out, profit = await recalculate_today_from_chain(found_addr)
        curr_usdt, curr_trx = await get_wallet_balance(found_addr)
        await update.message.reply_text(f"📊 <b>今日数据统计重新计算</b>\n\n地址: <code>{found_addr}</code>\n\n今日收入：<b>{total_in:,.2f} USDT / 0 TRX</b>\n今日支出：<b>{total_out:,.2f} USDT / 0 TRX</b>\n今日利润：<b>{profit:,.2f} USDT / 0 TRX</b>\n\n💰 USDT 余额: <b>{(curr_usdt or 0.0):,.2f}</b>\n⚡ TRX 余额: <b>{(curr_trx or 0.0):,.2f}</b>", parse_mode="HTML")
        return

    match_tx = re.search(r"^(.+?)\s*交易$", text, re.IGNORECASE)
    if match_tx:
        query = match_tx.group(1).strip()
        found_addr = None
        if chat_id in wallets:
            for addr, info in wallets[chat_id].items():
                if addr.lower() == query.lower() or info.get("memo", "").lower() == query.lower():
                    found_addr = addr
                    break
        if not found_addr and re.match(r"^T[a-zA-Z0-9]{33}$", query):
            found_addr = query
        if not found_addr:
            await update.message.reply_text("❌ 未找到指定地址。")
            return
        tx_history = await get_recent_transactions_today(found_addr, limit=5)
        if not tx_history:
            await update.message.reply_text("今日无交易")
            return
        await update.message.reply_text(f"<code>{found_addr}</code> 交易\n\n" + "\n".join(tx_history), parse_mode="HTML")
        return

    clean_addr = None
    tron_match = re.search(r"\b(T[a-zA-Z0-9]{33})\b", raw_text)
    if tron_match:
        clean_addr = tron_match.group(1)
    else:
        if re.search(r"\b(T[a-zA-Z0-9]{10,50})\b", raw_text):
            await update.message.reply_text("❌ 地址格式不正确（必须为 34 位 TRX 地址）。", parse_mode="HTML")
            return
        match_check = re.search(r"^查\s*(.+)$", text, re.IGNORECASE)
        if match_check:
            query = match_check.group(1).strip()
            if chat_id in wallets:
                for addr, info in wallets[chat_id].items():
                    if query.lower() == info.get("memo", "").lower():
                        clean_addr = addr
                        break

    if clean_addr:
        usdt, trx = await get_wallet_balance(clean_addr)
        if usdt is None:
            await update.message.reply_text("⚠️ API 查询余额失败，请检查网络或地址。", parse_mode="HTML")
            return
        await update.message.reply_text(f"✅<code>{clean_addr}</code>\n\n💰 USDT：{usdt:,.2f}\n⚡ TRX：{trx:,.2f}", parse_mode="HTML")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("all", all_command))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(monitor_wallets_task, interval=30, first=1)

    print("🚀 Bot đã khởi chạy thành công...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

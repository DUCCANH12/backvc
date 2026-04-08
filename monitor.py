import requests
import time
import os
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

# ── Cấu hình Environment Variables trên Render ──────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
POLL_INTERVAL      = int(os.environ.get("POLL_INTERVAL", "10"))
COOKIE             = os.environ.get("SHOPEE_COOKIE", "")
CSRF_TOKEN         = os.environ.get("SHOPEE_CSRF", "")

# ── Thông tin voucher — thay bằng voucher bạn muốn theo dõi ─────────────────
PROMOTION_ID = int(os.environ.get("PROMOTION_ID", "1393156180840448"))
VOUCHER_CODE = os.environ.get("VOUCHER_CODE", "SVIPBUNDLE08APR")
SIGNATURE    = os.environ.get("SIGNATURE", "b9a024bc0634fbd93b9956e9c588d9f86b1829611dac2e539536564bc46f97c7")

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "x-api-source": "pc",
    "x-requested-with": "XMLHttpRequest",
    "x-shopee-language": "vi",
    "x-csrftoken": CSRF_TOKEN,
    "referer": f"https://shopee.vn/voucher/details?action=okay&from_source=vlp&promotionId={PROMOTION_ID}&signature={SIGNATURE}&source=0",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "cookie": COOKIE,
}

PAYLOAD = {
    "promotionid": PROMOTION_ID,
    "voucher_code": VOUCHER_CODE,
    "signature": SIGNATURE,
    "need_basic_info": True,
    "need_user_voucher_status": True,
    "source": "0",
    "addition": []
}

# ── Trạng thái dùng để hiển thị trên web ────────────────────────────────────
status = {
    "last_check": "chưa có",
    "left_count": "?",
    "percentage_used": "?",
    "fully_used": "?",
    "end_time": "?",
    "alerts": 0,
}

# Cờ chỉ gửi cảnh báo hết hạn 1 lần
warned_expiry = False


# ── HTTP Server — giữ Render Web Service sống ────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = f"""<!DOCTYPE html>
        <html><body style="font-family:sans-serif;padding:20px;max-width:500px">
        <h2>🟢 Shopee Voucher Monitor</h2>
        <table border="1" cellpadding="8" style="border-collapse:collapse;width:100%">
          <tr><td>Voucher</td><td><b>{VOUCHER_CODE}</b></td></tr>
          <tr><td>Lần check cuối</td><td><b>{status['last_check']}</b></td></tr>
          <tr><td>Còn lại (left_count)</td><td><b>{status['left_count']}</b></td></tr>
          <tr><td>% đã dùng</td><td><b>{status['percentage_used']}%</b></td></tr>
          <tr><td>Hết lượt?</td><td><b>{status['fully_used']}</b></td></tr>
          <tr><td>HSD</td><td><b>{status['end_time']}</b></td></tr>
          <tr><td>Tổng alerts đã gửi</td><td><b>{status['alerts']}</b></td></tr>
        </table>
        </body></html>"""
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    log.info(f"HTTP server chạy trên port {port}")
    server.serve_forever()


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Chưa cấu hình Telegram!")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
        status["alerts"] += 1
    except Exception as e:
        log.error(f"Telegram error: {e}")


# ── Gọi API Shopee ────────────────────────────────────────────────────────────
def get_voucher_info():
    try:
        r = requests.post(
            "https://shopee.vn/api/v2/voucher_wallet/get_voucher_detail",
            headers=HEADERS,
            json=PAYLOAD,
            timeout=15
        )
        data = r.json()

        if data.get("error") != 0:
            log.warning(f"API error: {data.get('error_msg')}")
            return None

        basic = data["data"]["voucher_basic_info"]

        return {
            "left_count":       basic.get("left_count", 0),          # lượt còn lại ← field chính
            "percentage_used":  basic.get("percentage_used", 0),     # % đã dùng
            "percentage_claimed": basic.get("percentage_claimed", 0),
            "fully_used":       basic.get("fully_used", True),        # True = hết lượt
            "fully_claimed":    basic.get("fully_claimed", False),
            "fully_redeemed":   basic.get("fully_redeemed", False),
            "end_time":         basic.get("end_time", 0),             # unix timestamp HSD
            "discount_percentage": basic.get("discount_percentage", 0),
            "discount_cap":     basic.get("discount_cap", 0),        # đơn vị nano-đồng ÷ 100000
        }
    except Exception as e:
        log.error(f"Request error: {e}")
        return None


# ── Monitor loop ──────────────────────────────────────────────────────────────
def monitor_loop():
    global warned_expiry
    log.info("🚀 Monitor started")
    send_telegram(
        f"🚀 <b>Shopee Monitor bắt đầu chạy</b>\n"
        f"Voucher: <code>{VOUCHER_CODE}</code>\n"
        f"Poll mỗi {POLL_INTERVAL}s"
    )

    prev_left = None

    while True:
        info = get_voucher_info()

        if info is None:
            time.sleep(POLL_INTERVAL)
            continue

        left        = info["left_count"]
        pct_used    = info["percentage_used"]
        fully_used  = info["fully_used"]
        end_ts      = info["end_time"]
        now         = datetime.now()
        now_str     = now.strftime("%H:%M:%S")
        end_str     = datetime.fromtimestamp(end_ts).strftime("%d/%m/%Y %H:%M") if end_ts else "?"
        cap_vnd     = info["discount_cap"] // 100000  # nano-đồng → đồng

        # Cập nhật status cho web
        status["last_check"]     = now_str
        status["left_count"]     = left
        status["percentage_used"] = pct_used
        status["fully_used"]     = fully_used
        status["end_time"]       = end_str

        log.info(f"[{now_str}] left_count={left} | %used={pct_used} | fully_used={fully_used}")

        # ── Phát hiện BACK LƯỢT ──────────────────────────────────────────────
        if prev_left is not None:
            if left > prev_left:
                diff = left - prev_left
                msg = (
                    f"🔥 <b>BACK LƯỢT SHOPEE!</b>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"Voucher: <code>{VOUCHER_CODE}</code>\n"
                    f"➕ Thêm <b>{diff}</b> lượt mới\n"
                    f"📦 Còn lại: <b>{left}</b> lượt\n"
                    f"🏷 Giảm: <b>{info['discount_percentage']}%</b> tối đa <b>{cap_vnd:,}đ</b>\n"
                    f"⏰ {now_str} | HSD: {end_str}\n\n"
                    f"👉 https://shopee.vn/voucher/details?promotionId={PROMOTION_ID}&signature={SIGNATURE}&source=0"
                )
                log.info(f"🔥 BACK LƯỢT! {prev_left} → {left} (+{diff})")
                send_telegram(msg)

            elif left == 0 and prev_left > 0:
                log.info("⚠️ Hết lượt")
                send_telegram(
                    f"⚠️ Voucher <code>{VOUCHER_CODE}</code> vừa HẾT lượt lúc {now_str}"
                )

        prev_left = left

        # ── Cảnh báo sắp hết hạn (còn < 1 tiếng, chỉ báo 1 lần) ────────────
        if end_ts and not warned_expiry:
            secs_left = end_ts - time.time()
            if 0 < secs_left < 3600:
                warned_expiry = True
                mins = int(secs_left // 60)
                send_telegram(
                    f"⏳ <b>Voucher sắp hết hạn!</b>\n"
                    f"<code>{VOUCHER_CODE}</code> còn <b>{mins} phút</b>\n"
                    f"HSD: {end_str}"
                )

        # Poll dày hơn trước mốc giờ chẵn (phút 58-59 và 00-02)
        minute   = now.minute
        interval = 2 if (minute >= 58 or minute <= 2) else POLL_INTERVAL
        time.sleep(interval)


if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    run_server()

import requests
import time
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger(__name__)

# ── Cấu hình (đặt trong Environment Variables trên Render) ──────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
POLL_INTERVAL      = int(os.environ.get("POLL_INTERVAL", "10"))   # giây
COOKIE             = os.environ.get("SHOPEE_COOKIE", "")
CSRF_TOKEN         = os.environ.get("SHOPEE_CSRF", "")

# ── Thông tin voucher (lấy từ curl của bạn) ─────────────────────────────────
PROMOTION_ID = 1393156180840448
VOUCHER_CODE = "SVIPBUNDLE08APR"
SIGNATURE    = "b9a024bc0634fbd93b9956e9c588d9f86b1829611dac2e539536564bc46f97c7"

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "x-api-source": "pc",
    "x-requested-with": "XMLHttpRequest",
    "x-shopee-language": "vi",
    "x-csrftoken": CSRF_TOKEN,
    "referer": f"https://shopee.vn/voucher/details?action=okay&evcode=U1ZJUEJVTkRMRTA4QVBS&from_source=vlp&promotionId={PROMOTION_ID}&signature={SIGNATURE}&source=0",
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
    except Exception as e:
        log.error(f"Telegram error: {e}")


def get_voucher_info():
    try:
        r = requests.post(
            "https://shopee.vn/api/v2/voucher_wallet/get_voucher_detail",
            headers=HEADERS,
            json=PAYLOAD,
            timeout=15
        )
        data = r.json()

        if data.get("error"):
            log.warning(f"API error: {data}")
            return None

        d = data.get("data", {})
        basic = d.get("basic_info", d)  # tuỳ response structure

        # Thử các field khác nhau Shopee có thể dùng
        total   = basic.get("total_quota") or basic.get("stock") or basic.get("total_usage_limit", 0)
        used    = basic.get("current_usage") or basic.get("used_count") or basic.get("total_redeemed_item", 0)
        remaining = basic.get("remaining_quota") or (total - used) if total else None

        return {
            "total": total,
            "used": used,
            "remaining": remaining,
            "raw": data  # để debug lần đầu
        }
    except Exception as e:
        log.error(f"Request error: {e}")
        return None


def main():
    log.info("🚀 Shopee Voucher Monitor started")
    send_telegram(f"🚀 <b>Monitor bắt đầu chạy</b>\nVoucher: <code>{VOUCHER_CODE}</code>\nPoll mỗi {POLL_INTERVAL}s")

    prev_remaining = None
    first_run = True

    while True:
        info = get_voucher_info()

        if info is None:
            log.warning("Không lấy được data, thử lại...")
            time.sleep(POLL_INTERVAL)
            continue

        remaining = info["remaining"]
        total     = info["total"]
        used      = info["used"]
        now       = datetime.now().strftime("%H:%M:%S")

        log.info(f"[{now}] Còn lại: {remaining} / Tổng: {total} / Đã dùng: {used}")

        # Lần đầu: in raw để biết structure
        if first_run:
            log.info(f"RAW RESPONSE: {info['raw']}")
            first_run = False

        # Phát hiện back lượt: remaining tăng so với lần trước
        if prev_remaining is not None and remaining is not None:
            if remaining > prev_remaining:
                diff = remaining - prev_remaining
                msg = (
                    f"🔥 <b>BACK LƯỢT SHOPEE!</b>\n"
                    f"Voucher: <code>{VOUCHER_CODE}</code>\n"
                    f"➕ Thêm <b>{diff}</b> lượt\n"
                    f"📦 Còn lại: <b>{remaining}</b> / {total}\n"
                    f"⏰ {now}\n\n"
                    f"👉 https://shopee.vn/voucher/details?promotionId={PROMOTION_ID}&signature={SIGNATURE}&source=0"
                )
                log.info(f"🔥 BACK LƯỢT! +{diff}")
                send_telegram(msg)

            elif remaining == 0 and prev_remaining > 0:
                send_telegram(f"⚠️ Voucher <code>{VOUCHER_CODE}</code> đã HẾT lượt lúc {now}")

        prev_remaining = remaining

        # Poll dày hơn trước các mốc giờ chẵn (58-59 phút và 00-02 phút)
        minute = datetime.now().minute
        interval = 2 if (minute >= 58 or minute <= 2) else POLL_INTERVAL
        time.sleep(interval)


if __name__ == "__main__":
    main()

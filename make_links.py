from __future__ import annotations

import argparse
import base64
import csv
import hmac
import hashlib
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime, timezone
from typing import List, Sequence, cast, BinaryIO

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def sign_link(key: bytes, sid: str, exp_ts: int) -> str:
    msg = f"{sid}|{exp_ts}".encode("utf-8")
    mac = hmac.new(key, msg, hashlib.sha256).digest()
    return b64url(mac)

def load_subjects(csv_path: Path) -> List[str]:
    with csv_path.open("r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        fn_raw: Sequence[str] | None = rdr.fieldnames
        fieldnames: List[str] = cast(List[str], list(fn_raw) if fn_raw is not None else [])
        if "sid" not in fieldnames:
            raise SystemExit("subjects.csv 需要包含列名 'sid'")
        sids: List[str] = []
        for row in rdr:
            sid = (row.get("sid") or "").strip()
            if sid:
                sids.append(sid)
        return sids

def main() -> int:
    parser = argparse.ArgumentParser(description="批量生成被试专属链接（默认一年有效）")
    parser.add_argument("--subjects", type=Path, default=Path("subjects.csv"), help="CSV（至少包含 sid 列）")
    parser.add_argument("--out", type=Path, default=Path("links.csv"), help="输出 CSV 文件")
    parser.add_argument("--days", type=int, default=365, help="有效期（天），默认 365")
    parser.add_argument("--app-url", type=str, default=os.environ.get("APP_URL", ""), help="或设 APP_URL 环境变量")
    parser.add_argument("--key", type=str, default=os.environ.get("LINK_SIGNING_KEY", ""), help="或设 LINK_SIGNING_KEY")
    parser.add_argument("--qr-dir", type=Path, default=None, help="可选：输出二维码目录（需安装 qrcode）")
    args = parser.parse_args()

    if not args.app_url:
        raise SystemExit("缺少 APP_URL（可用 --app-url 指定，或设置环境变量 APP_URL）")
    if not args.key:
        raise SystemExit("缺少 LINK_SIGNING_KEY（可用 --key 指定，或设置环境变量 LINK_SIGNING_KEY）")

    sids = load_subjects(args.subjects)
    if not sids:
        raise SystemExit(f"{args.subjects} 中没有有效的 sid")

    key_bytes = args.key.encode("utf-8")
    now = int(time.time())
    exp_ts = now + args.days * 24 * 3600
    expire_iso_utc = (
        datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    rows: List[dict] = []
    base = args.app_url.rstrip("/")

    for sid in sids:
        sig = sign_link(key_bytes, sid, exp_ts)
        qs = urlencode({"sid": sid, "exp": exp_ts, "sig": sig})
        link = f"{base}/?{qs}"
        rows.append(
            {"sid": sid, "exp_unix": exp_ts, "expire_at_utc": expire_iso_utc, "link": link}
        )

    # 输出 CSV
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sid", "exp_unix", "expire_at_utc", "link"])
        w.writeheader()
        w.writerows(rows)

    print(f"生成 {len(rows)} 条链接 -> {args.out}（统一过期：{expire_iso_utc}）")

    # 可选二维码
    if args.qr_dir is not None:
        try:
            import qrcode  
        except Exception:
            print("未安装 qrcode，跳过二维码生成。需要可执行：pip install \"qrcode[pil]\"",
                  file=sys.stderr)
        else:
            args.qr_dir.mkdir(parents=True, exist_ok=True)
            for row in rows:
                qr = qrcode.QRCode(border=2, box_size=8)  # type: ignore
                qr.add_data(row["link"])
                qr.make(fit=True)
                img = qr.make_image()  # type: ignore
                out_path = args.qr_dir / f"{row['sid']}.png"
                with out_path.open("wb") as fp:  
                    img.save(fp)  # type: ignore
            print(f"二维码已输出至 {args.qr_dir}/")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

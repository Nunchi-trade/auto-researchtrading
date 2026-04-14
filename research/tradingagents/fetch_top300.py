"""
CoinGecko API로 시가총액 기준 상위 N개 알트코인 목록 반환.
스테이블코인(USDT, USDC, DAI 등) 제외.
"""
import os
import time
import requests

COINGECKO_URL = "https://api.coingecko.com/api/v3"

STABLECOIN_IDS = {
    "tether", "usd-coin", "dai", "binance-usd", "true-usd",
    "usdd", "frax", "pax-dollar", "gemini-dollar", "terra-usd",
    "terrausd", "nusd", "first-digital-usd", "paypal-usd",
}

EXCLUDE_CATEGORIES = {"stablecoins"}


def fetch_top_altcoins(n: int = 300) -> list[dict]:
    """시가총액 기준 상위 n개 알트코인 반환 (BTC, ETH, 스테이블코인 제외).

    Returns:
        list of {"id", "symbol", "name", "market_cap", "current_price"}
    """
    api_key = os.getenv("COINGECKO_API_KEY", "")
    headers = {"x-cg-demo-api-key": api_key} if api_key else {}

    results: list[dict] = []
    page = 1
    per_page = 250

    while len(results) < n + 20:  # 제외 항목 여유분 확보
        resp = requests.get(
            f"{COINGECKO_URL}/coins/markets",
            headers=headers,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": page,
                "sparkline": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        results.extend(data)
        page += 1
        if len(data) < per_page:
            break
        time.sleep(0.5)

    altcoins = [
        {
            "id": c["id"],
            "symbol": c["symbol"].upper(),
            "name": c["name"],
            "market_cap": c.get("market_cap") or 0,
            "current_price": c.get("current_price") or 0,
        }
        for c in results
        if c["id"] not in STABLECOIN_IDS
        and "usd" not in c["symbol"].lower()
        and c["id"] not in {"bitcoin", "ethereum"}
    ]

    return altcoins[:n]


if __name__ == "__main__":
    coins = fetch_top_altcoins(int(os.getenv("TOP_N_COINS", "300")))
    print(f"상위 {len(coins)}개 알트코인 로드 완료")
    for rank, coin in enumerate(coins[:10], 1):
        print(f"  {rank:3d}. {coin['symbol']:10s} {coin['name']}")
    print("  ...")

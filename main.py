#!/usr/bin/env python3
"""
Bot SOL - Trading automatisé avec buy/sell sur Gate.io
Version corrigée - Vente rentable
"""

import os
import time
import requests
from datetime import datetime
import http.server
import threading

# === CONFIGURATION ===
GATEIO_API_KEY = os.getenv('GATEIO_API_KEY')
GATEIO_API_SECRET = os.getenv('GATEIO_API_SECRET')
PAIR = "SOL/USDT"
TIMEFRAME = "15m"
ALLOCATION_USDT = 0.20  # 20% du solde pour chaque achat
RSI_BUY_THRESHOLD = 30
MIN_PROFIT_PERCENT = 0.5  # Seuil de profit minimum (0.5%)
RESERVE_USDT = 5  # Réserve minimale en USDT

# === GATE.IO API ===
BASE_URL = "https://api.gateio.ai"

def gate_request(method, path, signed=False):
    """Effectue une requête à l'API Gate.io"""
    url = BASE_URL + path
    headers = {"key": GATEIO_API_KEY} if signed else {}
    if signed:
        import hmac
        import hashlib
        timestamp = str(int(time.time()))
        message = timestamp + method + path
        signature = hmac.new(GATEIO_API_SECRET.encode(), message.encode(), hashlib.sha512).hexdigest()
        headers["timestamp"] = timestamp
        headers["sign"] = signature
    response = requests.request(method, url, headers=headers)
    return response.json()

# === INDICATEURS TECHNIQUES ===
def calculate_rsi(prices, period=14):
    """Calcule le RSI"""
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """Calcule le MACD"""
    if len(prices) < slow + signal:
        return 0, 0
    ema_fast = sum(prices[-fast:]) / fast
    ema_slow = sum(prices[-slow:]) / slow
    macd_line = ema_fast - ema_slow
    signal_line = macd_line  # Simplifié
    return macd_line, signal_line

# === FONCTIONS DE TRADING ===
def get_spot_balance():
    """Récupère le solde spot USDT et SOL"""
    try:
        data = gate_request("GET", "/api/v4/spot/accounts", signed=True)
        usdt_balance = 0
        sol_balance = 0
        for acc in data:
            if acc.get("currency") == "USDT":
                usdt_balance = float(acc.get("available", 0))
            elif acc.get("currency") == "SOL":
                sol_balance = float(acc.get("available", 0))
        return usdt_balance, sol_balance
    except Exception as e:
        print(f"[ERROR] Erreur lors de la récupération du solde: {e}")
        return 0, 0

def get_current_price():
    """Récupère le prix actuel de SOL/USDT"""
    try:
        data = gate_request("GET", "/api/v4/spot/tickers?currency_pair=SOL_USDT")
        return float(data[0]["last"])
    except Exception as e:
        print(f"[ERROR] Erreur prix: {e}")
        return None

def get_ohlcv():
    """Récupère les données OHLCV pour le RSI et MACD"""
    try:
        params = f"?currency_pair=SOL_USDT&interval={TIMEFRAME}&limit=50"
        data = gate_request("GET", f"/api/v4/spot/candles{params}")
        closes = [float(c[2]) for c in data]
        return closes
    except Exception as e:
        print(f"[ERROR] Erreur OHLCV: {e}")
        return []

def get_last_buy_price():
    """Récupère le prix d'achat depuis l'historique des trades"""
    try:
        params = f"?currency_pair=SOL_USDT&side=buy&limit=5"
        data = gate_request("GET", f"/api/v4/spot/trades{params}", signed=True)
        if data and len(data) > 0:
            return float(data[0]["price"])
        return None
    except Exception as e:
        print(f"[ERROR] Erreur historique trades: {e}")
        return None

def get_total_spent():
    """Calcule le montant total dépensé pour les SOL achetés"""
    try:
        trades = gate_request("GET", "/api/v4/spot/trades?currency_pair=SOL_USDT&side=buy&limit=10", signed=True)
        total_spent = 0
        total_sol = 0
        for trade in trades:
            price = float(trade["price"])
            amount = float(trade["amount"])
            total_spent += price * amount
            total_sol += amount
        if total_sol > 0:
            return total_spent, total_sol
        return 0, 0
    except Exception as e:
        print(f"[DEBUG] Erreur calcul spent: {e}")
        return 0, 0

def buy():
    """Execute un achat de SOL"""
    try:
        usdt_balance, _ = get_spot_balance()
        available_usdt = usdt_balance - RESERVE_USDT
        if available_usdt <= 0:
            print("-> Solde insuffisant pour l'achat")
            return False
        buy_amount = available_usdt * ALLOCATION_USDT
        if buy_amount < 10:
            print("-> Montant trop faible pour acheter")
            return False
        price = get_current_price()
        if price is None:
            return False
        quantity = round(buy_amount / price, 4)
        payload = {
            "currency_pair": "SOL_USDT",
            "side": "buy",
            "type": "market",
            "amount": str(quantity)
        }
        result = gate_request("POST", "/api/v4/spot/orders", signed=True)
        if "id" in result:
            print(f"-> ACHAT EXECUTE: {quantity} SOL à ${price}")
            return True
        else:
            print(f"-> ERREUR achat: {result}")
            return False
    except Exception as e:
        print(f"-> ERREUR achat: {e}")
        return False

def sell():
    """Execute une vente de SOL"""
    try:
        _, sol_balance = get_spot_balance()
        if sol_balance < 0.001:
            print("-> Solde SOL insuffisant")
            return False
        price = get_current_price()
        if price is None:
            return False
        # Calcul du profit avec les frais (0.2% par transaction)
        total_spent, total_sol = get_total_spent()
        if total_sol > 0:
            avg_buy_price = total_spent / total_sol
            profit_percent = ((price - avg_buy_price) / avg_buy_price) * 100
            # Soustraire les frais (0.2% achat + 0.2% vente = 0.4%)
            net_profit = profit_percent - 0.4
            profit_value = (price - avg_buy_price) * sol_balance
            print(f" -> Profit calculé: {net_profit:.2f}% (net après frais)")
            if net_profit >= MIN_PROFIT_PERCENT:
                quantity = round(sol_balance, 4)
                payload = {
                    "currency_pair": "SOL_USDT",
                    "side": "sell",
                    "type": "market",
                    "amount": str(quantity)
                }
                result = gate_request("POST", "/api/v4/spot/orders", signed=True)
                if "id" in result:
                    print(f"-> VENTE EXECUTE: {quantity} SOL à ${price} | Profit: +{profit_value:.2f}$")
                    return True
                else:
                    print(f"-> ERREUR vente: {result}")
                    return False
            else:
                print(f" -> Vente ANNULEE: Profit net {net_profit:.2f}% < {MIN_PROFIT_PERCENT}%")
                return False
        else:
            print("-> Impossible de calculer le profit (pas d'historique)")
            return False
    except Exception as e:
        print(f"-> ERREUR vente: {e}")
        return False

def should_sell():
    """Vérifie si les conditions de vente sont réunies"""
    try:
        closes = get_ohlcv()
        if len(closes) < 30:
            return False, 0
        rsi = calculate_rsi(closes)
        macd, signal = calculate_macd(closes)
        # Signal de vente: RSI > 60 et MACD négatif
        if rsi > 60 and macd < signal:
            return True, rsi
        return False, rsi
    except Exception as e:
        print(f"[ERROR] Erreur should_sell: {e}")
        return False, 0

def should_buy():
    """Vérifie si les conditions d'achat sont réunies"""
    try:
        closes = get_ohlcv()
        if len(closes) < 30:
            return False, 50
        rsi = calculate_rsi(closes)
        return rsi < RSI_BUY_THRESHOLD, rsi
    except Exception as e:
        print(f"[ERROR] Erreur should_buy: {e}")
        return False, 50

def run():
    """Boucle principale du bot"""
    print("=" * 60)
    print("Bot SOL - Mode 3 minutes")
    print(f"Paire: {PAIR}")
    print(f"Seuil d'achat RSI: < {RSI_BUY_THRESHOLD}")
    print(f"Seuil de profit NET: {MIN_PROFIT_PERCENT}% (après frais)")
    print("=" * 60)
    while True:
        try:
            price = get_current_price()
            if price is None:
                time.sleep(180)
                continue
            usdt_balance, sol_balance = get_spot_balance()
            closes = get_ohlcv()
            rsi = calculate_rsi(closes) if len(closes) >= 15 else 50
            macd, signal = calculate_macd(closes) if len(closes) >= 35 else (0, 0)
            timestamp = datetime.now().strftime("%H:%M:%S")
            if sol_balance > 0.001:
                total_spent, total_sol = get_total_spent()
                if total_sol > 0:
                    avg_price = total_spent / total_sol
                    profit_pct = ((price - avg_price) / avg_price) * 100 - 0.4
                    min_sell = avg_price * (1 + MIN_PROFIT_PERCENT / 100)
                    print(f"{timestamp} | Prix: ${price:.2f}")
                    print(f" Solde USDT: {usdt_balance:.2f} | SOL: {sol_balance:.4f}")
                    print(f" -> Position: Acheté à ${avg_price:.2f} | Profit: {profit_pct:.2f}% | Cible: ${min_sell:.2f}")
                    sell_signal, rsi_val = should_sell()
                    print(f" RSI: {rsi:.1f} | MACD: {macd:.2f} (signal: {signal:.2f})")
                    if sell_signal and profit_pct >= MIN_PROFIT_PERCENT:
                        sell()
                else:
                    print(f"{timestamp} | Prix: ${price:.2f}")
                    print(f" Solde USDT: {usdt_balance:.2f} | SOL: {sol_balance:.4f} -> En attente")
                    print(f" RSI: {rsi:.1f} | MACD: {macd:.2f} (signal: {signal:.2f})")
            else:
                print(f"{timestamp} | Prix: ${price:.2f}")
                print(f" Solde USDT: {usdt_balance:.2f} | SOL: 0.0000")
                buy_signal, rsi_val = should_buy()
                print(f" RSI: {rsi:.1f} | MACD: {macd:.2f} (signal: {signal:.2f})")
                if buy_signal:
                    buy()
        except Exception as e:
            print(f"[ERROR] Erreur boucle principale: {e}")
        time.sleep(180)

# === SERVEUR WEB MINIMAL ===
class MinimalHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args):
        pass

def start_server():
    server = http.server.HTTPServer(("0.0.0.0", 8080), MinimalHandler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()
    run()

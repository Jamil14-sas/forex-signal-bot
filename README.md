# Forex Signal Bot

A Telegram bot that analyzes forex markets using programmatic technical analysis
and market sentiment to generate trading signals.

## Features

- **Live forex data** — OANDA API (primary) with Yahoo Finance fallback
- **Technical indicators** — SMA, RSI, MACD, Bollinger Bands, Smart Money Concepts (BOS, FVG, Order Blocks)
- **Market sentiment** — News headlines sentiment (VADER) + economic calendar risk scoring
- **Trading signals** — Weighted confluence scoring with entry, stop loss, and take profit levels
- **Beautiful output** — Telegram HTML formatting with emoji, confidence bars, and structured analysis

## Supported Pairs

EUR/USD, GBP/USD, USD/JPY, AUD/USD, NZD/USD, USD/CAD, USD/CHF, EUR/GBP, EUR/JPY,
GBP/JPY, EUR/CHF, AUD/JPY, NZD/JPY, GBP/AUD, GBP/CAD, EUR/AUD, EUR/CAD, AUD/CAD,
AUD/NZD, NZD/CAD, USD/SGD, USD/HKD, EUR/NZD, GBP/NZD, USD/NOK, USD/SEK, USD/MXN, USD/ZAR

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN (from @BotFather)
# Add OANDA_API_KEY for forex data (optional, falls back to yfinance)
# Add NEWS_API_KEY for sentiment (optional)

# 3. Run
python -m forex_signal.main
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Full command reference |
| `/signal <pair>` | Trading signal with entry/SL/TP |
| `/analysis <pair>` | Full technical analysis |
| `/multianalysis <pair>` | Multi-timeframe analysis (3 TFs) |
| `/sentiment <pair>` | News & event sentiment |
| `/pairs` | List all currency pairs |
| `/timeframe <tf>` | Set timeframe (5m, 15m, 1h, 4h, 1d) |
| `/history` | Recent signal history |
| `/stats` | Signal win rate statistics |
| `/resolve won/lost <id>` | Mark signal outcome |
| `/subscribe [time] [pairs]` | Daily scheduled signal broadcasts |
| `/unsubscribe` | Cancel scheduled signals |
| `/mytime HH:MM` | Change broadcast time (UTC) |
| `/mypairs pair1,pair2` | Change tracked pairs |

## Architecture

```
forex-signal-bot/src/forex_signal/
├── main.py              # Bot entry point
├── config.py            # Pydantic settings
├── db/                  # Database layer (SQLAlchemy async)
│   ├── base.py          #   Engine, session factory, init/close
│   ├── models.py        #   ORM models (User, SignalRecord, Subscription)
│   └── repository.py    #   CRUD operations
├── scheduler/           # Scheduled signal broadcasts
│   └── broadcast.py     #   Auto-analyze & send to subscribers
├── services/
│   ├── data_service.py  # OANDA + yfinance data fetching
│   ├── indicators.py    # Technical indicators + SMC
│   ├── signal_service.py # Weighted signal gen + risk mgmt
│   ├── sentiment.py     # News + economic calendar
│   ├── analysis_service.py # Orchestrator + multi-tf analysis
│   └── formatter.py     # Telegram HTML formatting + risk display
└── bot/
    └── handlers.py      # aiogram command handlers (DB-backed)
```

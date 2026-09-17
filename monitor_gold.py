#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金 AU2612 第一层风险监控（免费数据：PandaAI CLI + AkShare/新浪）。
输出：第一行 LEVEL=<NONE|INFO|WARN|DANGER|ERROR>，其后为 Markdown 简报。
用法：
  python3 monitor_gold.py          # 扫描模式：仅 WARN/DANGER/ERROR 需推送
  python3 monitor_gold.py --brief  # 收盘简报：强制输出 INFO 简报
规则依据《新手操作与风控手册》：单笔风险 1%，浮亏达风险预算 50%/80%/100% 分级。
本脚本只读，不下单、不撤单；任何平仓动作必须用户手动确认。
"""
import subprocess, json, sys, datetime
from report_core import number, prepare_history, atr14, position_size

CONTRACT = "AU2612"
MULT = 1000          # 黄金合约乘数 1000 克/手
RISK_PCT = 0.01      # 单笔风险预算 1%

def panda(args):
    try:
        r = subprocess.run(["panda"] + args + ["--json"], capture_output=True,
                           text=True, timeout=40)
        j = json.loads(r.stdout)
        return j.get("data") if j.get("ok") else None
    except Exception:
        return None

def get_atr():
    """用 AkShare 日 K 算 ATR(14)，失败返回 None。"""
    try:
        import akshare as ak
        d = ak.futures_zh_daily_sina(symbol=CONTRACT).rename(columns={
            'date':'日期','open':'开盘价','high':'最高价','low':'最低价','close':'收盘价'})
        return atr14(prepare_history(d))
    except Exception:
        return None

def pick(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default

def main():
    force_brief = "--brief" in sys.argv
    now = datetime.datetime.now()
    acct = panda(["account"])
    positions = panda(["positions"])
    if not isinstance(acct, dict) or not isinstance(positions, list):
        print("LEVEL=ERROR")
        print("账户或持仓查询失败，当前持仓未知；停止生成账户风险结论。")
        return
    q = panda(["quote", CONTRACT])
    atr = get_atr()

    if not q or not q.get("ready"):
        print("LEVEL=ERROR")
        print(f"⚠️ 黄金监控：无法获取 {CONTRACT} 有效行情（PandaAI 行情通道异常或当前休市）。"
              f"请人工打开行情核对；账户/持仓命令需在云电脑复查。时间 {now:%Y-%m-%d %H:%M}")
        return

    if any(number(q.get(k), True) is None for k in ('latestPrice','preclose','limitUp','limitDown')):
        print("LEVEL=ERROR\n行情关键字段缺失，停止风险计算。")
        return
    last = float(q["latestPrice"])
    pre = float(q.get("preclose") or 0)
    up, dn = float(q.get("limitUp") or 0), float(q.get("limitDown") or 0)
    chg = float(q.get("change") or (last - pre if pre else 0))
    chg_pct = float(q.get("changeRate") or (chg / pre if pre else 0))
    hi, lo = float(q.get("high") or last), float(q.get("low") or last)
    oi = q.get("openInterest")
    dist_up = (last - dn) / (up - dn) if up > dn else 0.5      # 距跌停 0 / 距涨停 1
    amp = (hi - lo) / pre if pre else 0

    # Only an explicit equity field is accepted. Do not guess its meaning from available funds.
    equity = number(acct.get('equity'), True)
    if equity is None:
        print("LEVEL=ERROR\n未取得明确的 equity 权益字段；请核对柜台字段映射，不能用500万元代替实际权益。")
        return
    risk_budget = equity * RISK_PCT

    # 解析黄金持仓（防御性：字段名随柜台可能不同）
    gold_pos = None
    matches = []
    if isinstance(positions, list):
        for p in positions:
            code = str(pick(p, "contractCode", "symbol", "instrumentId", default="")).upper()
            if code.startswith("AU"):
                if code != CONTRACT:
                    print(f"LEVEL=ERROR\n存在其他黄金合约 {code}，不能用 {CONTRACT} 价格计算其盈亏。")
                    return
                matches.append(p)
    if len(matches)>1:
        print("LEVEL=ERROR\n同合约存在多条持仓，尚未完成逐笔归并，停止输出简化盈亏。")
        return
    gold_pos = matches[0] if matches else None

    level, head, lines = "NONE", "", []

    if gold_pos:
        vol = pick(gold_pos, "volume", "position", "totalVolume", "total", default=0)
        side = str(pick(gold_pos, "direction", "side", "posSide", default=""))
        open_px = number(pick(gold_pos, "openPrice", "avgPrice"), True)
        if side.upper() not in ('多','空','LONG','SHORT','BUY','SELL') or open_px is None or number(vol,True) is None:
            print("LEVEL=ERROR\n持仓方向、均价或数量不可识别，停止猜测盈亏。")
            return
        sign = -1 if side.upper() in ('空','SHORT','SELL') else 1
        pnl = sign * (last - open_px) * MULT * float(vol or 0)
        ratio = abs(pnl) / risk_budget if pnl < 0 else 0
        lines += [f"持仓：{CONTRACT} {side} {vol} 手，开仓均价 {open_px:.2f}，现价 {last:.2f}",
                  f"浮动{'亏损' if pnl < 0 else '盈利'} {pnl:,.0f} 元（风险预算 {risk_budget:,.0f} 元的 {ratio*100:.0f}%）"]
        if ratio >= 1.0 or dist_up <= 0.03 or dist_up >= 0.97:
            level, head = "DANGER", "🛑 黄金风险·危险（触及止损预算/逼近涨跌停）"
        elif ratio >= 0.8:
            level, head = "WARN", "🟠 黄金风险·警告（浮亏达风险预算 80%）"
        elif ratio >= 0.5:
            level, head = "INFO", "🟡 黄金风险·关注（浮亏达风险预算 50%）"
        else:
            head = "🟢 黄金持仓·正常"
    else:
        # 无持仓：开仓前观察 + 异常波动提示
        sizing = position_size(last, 1.5*atr if atr else None, MULT, equity)
        lines += [f"最新价 {last:.2f}（{chg:+.2f}，{chg_pct*100:+.2f}%），今开 {float(q.get('open') or 0):.2f}，"
                  f"高 {hi:.2f} / 低 {lo:.2f}，持仓量 {oi}",
                  f"涨跌停区间 {dn:.2f} ~ {up:.2f}；当前位于区间 {dist_up*100:.0f}% 处"]
        if atr:
            lines.append(f"ATR(14)≈{atr:.2f} 元/克（约 {atr*MULT:,.0f} 元/手·日）；"
                         f"1%预算 {risk_budget:,.0f} 元，1.5×ATR 与10%敞口约束下参考上限 {sizing['lots']} 手；乘数按1000克/手假设")
        # 异常波动：已走出涨跌停幅度 70%，或当日振幅显著大于 ATR
        midpoint = (up+dn)/2
        limit_fraction = (up-dn)/2/midpoint if up>dn and midpoint>0 else None
        abnormal = (limit_fraction and abs(chg_pct) >= .7*limit_fraction) or (atr and amp >= 1.5*atr/last)
        if abnormal:
            level, head = "WARN", "🟠 黄金异常波动（无持仓，今日勿追单，谨慎开仓）"
        elif force_brief or (15 <= now.hour < 16):
            level, head = "INFO", "🔔 黄金收盘小结（无持仓）"
        else:
            head = "黄金盯盘（无持仓）"

    print(f"LEVEL={level}")
    print(f"### {head}")
    print(f"时间 {now:%Y-%m-%d %H:%M}（行情日 {q.get('tradeDate')} {q.get('time')}）")
    for x in lines:
        print("- " + x)
    if level in ("WARN", "DANGER"):
        print("- 提醒：本消息为客观风险预警，不构成买卖建议；是否平仓/离场请你手动确认后操作。")

if __name__ == "__main__":
    main()

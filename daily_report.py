"""Collect, archive, replay and publish local evidence-backed reports. No remote writes."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd
from market_config import WATCH, SECTOR
from report_core import build_dataset, number
from report_writer import render_report

ROOT = Path(__file__).resolve().parent


def now():
    return dt.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def panda(args):
    try:
        result = subprocess.run(["panda", *args, "--json"], capture_output=True, text=True,
                                encoding="utf-8", timeout=40)
        obj = json.loads(result.stdout)
        return obj.get("data") if result.returncode == 0 and obj.get("ok") else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def fetch_worker(kind, symbol, date, destination):
    # Executed in a bounded subprocess because the provider's requests have no timeout.
    try:
        frame = ak.futures_rule(date=date.replace("-", "")) if kind == "rules" else ak.futures_main_sina(
            symbol=symbol, start_date=(pd.Timestamp(date)-pd.DateOffset(months=18)).strftime('%Y%m%d'),
            end_date=date.replace("-", ""))
        if frame.empty:
            raise ValueError("empty provider response")
        frame.to_csv(destination, index=False, encoding="utf-8-sig")
        return 0
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        return 1


def collect(date, watch, base, timeout):
    folder = base / "raw" / (now().replace(":", "-") + "-" + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    manifest = {"schema_version": 1, "date": date, "collected_at": now(), "watch": watch,
                "source": "AkShare futures_main_sina / 新浪主力连续", "rule_date_requested": date,
                "history_start_requested": (pd.Timestamp(date)-pd.DateOffset(months=18)).date().isoformat(),
                "rule_source": "AkShare futures_rule / 国泰君安期货交易日历页面（请求日期不等于源站日期已独立核验）",
                "versions": {"python": sys.version.split()[0], "akshare": ak.__version__, "pandas": pd.__version__},
                "files": [], "fetch_issues": [], "code_hashes": {f: digest(ROOT/f) for f in
                    ("daily_report.py", "report_core.py", "report_writer.py", "market_config.py")}}
    jobs = [("rules", "rules")] + [("history", sym) for sym in watch]
    for kind, sym in jobs:
        path = folder / (sym + ".csv")
        started = now()
        try:
            result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT/"daily_report.py"),
                                     "--fetch-worker", kind, sym, date, str(path)],
                                    capture_output=True, timeout=timeout)
            if result.returncode != 0:
                raise ValueError("接口失败：" + result.stderr.decode("utf-8",errors="replace")[-160:].strip())
            pd.read_csv(path)  # Confirm a readable artifact before registering it.
            manifest["files"].append({"kind":kind,"symbol":sym,"path":path.name,"sha256":digest(path),
                                      "started_at":started,"completed_at":now()})
            print(f"[data] {sym} archived", file=sys.stderr)
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            manifest["fetch_issues"].append({"symbol":sym,"reason":str(exc)[:240]})
            print(f"[data] {sym} unavailable", file=sys.stderr)
    write_json(folder/"manifest.json", manifest)
    return folder/"manifest.json"


def read_archive(path):
    path = Path(path).resolve(); manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("不支持的原始档案版本")
    histories, rules = {}, {}
    for item in manifest["files"]:
        file = (path.parent / item["path"]).resolve()
        if file.parent != path.parent or digest(file) != item["sha256"]:
            raise ValueError("原始文件路径或 SHA256 校验失败")
        frame = pd.read_csv(file, encoding="utf-8-sig")
        if item["kind"] == "history": histories[item["symbol"]] = frame
        elif item["kind"] == "rules":
            if "代码" not in frame:
                continue
            for _, row in frame.iterrows():
                rules[str(row["代码"]).strip().upper()] = row.to_dict()
    return manifest, histories, rules


def legacy_dataset(path, equity):
    """Re-express archived summaries; do not fabricate missing indicator evidence."""
    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"date","symbol","name","sector","regime","last","chg_pct","atr"}
    if not required.issubset(frame.columns) or frame.empty or frame['date'].nunique()!=1 or frame['symbol'].duplicated().any():
        raise ValueError("旧快照字段、日期或唯一性检查失败")
    rows=[]
    for r in frame.to_dict("records"):
        if r['regime'] not in ('long','short','flat','unknown') or number(r['last'],True) is None:
            raise ValueError("旧快照分类或价格无效")
        change=number(r['chg_pct'])
        rows.append(dict(symbol=r['symbol'],name=r['name'],sector=r['sector'],last=float(r['last']),
            chg=change/100 if change is not None else None,atr=number(r['atr'],True),side=r['regime'],
            side_prev='unknown',evidence=None,hold_change=None,quadrant='数据不足',lots=None,
            risk_lots=None,exposure_lots=None,binding='unknown',stop_px=None,
            notes=['缺少原始K线、历史规则和持仓变动，仅转述汇总快照']))
    return dict(date=str(frame['date'].iloc[0]),rows=rows,issues=[],expected=len(frame),equity=equity,
                mode='legacy',source=f"仓库历史汇总快照：{Path(path).name}",
                rule_source='未附历史规则，不计算仓位',generated_at=now(),independently_verified=False)


def write_report(data, output):
    output = Path(output); rep = output/'reports'; snap = output/'snapshots'
    rep.mkdir(parents=True,exist_ok=True); snap.mkdir(parents=True,exist_ok=True)
    md, xml, meta = render_report(data)
    # A unique per-run result is retained; latest_meta only points to this run.
    suffix = data['date']+'_'+uuid.uuid4().hex[:8]
    stem = 'review_preview_' if data.get('mode')=='legacy' else 'daily_report_'
    mdpath = rep/(stem+suffix+'.md'); xmlpath = rep/(stem+suffix+'.xml')
    mdpath.write_text(md,encoding='utf-8'); xmlpath.write_text(xml,encoding='utf-8')
    meta.update(markdown_path=str(mdpath),xml_path=str(xmlpath),manifest=data.get('manifest'),
                generated_at=data.get('generated_at'),equity_assumption=data['equity'],
                calculation_code_hashes={f:digest(ROOT/f) for f in ('daily_report.py','report_core.py','report_writer.py','market_config.py')},
                publish_ready=False,
                publication_note='尚未独立核验行情；需审阅数据状态后决定是否分享')
    write_json(rep/('meta_'+suffix+'.json'),meta); write_json(rep/'latest_meta.json',meta)
    pd.DataFrame([dict(date=data['date'],symbol=r['symbol'],name=r['name'],sector=r['sector'],
                      regime=r['side'],last=r['last'],chg_pct=r['chg']*100 if r['chg'] is not None else None,atr=r['atr'])
                  for r in data['rows']]).to_csv(snap/('regime_'+suffix+'.csv'),index=False,encoding='utf-8-sig')
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--replay',type=Path)
    source.add_argument('--legacy-snapshot',type=Path)
    parser.add_argument('--date',help='Shanghai trading date YYYY-MM-DD; omitted means calendar today')
    parser.add_argument('--symbols',help='Comma-separated subset of configured symbols')
    parser.add_argument('--equity',type=float,default=5_000_000)
    parser.add_argument('--output-dir',type=Path,default=Path(os.environ.get('FUTURES_HOME',ROOT)))
    parser.add_argument('--account',action='store_true',help='Read current Panda positions; never backfill historical state')
    parser.add_argument('--timeout',type=int,default=30,help='Per-provider subprocess timeout seconds')
    args = parser.parse_args(argv)
    if number(args.equity,True) is None or args.timeout <= 0: parser.error('equity and timeout must be positive')
    if args.replay or args.legacy_snapshot:
        if args.date or args.symbols: parser.error('replay/legacy use their recorded date and universe')
    try:
        if args.legacy_snapshot:
            data=legacy_dataset(args.legacy_snapshot,args.equity)
        else:
            if args.replay:
                archive=args.replay
            else:
                date=args.date or now()[:10]; dt.date.fromisoformat(date)
                if date > now()[:10]: raise ValueError('不能请求未来交易日')
                watch=WATCH if not args.symbols else {s:WATCH[s] for s in args.symbols.upper().split(',')}
                archive=collect(date,watch,args.output_dir,args.timeout)
            manifest,histories,rules=read_archive(archive)
            data=build_dataset(histories,rules,manifest['date'],manifest['watch'],SECTOR,args.equity)
            data.update(generated_at=now(),source=manifest['source'],rule_source=manifest['rule_source'],
                        manifest=str(archive.resolve()),collected_at=manifest['collected_at'])
            data['issues'] += [i for i in manifest['fetch_issues'] if i['symbol']=='rules']
            data['date_note']='报告仅选用目标日期日线；未接入交易所日历，也未独立确认源站日线已最终结算。'
        if args.account:
            data['positions']=panda(['positions']); data['account_at']=now()
        meta=write_report(data,args.output_dir)
        print(json.dumps(meta,ensure_ascii=False,allow_nan=False))
        return 0 if data['rows'] else 2
    except (ValueError,KeyError,OSError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--fetch-worker':
        sys.exit(fetch_worker(*sys.argv[2:]))
    sys.exit(main())

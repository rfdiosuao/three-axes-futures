"""Compact view of the same validated calculations used by daily_report."""
from pathlib import Path
import json
import sys
import contextlib
import io
from daily_report import main as report_main
from report_writer import SIDE, BINDING, fmt


def main():
    # Reuse the public parser, collection and full evidence archive.
    with contextlib.redirect_stdout(io.StringIO()) as buffer:
        code = report_main()
    if code != 0:
        print(buffer.getvalue(),end='')
        return code
    meta=json.loads(buffer.getvalue())
    output=Path(meta['markdown_path']).parent.parent
    lines=[f"# 三板斧环境筛选 · {meta['date']}",
           f"证据状态：{meta['evidence_status']}；独立行情核验未完成。假设权益 {fmt(meta['equity_assumption'],0)} 元。",
           f"有效覆盖 {meta['scanned']}/{meta['expected']}；完整依据见 {meta['markdown_path']}。"]
    for r in meta['rows']:
        text=f"- {r['name']}：{SIDE[r['side']]}；连续收盘 {fmt(r['last'])}；ATR {fmt(r['atr'])}。"
        if r['side'] in ('long','short'):
            text+=f"参考手数上限 {fmt(r.get('lots'),0)}，限制来源：{BINDING[r.get('binding','unknown')]}。"
        lines.append(text)
    lines.append('各品种分别测算，不构成组合配置；参考手数不能直接相加。')
    for name in ('three_axes_latest.md','three_axes_brief.md'):
        (output/name).write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    print('\n\n'.join(lines))
    return code


if __name__=='__main__':
    sys.exit(main())

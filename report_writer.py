"""One content tree for Markdown and Feishu XML; no independent prose calculations."""
from collections import Counter
from datetime import date
from html import escape

SIDE = {"long":"多头共振", "short":"空头共振", "flat":"不共振", "unknown":"无法判断"}
BINDING = {"risk":"参考止损风险预算", "exposure":"名义敞口上限", "both":"两项约束", "unknown":"输入不足"}


def fmt(x, digits=2):
    return "未取得" if x is None else f"{x:,.{digits}f}"


def pct(x):
    return "未取得" if x is None else f"{x*100:+.2f}%"


def render_report(data):
    rows = data["rows"]; n = len(rows); legacy = data.get("mode") == "legacy"
    valid_chg = [r for r in rows if r["chg"] is not None]
    up = sum(r["chg"] > 0 for r in valid_chg); down = sum(r["chg"] < 0 for r in valid_chg)
    flat_price = len(valid_chg)-up-down
    counts = Counter(r["side"] for r in rows)
    nonflat_ratio = up/(up+down) if up+down else None
    temp = "无法判断" if counts["unknown"] or len(valid_chg)!=n or not n else (
        "偏多" if counts["long"] > counts["short"] and nonflat_ratio is not None and nonflat_ratio >= .55
        else "偏空" if counts["short"] > counts["long"] and nonflat_ratio is not None and nonflat_ratio <= .45
        else "均衡分化")
    positions = data.get("positions")
    position_status = "unknown" if not isinstance(positions,list) else "empty" if not positions else "present"
    blocks = []
    def h(text, level=2): blocks.append(("h",level,text))
    def p(text): blocks.append(("p",text))
    def table(head, body):
        blocks.append(("table",head,body)) if body else p('本项没有符合条件的记录。')
    h(f"三板斧期市复盘 · {data['date']}", 1)
    p("盘面结构、趋势条件与仓位预算。")
    h("阅读摘要")
    p(f"本次覆盖 {n}/{data['expected']} 个预设品种，取得可计算涨跌幅的样本 {len(valid_chg)} 个。"
      f"其中上涨 {up} 个、下跌 {down} 个、平盘 {flat_price} 个；多头共振 {counts['long']} 个，"
      f"空头共振 {counts['short']} 个，不共振 {counts['flat']} 个，无法判断 {counts['unknown']} 个。"
      f"当前样本的规则标签为“{temp}”。这个标签概括样本结构，不代表下一交易日方向。")
    if n and len(valid_chg)!=n:
        p(f"其中 {n-len(valid_chg)} 个品种缺少同口径涨跌幅，所以暂不生成完整样本的市场温度判断；"
          '它们的均线与ATR若输入完整，仍可正常计算。')
    if legacy:
        p("证据状态：历史快照写作预览。以下数字来自仓库既有 CSV，已按该文件重新汇总；"
          "没有原始 K 线，不能重新验证 ATR、MA10 或历史行情真实性。不得把本预览作为独立核验通过的日报。")
    else:
        p("证据状态：按输入日线执行结构检查与同日筛选。均线证据及风险公式可复算；"
          "行情仅来自单一数据链路，尚未做独立第二来源核验。输入检查通过不等于源站价格已被独立证实。")
    h("一、数据范围与阅读口径")
    table(["项目","本次口径"], [
        ["研究交易日",data["date"]], ["报告生成时间",data.get("generated_at","未记录")],
        ["行情来源",data.get("source","AkShare / 新浪主力连续")],
        ["统计对象",f"预设清单 {data['expected']} 个；有效 {n} 个；排除 {len(data.get('issues',[]))} 个"],
        ["规则与保证金来源",data.get("rule_source","未取得当日规则")],
        ["仓位口径",f"假设权益 {fmt(data['equity'],0)} 元；风险预算 1%；单品种名义敞口上限 10%"],
        ["独立行情核验","尚未完成"], ["原始证据档案",data.get("manifest","无原始档案，仅有汇总快照")]])
    p("主力连续用于观察品种历史，不是一个可直接下单的合约。换月可能带来价格、持仓和指标变化，"
      "本版尚未自动识别换月。涉及具体交易时，应重新核对实际合约、报价单位、最小变动价位与有效规则。")
    if data.get("date_note"): p(data["date_note"])
    h("二、盘面宽度：上涨家数与趋势状态分别说明什么")
    if valid_chg:
        p(f"上涨品种占可计算涨跌幅样本的 {up/len(valid_chg)*100:.1f}%（{up}/{len(valid_chg)}，含平盘）；"
          + (f"剔除平盘后为 {nonflat_ratio*100:.1f}%（{up}/{up+down}）。" if nonflat_ratio is not None else "全部样本平盘，不计算剔除平盘后的占比。")
          + "涨跌幅以本次收盘与前一条日线的结算价比较。前结算价缺失时不改用前收盘价混入同一排行榜。")
    if n:
        p(f"多头与空头共振数量相差 {abs(counts['long']-counts['short'])} 个；"
          f"尚未形成共振的品种占有效样本 {counts['flat']/n*100:.1f}%。"
          "涨跌家数回答当天价格如何变化，共振数量回答多个周期是否同向。"
          "两者方向不同并不矛盾：单日变化可能尚不足以改变周、月均线结构。是否形成延续，需要后续同口径观察。")
    p("市场温度是固定分类规则：多头共振数大于空头，且剔除平盘后的上涨占比不低于55%，记为偏多；"
      "空头数大于多头且该占比不高于45%，记为偏空；其余完整样本记为均衡分化。"
      "有关键指标缺失时不强行定性；覆盖不全时，即使能分类，也只代表已取得的子样本。")
    rebound = [r for r in valid_chg if r['chg']>0 and r['side']=='short']
    pullback = [r for r in valid_chg if r['chg']<0 and r['side']=='long']
    if rebound or pullback:
        p((f"本次有 {len(rebound)} 个上涨品种仍处于空头共振：{'、'.join(r['name'] for r in rebound)}。" if rebound else '')
          + (f"另有 {len(pullback)} 个下跌品种仍处于多头共振：{'、'.join(r['name'] for r in pullback)}。" if pullback else '')
          + '这些是单日变化与多周期状态不同向的实际样本。后续复盘应观察价格变化是否继续累积到足以改变均线条件，而非仅因当天涨跌就更换趋势标签。')
    h("三、板块结构：方向分布与集中程度")
    sectors = {}
    for r in rows: sectors.setdefault(r["sector"],[]).append(r)
    body = []
    for sector, rs in sectors.items():
        changes = [r["chg"] for r in rs if r["chg"] is not None]
        lo = sum(r["side"]=="long" for r in rs); sh = sum(r["side"]=="short" for r in rs)
        avg = sum(changes)/len(changes) if changes else None
        body.append([sector,str(len(rs)),str(sum(x>0 for x in changes)),str(sum(x<0 for x in changes)),
                     str(lo),str(sh),pct(avg),f"{len(changes)}/{len(rs)}"])
    table(["板块","覆盖数","涨","跌","多头","空头","等权平均涨跌","涨跌有效数"],body)
    for direction, label in (('long','多头'),('short','空头')):
        distribution=Counter(r['sector'] for r in rows if r['side']==direction)
        if distribution:
            count=max(distribution.values()); total=sum(distribution.values())
            leaders=[s for s,c in distribution.items() if c==count]
            p(f"{label}共振中，数量最多的板块是{'、'.join(leaders)}，"
              + ('各' if len(leaders)>1 else '') + f"占 {count}/{total}，即 {count/total*100:.1f}%。"
              '这个比例衡量候选分布的集中程度，不代表资金权重；同时观察这些品种时，应留意它们是否共享产业或宏观风险。')
    for sector, rs in sectors.items():
        lo = [r["name"] for r in rs if r["side"]=="long"]
        sh = [r["name"] for r in rs if r["side"]=="short"]
        if lo or sh:
            changes=[r['chg'] for r in rs if r['chg'] is not None]
            p(f"{sector}：覆盖 {len(rs)} 个品种，多头共振 {len(lo)} 个、空头共振 {len(sh)} 个。"
              + (f"多头包括{'、'.join(lo)}。" if lo else "")
              + (f"空头包括{'、'.join(sh)}。" if sh else "")
              + (f"可计算涨跌幅的 {len(changes)} 个样本中，上涨 {sum(x>0 for x in changes)} 个、下跌 {sum(x<0 for x in changes)} 个，"
                 f"品种涨跌幅范围为 {pct(min(changes))} 至 {pct(max(changes))}。" if changes else
                 '前结算价数据不足，本次只展示趋势状态，不比较该板块的统一口径涨跌幅。'))
    p("板块平均值为有效品种涨跌幅的简单平均，不按成交额或持仓价值加权，也不是交易所板块指数。"
      "各板块覆盖数量不同，因此均值和共振数量需要连同样本数一起阅读。涨跌幅范围补充了均值没有展示的内部差异，后续可比较同向状态是否扩散到更多品种。")
    h("四、状态变化：哪些品种需要重新检查")
    transitions = [r for r in rows if r.get("side_prev") not in (None,"unknown") and r["side"]!="unknown" and r["side"]!=r["side_prev"]]
    if legacy:
        p("本快照没有上一交易日的规则状态，也没有用于回算的原始日线。本节不判定新进入或退出，避免把未记录的信息补成历史事实。")
    elif transitions:
        table(["品种","前一条日线状态","本日状态"],[[r["name"],SIDE[r["side_prev"]],SIDE[r["side"]]] for r in transitions])
        p("状态切换只说明筛选条件发生变化。从空头直接变为多头，与从不共振进入多头，含义不同。"
          "这里按各品种的前一条有效日线回算；尚未接入交易所日历，不能保证其间没有缺失交易日。")
    else:
        p("在能够回算前一条日线状态的样本中，本次未观察到规则切换。前态未知的样本不算作新进入。")
    p("当前周线和月线尚可能未结束。若后续收盘重新跨越对应 MA10，或周、日 MA10 斜率不再满足条件，"
      "现有共振会失效。因此本节适合建立复查清单，不适合写成已经确认的趋势起点。")
    h("五、价格与持仓：四象限分布")
    quadrants = ("价涨仓增","价涨仓减","价跌仓增","价跌仓减","持仓不变","价格持平","数据不足")
    table(["状态","样本数","代表品种（最多六个）"],[[q,str(sum(r["quadrant"]==q for r in rows)),
        "、".join([r["name"] for r in rows if r["quadrant"]==q][:6]) or "无"] for q in quadrants])
    p("持仓增加意味着未平仓合约数量增加，每张合约都有买卖双方。仅凭日收盘与总持仓变化，"
      "无法识别谁主动成交，也无法证明上涨来自空头回补或下跌来自多头止损。"
      "本报告保留“价涨仓增”等事实分类，不为它们赋予未经检验的胜率或强弱等级。")
    p("主力连续在切换合约时，持仓变化还可能包含合约切换的影响。若某品种同时出现异常跳价和持仓突变，"
      "应先核对实际主力合约，再讨论交易行为。持仓变化为零单独列示，不划入减仓。")
    h("六、价格变化榜与趋势对照")
    for label, rs in (("涨幅样本",sorted([r for r in valid_chg if r['chg']>0],key=lambda r:-r['chg'])[:5]),
                      ("跌幅样本",sorted([r for r in valid_chg if r['chg']<0],key=lambda r:r['chg'])[:5])):
        h(label,3)
        table(["品种","连续收盘","涨跌幅","共振状态"],[[r['name'],fmt(r['last']),pct(r['chg']),SIDE[r['side']]] for r in rs])
    p("榜单只描述样本中的相对排序。排在前列不等于超出该品种的正常波动区间，"
      "也不自动构成追涨、反转或离场信号。将日变化与多周期状态并列，是为了避免把一天的反弹或回落直接当成趋势改变。")
    h("七、候选证据与风险测算")
    p(f"本节统一使用假设权益 {fmt(data['equity'],0)} 元，单笔参考风险预算 {fmt(data['equity']*.01,0)} 元，"
      f"单品种名义敞口上限 {fmt(data['equity']*.10,0)} 元。不是读取到账户后自动计算的可开仓额度。"
      "缺少当日乘数时不出手数；缺少有效保证金比例时显示未知。")
    p("下面的证据表检查月线价格位置，以及周、日价格位置和均线方向，共五项条件。"
      "收盘相对MA10的偏离幅度帮助复查位置，不代表信号成功概率。所有金额使用未四舍五入的指标计算，展示值可能有末位差异。")
    candidates = [r for r in rows if r["side"] in ("long","short")]
    for label, side in (("多头共振","long"),("空头共振","short")):
        h(label,3)
        table(["品种","连续收盘","ATR14","参考止损","风险手数","敞口手数","上限手数","限制来源"],
              [[r['name'],fmt(r['last']),fmt(r['atr']),fmt(r.get('stop_px')),fmt(r.get('risk_lots'),0),
                fmt(r.get('exposure_lots'),0),fmt(r.get('lots'),0),BINDING[r.get('binding','unknown')]]
               for r in candidates if r['side']==side])
    if legacy:
        p("旧 CSV 记录了共振分类和 ATR，但没有原始价格序列、合约乘数与当日规则。"
          "以上只转述历史记录，不补写均线数值、止损委托价或仓位上限。下次从完整输入运行后，才可逐项展示触发证据。")
    for r in candidates:
        ev = r.get('evidence')
        if not ev: continue
        h(f"{r['name']}（{r['symbol']}）：{SIDE[r['side']]}的计算依据",3)
        table(["周期","周期末可见收盘","MA10","前一期MA10","收盘相对MA10"],
              [[name,fmt(ev[key]['close']),fmt(ev[key]['ma']),fmt(ev[key]['ma_prev']),
                pct(ev[key]['close']/ev[key]['ma']-1)] for name,key in (("月","monthly"),("周","weekly"),("日","daily"))])
        if r.get('lots') is not None:
            p(f"每手名义价值 = {fmt(r['last'])} × {fmt(r['mult'])} = {fmt(r['notional_per_lot'])} 元；"
              f"每手参考风险 = {fmt(r['stop_distance'])} × {fmt(r['mult'])} = {fmt(r['risk_per_lot'])} 元。"
              f"两项上限分别为 {r['risk_lots']} 手和 {r['exposure_lots']} 手，取小得到 {r['lots']} 手，"
              f"限制来自{BINDING[r['binding']]}。"
              f"每手保证金估算：{fmt(r.get('margin'))} 元。")
        else:
            p("缺少完整的风险测算输入，本品种保留环境状态，但不提供手数。不能用默认乘数1或默认保证金0替代实际规则。")
    p("ATR 使用最近14根真实波幅的简单平均，参考止损距离为1.5×ATR。"
      "真实波幅以最高、最低和前收盘计算。这个选择描述历史波动，不证明1.5倍是最优参数。"
      "实际成交若存在跳空、滑点或无法成交，损失可能超过测算；止损参考价也尚未按实际合约最小变动价位处理。")
    p("每个候选均按同一个账户独立测算，不能把表内手数全部同时使用。组合层面的总敞口、"
      "已有持仓、可用资金和相关风险尚需另行检查。本版不自动分配组合仓位。")
    excluded = [r for r in rows if r['side']=='flat' and r.get('evidence')]
    if excluded:
        h('未进入共振的品种：分歧在哪里',3)
        def condition(e, slope=False):
            location='高于' if e['close']>e['ma'] else '低于' if e['close']<e['ma'] else '等于'
            direction=('上行' if e['ma']>e['ma_prev'] else '下行' if e['ma']<e['ma_prev'] else '走平') if slope else ''
            return location+'MA10'+(' / MA10'+direction if slope else '')
        table(['品种','月线位置','周线位置与方向','日线位置与方向'],
              [[r['name'],condition(r['evidence']['monthly']),condition(r['evidence']['weekly'],True),
                condition(r['evidence']['daily'],True)] for r in excluded])
        p('不共振表示五项条件未同向，并不等于该品种不会上涨或下跌。保留具体分歧，便于后续确认究竟是哪一层条件发生变化。')
    h("八、账户信息：与研究盘面分开记录")
    p(f"账户查询时间：{data.get('account_at','未查询')}。账户为查询时刻状态，不用于回填历史交易日。")
    if position_status == 'unknown': p("持仓状态未知：未查询、查询失败或返回结构不可识别，不能据此写为无持仓。")
    elif position_status == 'empty': p("持仓查询成功，返回列表为空。挂单未查询，不能据此判断无挂单。")
    else: p(f"持仓查询成功，返回 {len(positions)} 条记录。本报告未完成逐笔合约核验与组合风险测算，不输出账户安全结论；挂单未查询。")
    p("本版不以“可用资金+保证金”自动替代账户权益。不同柜台字段口径需要先核实；"
      "候选表始终标明假设权益，避免真实账户信息与仿真预算混用。公开分享时应移除个人账户信息。")
    h("九、下一次复盘应验证什么")
    if transitions:
        p('本次优先复查名单为'+ '、'.join(r['name'] for r in transitions)+'。'
          '它们刚发生规则切换，下一份同口径数据应先确认新状态是否保持，再讨论它是否扩散为更稳定的多周期结构。')
    p("首先检查新数据是否覆盖同一品种清单和同一交易日。覆盖变化会改变涨跌占比与共振数量，"
      "不能将样本减少造成的数量变化解释成市场转向。若数据不齐，先说明缺口，再讨论已有样本。")
    p("其次回看本次共振条件：周、日 MA10 的方向是否保持，收盘是否仍在要求的一侧。"
      "如果条件失效，应更新分类，而不是为了维持昨日观点扩大解释。周末、月末还应确认临时周期状态能否在周期结束时保留。")
    p("对价格排名靠前的品种，分开检查单日变化与多周期状态。若二者相反，继续观察变化是否足以改变均线结构；"
      "若二者一致，也只意味着观察方向一致，不能据此省略入场与实际合约的核对。宏观事件原因需要另外引用可核查来源，"
      "本报告未接入新闻与事件数据，因此不编写未经核实的事件归因。")
    h("十、缺失项与复核入口")
    issue_rows = [[i['symbol'],i['reason']] for i in data.get('issues',[])]
    issue_rows += [[r['symbol'],note] for r in rows for note in r.get('notes',[])]
    table(["对象","状态 / 影响"], issue_rows or [["覆盖检查","本次未记录品种排除或字段缺失；仍不等于独立行情核验通过"]])
    p("复核顺序：原始输入 → 日期与字段检查 → 周月重采样 → MA10和ATR → 规则分类 → 风险公式 → 报告展示。"
      "计算采用截至研究日的最近18个月日线，既保留足够的MA10历史，也避免无关远期数据参与校验。"
      "原始档案保存输入与文件哈希，便于定位同一版本；哈希只能发现文件是否变化，不能证明数据源本身正确。"
      "对外引用时保留交易日、来源和证据状态，不只截取一个结论或一张手数表。")
    p("本报告用于期货仿真研究，不构成交易指令或收益承诺。规则的历史收益、胜率和预测有效性尚未经过本项目验证。")
    md, xml = [], []
    for b in blocks:
        if b[0]=='h':
            _,level,text=b; md.append('#'*level+' '+text)
            tag='title' if level==1 else 'h1' if level==2 else 'h2'
            xml.append(f'<{tag}>{escape(text)}</{tag}>')
        elif b[0]=='p': md.append(b[1]); xml.append('<p>'+escape(b[1])+'</p>')
        else:
            _,headers,body=b
            clean=lambda x: str(x).replace('|','／').replace('\n',' ')
            md.append('\n'.join(['| '+' | '.join(map(clean,headers))+' |','|'+'---|'*len(headers)] +
                                ['| '+' | '.join(map(clean,r))+' |' for r in body]))
            xml.append('<table><thead><tr>'+''.join('<th><p>'+escape(str(x))+'</p></th>' for x in headers)+
                       '</tr></thead><tbody>'+''.join('<tr>'+''.join('<td><p>'+escape(str(x))+'</p></td>' for x in r)+'</tr>' for r in body)+'</tbody></table>')
    meta = dict(date=data['date'],scanned=n,up=up,down=down,flat=flat_price,long_n=counts['long'],short_n=counts['short'],
                unknown_n=counts['unknown'],temperature=temp,positions_status=position_status,independently_verified=False,
                evidence_status='legacy_unverified' if legacy else 'single_source_checked',
                rows=rows,issues=data.get('issues',[]),expected=data['expected'],
                new_long=[r['name'] for r in transitions if r['side']=='long'],
                new_short=[r['name'] for r in transitions if r['side']=='short'])
    meta.update(weekday=('周一','周二','周三','周四','周五','周六','周日')[date.fromisoformat(data['date']).weekday()],
                top=[r['name'] for r in sorted(valid_chg,key=lambda r:-r['chg']) if r['chg']>0][:3],
                bottom=[r['name'] for r in sorted(valid_chg,key=lambda r:r['chg']) if r['chg']<0][:3])
    return '\n\n'.join(md)+'\n', '\n'.join(xml)+'\n', meta

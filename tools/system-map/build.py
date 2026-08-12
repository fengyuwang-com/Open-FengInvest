#!/usr/bin/env python3
"""FengInvest 系统关系图生成器

唯一源数据:  tools/system-map/system-map.yaml
产物:        docs/system-map.mmd   (Mermaid 静态图, 可直接嵌进 markdown)
             docs/system-map.html  (vis-network 互动图, 双击打开可拖拽/缩放/搜索)

用法:
    python tools/system-map/build.py

改图流程: 增删组件只改 system-map.yaml, 重跑本脚本即可, 不用手画。
"""
import os
import sys
import json

import yaml

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "tools", "system-map", "system-map.yaml")
OUT_MMD = os.path.join(BASE, "docs", "system-map.mmd")
OUT_HTML = os.path.join(BASE, "docs", "system-map.html")


def esc_md(s):
    """mermaid 引号内安全化: 去换行, 双引号转单引号"""
    return str(s).replace("\n", " ").replace('"', "'").replace("\r", "")


def validate(data):
    """校验 YAML: id 唯一、边引用存在、path 存在性警告"""
    errors, warns = [], []
    nodes = {n["id"]: n for n in data["nodes"]}
    if len(nodes) != len(data["nodes"]):
        errors.append("存在重复的节点 id")
    for g in data["groups"]:
        if g not in data["groups"]:
            errors.append(f"未知分组 {g}")
    for e in data["edges"]:
        if e["from"] not in nodes:
            errors.append(f"边 {e['from']}->{e['to']}: 起点不存在")
        if e["to"] not in nodes:
            errors.append(f"边 {e['from']}->{e['to']}: 终点不存在")
    for n in data["nodes"]:
        p = n.get("path")
        if p and not os.path.exists(p):
            warns.append(f"节点 {n['id']}: 路径不存在 -> {p}")
    return errors, warns


def render_mermaid(data):
    groups, nodes, edges = data["groups"], data["nodes"], data["edges"]
    # 图级配置: 大字号(20px)+大间距, 布局横排(LR)便于横向展开
    L = ["%%{init: {\"themeVariables\": {\"fontSize\": \"20px\"}, "
         "\"flowchart\": {\"nodeSpacing\": 50, \"rankSpacing\": 80, \"padding\": 16}}}%%",
         "%% 由 tools/system-map/build.py 生成, 勿手改。改 system-map.yaml 后重跑。",
         "%% 互动版: docs/system-map.html", "flowchart LR"]
    for gname, g in groups.items():
        gid = gname.replace("-", "_")
        L.append(f'  subgraph G_{gid}["{esc_md(g["label"])}"]')
        for n in nodes:
            if n["group"] == gname:
                L.append(f'    n_{n["id"]}["{esc_md(n["label"])}"]:::{gid}')
        L.append("  end")
    for gname, g in groups.items():
        gid = gname.replace("-", "_")
        L.append(f'  classDef {gid} fill:{g["color"]},stroke:#333,color:#fff,font-weight:bold')
    for e in edges:
        L.append(f'  n_{e["from"]} -->|"{esc_md(e["label"])}"| n_{e["to"]}')
    return "\n".join(L) + "\n"


def render_html(data, src_rel):
    groups, nodes, edges = data["groups"], data["nodes"], data["edges"]
    vis_nodes = []
    for n in nodes:
        vis_nodes.append({
            "id": n["id"],
            "label": n["label"],
            "group": n["group"],
            "title": n.get("desc", ""),
            "desc": n.get("desc", ""),
            "path": n.get("path", ""),
        })
    vis_edges = [{"from": e["from"], "to": e["to"], "label": e["label"],
                  "arrows": "to", "color": "#9aa0a6"} for e in edges]
    group_colors = {g: v["color"] for g, v in groups.items()}
    group_labels = {g: v["label"] for g, v in groups.items()}
    title = data["meta"]["title"]
    updated = data["meta"]["updated"]

    js_nodes = json.dumps(vis_nodes, ensure_ascii=False, indent=2)
    js_edges = json.dumps(vis_edges, ensure_ascii=False, indent=2)
    js_colors = json.dumps(group_colors, ensure_ascii=False)
    js_labels = json.dumps(group_labels, ensure_ascii=False)

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{TITLE}</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  html,body {{ margin:0; padding:0; height:100%; font-family:"Microsoft YaHei",sans-serif; }}
  #toolbar {{ position:fixed; top:0; left:0; right:0; height:48px; background:#1f2937; color:#fff;
              display:flex; align-items:center; gap:16px; padding:0 16px; z-index:10; }}
  #toolbar h1 {{ font-size:15px; margin:0; }}
  #toolbar .hint {{ font-size:12px; color:#9ca3af; }}
  #search {{ padding:5px 10px; border-radius:4px; border:none; width:220px; }}
  #legend {{ display:flex; gap:10px; margin-left:auto; }}
  .chip {{ font-size:11px; padding:3px 8px; border-radius:10px; color:#fff; }}
  #mynetwork {{ position:fixed; top:48px; left:0; right:280px; bottom:0; }}
  #info {{ position:fixed; top:48px; right:0; bottom:0; width:280px; background:#f3f4f6;
           border-left:1px solid #d1d5db; padding:16px; overflow-y:auto; font-size:13px; }}
  #info h2 {{ font-size:15px; margin:0 0 8px; }}
  #info .kv {{ margin:6px 0; }}
  #info .kv b {{ color:#374151; }}
  #info .path {{ font-family:Consolas,monospace; font-size:12px; word-break:break-all; }}
</style>
</head>
<body>
<div id="toolbar">
  <h1>{TITLE}</h1>
  <span class="hint">源: tools/system-map/system-map.yaml · 更新 {UPDATED} · 双击拖动/滚轮缩放/点节点看详情</span>
  <input id="search" type="text" placeholder="搜索节点…">
  <div id="legend"></div>
</div>
<div id="mynetwork"></div>
<div id="info"><h2>节点详情</h2><p style="color:#6b7280">点击图中节点查看说明</p></div>

<script>
const GROUP_COLORS = {COLORS};
const GROUP_LABELS = {LABELS};
const nodes = new vis.DataSet({NODES});
const edges = new vis.DataSet({EDGES});

// 图例
const legendEl = document.getElementById('legend');
for (const [g, label] of Object.entries(GROUP_LABELS)) {{
  const c = document.createElement('span');
  c.className = 'chip';
  c.style.background = GROUP_COLORS[g];
  c.textContent = label;
  legendEl.appendChild(c);
}}

const container = document.getElementById('mynetwork');
const options = {{
  nodes: {{
    shape: 'box',
    margin: 10,
    font: {{ size: 14, color: '#111827' }},
    borderWidth: 1,
    shadow: true,
  }},
  edges: {{
    font: {{ size: 11, color: '#4b5563', align: 'middle' }},
    width: 1.5,
    smooth: {{ type: 'continuous' }},
  }},
  groups: Object.fromEntries(
    Object.entries(GROUP_COLORS).map(([g, c]) => [g, {{
      color: {{ background: c, border: '#333' }},
      font: {{ color: '#fff' }},
      shape: 'box',
    }}])
  ),
  physics: {{ barnesHut: {{ gravitationalConstant: -8000, springLength: 160 }} }},
  interaction: {{ hover: true, tooltipDelay: 100 }},
}};
const network = new vis.Network(container, {{ nodes, edges }}, options);

// 点击节点 -> 右侧详情
network.on('click', function (params) {{
  if (params.nodes.length === 0) {{
    document.getElementById('info').innerHTML = '<h2>节点详情</h2><p style="color:#6b7280">点击图中节点查看说明</p>';
    return;
  }}
  const n = nodes.get(params.nodes[0]);
  const gname = GROUP_LABELS[n.group] || n.group;
  const gcolor = GROUP_COLORS[n.group] || '#888';
  document.getElementById('info').innerHTML =
    '<h2>' + n.label + '</h2>' +
    '<div class="kv"><b>分组</b> <span class="chip" style="background:' + gcolor + '">' + gname + '</span></div>' +
    (n.desc ? '<div class="kv"><b>说明</b><br>' + n.desc + '</div>' : '') +
    (n.path ? '<div class="kv"><b>路径</b><br><span class="path">' + n.path + '</span></div>' : '');
}});

// 搜索过滤
document.getElementById('search').addEventListener('input', function (e) {{
  const q = e.target.value.trim().toLowerCase();
  const updates = nodes.getIds().map(id => {{
    const n = nodes.get(id);
    const hit = !q || (n.label + ' ' + (n.desc || '')).toLowerCase().includes(q);
    return {{ id, hidden: !hit }};
  }});
  nodes.update(updates);
  network.setOptions({{ physics: {{ enabled: true }} }});
}});
</script>
</body>
</html>
"""
    html = html.replace("{TITLE}", title).replace("{UPDATED}", updated)
    html = html.replace("{NODES}", js_nodes).replace("{EDGES}", js_edges)
    html = html.replace("{COLORS}", js_colors).replace("{LABELS}", js_labels)
    # 模板中的双花括号是为 .format() 准备的转义, 这里用 .replace() 注入, 需还原为单括号
    html = html.replace("{{", "{").replace("}}", "}")
    return html


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with open(SRC, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    errors, warns = validate(data)
    for w in warns:
        print(f"[warn] {w}")
    if errors:
        for e in errors:
            print(f"[error] {e}")
        sys.exit(1)

    mmd = render_mermaid(data)
    with open(OUT_MMD, "w", encoding="utf-8") as f:
        f.write(mmd)

    html = render_html(data, SRC)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    n_nodes = len(data["nodes"])
    n_edges = len(data["edges"])
    print(f"✅ 节点 {n_nodes} 个, 关系 {n_edges} 条")
    print(f"   静态图:  {OUT_MMD}")
    print(f"   互动图:  {OUT_HTML}")


if __name__ == "__main__":
    main()

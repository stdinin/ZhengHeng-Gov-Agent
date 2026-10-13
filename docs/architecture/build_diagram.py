"""Build matching SVG, PNG and editable draw.io architecture artifacts."""
from pathlib import Path
import base64
import concurrent.futures
import html
import json
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent
ASSETS = ROOT / 'assets'
ASSETS.mkdir(exist_ok=True)
LOGOS = {
    'React': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/react/react-original.svg',
    'FastAPI': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/fastapi/fastapi-original.svg',
    'Python': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/python/python-original.svg',
    'Node.js': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/nodejs/nodejs-original.svg',
    'MongoDB': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/mongodb/mongodb-original.svg',
    'Redis': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/redis/redis-original.svg',
    'OpenSearch': 'https://raw.githubusercontent.com/opensearch-project/project-website/main/assets/brand/SVG/Mark/opensearch_mark_default.svg',
    'Milvus': 'https://raw.githubusercontent.com/milvus-io/artwork/master/icon/color/milvus-icon-color.svg',
    'Docker': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/docker/docker-original.svg',
    'Prometheus': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/prometheus/prometheus-original.svg',
    'Kubernetes': 'https://raw.githubusercontent.com/devicons/devicon/master/icons/kubernetes/kubernetes-original.svg',
}

def fetch(item):
    name, url = item
    path = ASSETS / (name.replace('.', '-') + '.svg')
    if not path.exists():
        request = urllib.request.Request(url, headers={'User-Agent': 'ZhengHeng-architecture'})
        content = urllib.request.urlopen(request, timeout=30).read()
        ET.fromstring(content)
        path.write_bytes(content)
    return name, path

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    assets = dict(pool.map(fetch, LOGOS.items()))
(ASSETS / 'sources.json').write_text(json.dumps(LOGOS, ensure_ascii=False, indent=2), encoding='utf-8')

W, H = 1640, 1350
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#59636e"/></marker></defs>']
mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
diagram = ET.SubElement(mx, 'diagram', name='政衡系统架构', id='zhengheng-architecture')
model = ET.SubElement(diagram, 'mxGraphModel', dx=str(W), dy=str(H), grid='1', gridSize='10', page='1', pageScale='1', pageWidth=str(W), pageHeight=str(H), background='#ffffff')
cells = ET.SubElement(model, 'root')
ET.SubElement(cells, 'mxCell', id='0')
ET.SubElement(cells, 'mxCell', id='1', parent='0')
seq = 1

def cell(x,y,w,h,value,style):
    global seq
    seq += 1
    c=ET.SubElement(cells,'mxCell',id=str(seq),value=value,style=style,vertex='1',parent='1')
    ET.SubElement(c,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h), attrib={'as':'geometry'})
    return c

def rect(x,y,w,h,fill='#ffffff',stroke='#68717a',radius=0,dash=False):
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"'+(' stroke-dasharray="7 4"' if dash else '')+'/>')
    cell(x,y,w,h,'',f'rounded={int(radius>0)};arcSize=18;fillColor={fill};strokeColor={stroke};strokeWidth=1.4;dashed={int(dash)};dashPattern=7 4;')

def text(x,y,w,h,value,size=20,bold=False,color='#29333d',align='center'):
    lines=value.split('\n')
    gap=size*1.38
    yy=y+h/2-(len(lines)-1)*gap/2
    xx=x+w/2 if align=='center' else x+8
    for i,line in enumerate(lines):
        svg.append(f'<text x="{xx}" y="{yy+i*gap}" dominant-baseline="central" text-anchor="{"middle" if align=="center" else "start"}" font-family="Microsoft YaHei, Arial, sans-serif" font-size="{size}" font-weight="{600 if bold else 400}" fill="{color}">{html.escape(line)}</text>')
    cell(x,y,w,h,value,f'text;html=0;whiteSpace=wrap;overflow=hidden;align={align};verticalAlign=middle;fontFamily=Microsoft YaHei;fontSize={size};fontStyle={int(bold)};fontColor={color};strokeColor=none;fillColor=none;')

def box(x,y,w,h,label,fill='#d2edb9',size=20,bold=False,stroke='none',radius=12):
    rect(x,y,w,h,fill,stroke,radius)
    text(x,y,w,h,label,size,bold)

def line(points,arrow=True,dash=False):
    p=' '.join(f'{x},{y}' for x,y in points)
    svg.append(f'<polyline points="{p}" fill="none" stroke="#59636e" stroke-width="1.6"'+(' marker-end="url(#arrow)"' if arrow else '')+(' stroke-dasharray="5 4"' if dash else '')+'/>')
    global seq
    seq+=1
    c=ET.SubElement(cells,'mxCell',id=str(seq),style=f'edgeStyle=none;rounded=0;endArrow={"block" if arrow else "none"};endFill=1;strokeColor=#59636e;strokeWidth=1.6;dashed={int(dash)};',edge='1',parent='1')
    geo=ET.SubElement(c,'mxGeometry',relative='1',attrib={'as':'geometry'})
    for point,key in [(points[0],'sourcePoint'),(points[-1],'targetPoint')]:
        ET.SubElement(geo,'mxPoint',x=str(point[0]),y=str(point[1]),attrib={'as':key})
    if len(points)>2:
        a=ET.SubElement(geo,'Array',attrib={'as':'points'})
        for x,y in points[1:-1]: ET.SubElement(a,'mxPoint',x=str(x),y=str(y))

def layer(y,h,label,fill):
    rect(45,y,140,h,'#ffffff','#707780',0,True)
    rect(57,y+10,116,h-20,fill,'none')
    text(57,y+10,116,h-20,label,24,True)
    rect(205,y,1390,h,fill,'#65707c',0,True)

rect(0,0,W,H,'#ffffff','none')
text(45,24,1550,44,'政衡 Agent 系统架构',32,True)
text(45,70,1550,28,'多部门可信政务问答与反馈演化  ·  基于当前代码结构绘制',17,False,'#6b7480')

layer(115,95,'客户端','#f0eded')
box(230,137,445,51,'Web 浏览器  ·  React + Vite + TypeScript','#fafafa',21,False,'#ffffff',0)
box(700,137,410,51,'政策问答  /  引用溯源  /  Trace','#fafafa',21,False,'#ffffff',0)
box(1135,137,435,51,'Agent Network  /  登录  /  系统状态','#fafafa',20,False,'#ffffff',0)

layer(225,100,'服务层','#e8edf0')
for x,w,s in [(230,310,'FastAPI + Uvicorn'),(560,300,'REST API  /  JWT + RBAC'),(880,350,'内部 HTTP  /  服务 Token'),(1250,320,'Docker Compose 部署')]:
    box(x,249,w,52,s,'#f8dedd',20,False,'#ffffff',0)

layer(340,475,'业务层','#fcebdc')
for i,s in enumerate(['用户与部门权限','政策文档与版本治理','可信问答与多 Agent','分层记忆与 Trace','反馈评测与策略演化']):
    box(229+i*270,359,258,47,s,'#fffdf0',20,True,radius=0)

# Left document governance column.
rect(229,425,251,367,'#ffffff','#78828b',0,True)
text(239,432,231,35,'政策知识治理',22,True)
for i,s in enumerate(['采集 / 上传 / 解析','文档分块 · 元数据','稀疏 / 向量双索引','原子发布 · 版本切换','ACTIVE / 归档治理']):
    box(246,480+i*57,217,43,s,size=19)

# Main governed multi-agent request path.
rect(496,425,716,367,'#ffffff','#78828b',0,True)
box(513,440,682,52,'全局 Orchestrator  ·  意图识别 → 改写 → 静态路由','#d2edb9',20,True)
for xx in [627,854,1081]:
    line([(854,492),(854,506),(xx,506),(xx,521)])
for i,s in enumerate(['税务 Agent','人社 Agent','住建 Agent']):
    box(516+i*227,521,222,48,s,'#d2edb9',21,True)
text(518,574,674,26,'固定 DEPT_ID 隔离检索  ·  有界并发  ·  单部门超时隔离',17,False,'#59636e')
for xx in [627,854,1081]: line([(xx,569),(xx,574)],False)
box(516,611,676,48,'Hybrid RAG：BM25 + Dense → RRF → Reranker','#dceff0',19,True)
line([(854,600),(854,611)])
box(516,675,676,40,'canonical ACTIVE 复核 → 部门回答与引用验证','#d2edb9',20)
line([(854,659),(854,675)])
box(516,735,676,40,'结果聚合 → 全局验证 → 引用去重 / 证据不足拒答','#d2edb9',19)
line([(854,715),(854,735)])
line([(480,635),(496,635)],True)

# Feedback governance column.
rect(1228,425,343,367,'#ffffff','#78828b',0,True)
text(1238,432,323,35,'记忆与反馈闭环',22,True)
for i,s in enumerate(['工作 / 用户 / 案例 / 组织 / 策略记忆','根 / 子 Trace · 用户反馈','Bad Case 归因 · 策略 DSL','冻结 Trace 回放 · Replay Gate','人工审核 · 灰度发布 · 回滚']):
    box(1244,480+i*57,311,43,s,size=17)

layer(830,285,'公共\n技术层','#e8f4dc')
cards=[(229,332,'后端与运行时'),(580,438,'模型与检索能力'),(1037,534,'数据与状态组件')]
for x,w,title in cards:
    rect(x,851,w,241,'#ffffff','#717c87')
    text(x+10,860,w-20,33,title,22,True)
for x,y,w,s in [(243,907,143,'FastAPI'),(402,907,143,'Pydantic'),(243,957,143,'Python 3.12'),(402,957,143,'Node.js / TS'),(243,1007,302,'Pi Agent Core  ·  可选运行时')]:
    box(x,y,w,39,s,'#ddf2f2',18)
text(241,1053,308,25,'固定 Harness · 受控语义节点',16,False,'#697681')
for x,y,w,s in [(596,907,406,'BGE-M3  ·  1024 维向量'),(596,957,406,'BGE Reranker v2 M3'),(596,1007,195,'BM25 / RRF'),(807,1007,195,'LLM 兼容接口')]:
    box(x,y,w,39,s,'#ddf2f2',19)
text(590,1053,418,25,'模型可配置 · Pi Compose 默认 Faux',16,False,'#697681')
for x,y,s in [(1053,907,'MongoDB · 文档 / 版本 / Trace'),(1312,907,'Redis · 会话 / 工作记忆'),(1053,957,'OpenSearch · BM25 索引'),(1312,957,'Milvus · Dense 向量索引'),(1053,1007,'MinIO · Milvus 对象存储'),(1312,1007,'etcd · Milvus 元数据')]:
    box(x,y,243,39,s,'#ddf2f2',16)
text(1050,1053,506,25,'事实以 MongoDB 当前有效版本为准',16,False,'#697681')

layer(1130,145,'基础设施\n与工具','#e7e5fa')
for i,(name,path) in enumerate(assets.items()):
    x=223+i*123
    data=base64.b64encode(path.read_bytes()).decode()
    uri='data:image/svg+xml;base64,'+data
    svg.append(f'<image x="{x+31}" y="1151" width="62" height="62" xlink:href="{uri}"/>')
    # Embed PNG in draw.io for maximum portability across diagrams.net versions.
    import resvg_py
    png=resvg_py.svg_to_bytes(svg_path=str(path),width=150,height=150)
    pnguri='data:image/png,'+base64.b64encode(png).decode()
    cell(x+31,1151,62,62,'',f'shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=1;aspect=fixed;image={pnguri};')
    text(x,1218,123,29,name,17,True)
text(228,1250,1343,19,'Docker Compose 部署  ·  Prometheus 指标  ·  pytest / k6 评测  ·  Kubernetes / Helm 为可选部署配置',15,False,'#59636e')
text(45,1291,1550,25,'注：主链路展示 V1.1 可选多 Agent 模式；默认保留 V1.0 单 Agent Harness。Kubernetes 运行验收仍有保留项。',16,False,'#697681')
svg.append('</svg>')
svgtxt='\n'.join(svg)
(ROOT/'zhengheng-architecture.svg').write_text(svgtxt,encoding='utf-8')
ET.indent(mx)
ET.ElementTree(mx).write(ROOT/'zhengheng-architecture.drawio',encoding='utf-8',xml_declaration=True)
import resvg_py
(ROOT/'zhengheng-architecture.png').write_bytes(resvg_py.svg_to_bytes(svg_string=svgtxt,width=W*2,height=H*2))
(ROOT/'preview.png').write_bytes(resvg_py.svg_to_bytes(svg_string=svgtxt,width=W,height=H))
print('Created SVG, editable draw.io, and 3280 x 2700 PNG; embedded logos:',len(assets))

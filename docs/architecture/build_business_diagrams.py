"""Source-grounded business sequence and functional hierarchy diagrams."""
from pathlib import Path
import copy
import html
import xml.etree.ElementTree as ET
import resvg_py
from PIL import ImageFont
import re

FONT = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 17)

def wrap_label(label, width):
    lines=[]; current=''
    for token in re.findall(r'[A-Za-z0-9_/-]+|.',label):
        if current and FONT.getlength(current+token)>width:
            lines.append(current.strip()); current=token
        else:
            current+=token
    if current: lines.append(current.strip())
    return lines

OUT = Path(__file__).parent

class Drawing:
    def __init__(self, name, width, height):
        self.name, self.w, self.h = name, width, height
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10Z" fill="#555"/></marker></defs>', f'<rect width="{width}" height="{height}" fill="white"/>']
        self.mx = ET.Element('mxfile', host='app.diagrams.net')
        self.page = ET.SubElement(self.mx, 'diagram', name=name, id=name)
        model = ET.SubElement(self.page, 'mxGraphModel', page='1', pageWidth=str(width), pageHeight=str(height), grid='1', gridSize='10', background='#ffffff')
        self.root = ET.SubElement(model, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.id = 1

    def cell(self,x,y,w,h,value,style):
        self.id += 1
        c=ET.SubElement(self.root,'mxCell',id=str(self.id),value=value,style=style,vertex='1',parent='1')
        ET.SubElement(c,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),attrib={'as':'geometry'})

    def rect(self,x,y,w,h,fill='white',stroke='#666',dash=False):
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"'+(' stroke-dasharray="7 5"' if dash else '')+'/>')
        self.cell(x,y,w,h,'',f'fillColor={fill};strokeColor={stroke};strokeWidth=1.5;dashed={int(dash)};')

    def text(self,x,y,w,h,label,size=20,bold=False,color='#303030',back=False):
        lines=label.split('\n'); gap=size*1.26
        if back:
            self.rect(x,y,w,h,'white','none')
        for i,s in enumerate(lines):
            yy=y+h/2+(i-(len(lines)-1)/2)*gap
            self.svg.append(f'<text x="{x+w/2}" y="{yy}" text-anchor="middle" dominant-baseline="central" font-family="Microsoft YaHei, Arial, sans-serif" font-size="{size}" font-weight="{600 if bold else 400}" fill="{color}">{html.escape(s)}</text>')
        self.cell(x,y,w,h,label,f'text;html=0;whiteSpace=wrap;align=center;verticalAlign=middle;fontFamily=Microsoft YaHei;fontSize={size};fontStyle={int(bold)};fontColor={color};fillColor=none;strokeColor=none;')

    def box(self,x,y,w,h,label,fill='white',size=20,bold=False):
        self.rect(x,y,w,h,fill); self.text(x,y,w,h,label,size,bold)

    def line(self,points,arrow=False,dash=False):
        self.svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="none" stroke="#666" stroke-width="1.5"'+(' marker-end="url(#a)"' if arrow else '')+(' stroke-dasharray="7 5"' if dash else '')+'/>')
        self.id+=1
        c=ET.SubElement(self.root,'mxCell',id=str(self.id),edge='1',parent='1',style=f'edgeStyle=none;endArrow={"block" if arrow else "none"};endFill=1;strokeColor=#666;strokeWidth=1.5;dashed={int(dash)};')
        geo=ET.SubElement(c,'mxGeometry',relative='1',attrib={'as':'geometry'})
        for (x,y),tag in [(points[0],'sourcePoint'),(points[-1],'targetPoint')]:
            ET.SubElement(geo,'mxPoint',x=str(x),y=str(y),attrib={'as':tag})
        if len(points)>2:
            a=ET.SubElement(geo,'Array',attrib={'as':'points'})
            for x,y in points[1:-1]: ET.SubElement(a,'mxPoint',x=str(x),y=str(y))

    def save(self,stem):
        svg='\n'.join(self.svg+['</svg>'])
        (OUT/f'{stem}.svg').write_text(svg,encoding='utf-8')
        ET.indent(self.mx)
        ET.ElementTree(self.mx).write(OUT/f'{stem}.drawio',encoding='utf-8',xml_declaration=True)
        (OUT/f'{stem}.png').write_bytes(resvg_py.svg_to_bytes(svg_string=svg,width=self.w*2,height=self.h*2))
        (OUT/f'{stem}-preview.png').write_bytes(resvg_py.svg_to_bytes(svg_string=svg,width=self.w,height=self.h))
        print(stem,self.w*2,self.h*2,'cells',self.id)

# Functional hierarchy: white boxes, orthogonal branches and vertical leaf labels.
groups=[
 ('认证与访问子系统',[
  ('身份认证',['邮箱密码登录','令牌签发校验','当前用户查询']),
  ('访问控制',['角色权限控制','部门检索隔离','内部服务鉴权'])]),
 ('政策知识子系统',[
  ('文档入库',['文件上传解析','税务数据导入','文档分块处理','双索引构建']),
  ('版本治理',['版本列表查询','索引一致校验','原子发布切换','政策归档管理'])]),
 ('可信问答子系统',[
  ('检索生成',['意图识别改写','部门路由选择','混合检索融合','候选证据重排']),
  ('可信输出',['有效版本复核','证据引用校验','证据不足拒答','引用来源展示'])]),
 ('多部门协同子系统',[
  ('部门调度',['静态服务注册','税务部门代理','人社部门代理','住建部门代理']),
  ('结果治理',['有界并发调度','部门超时隔离','结果聚合去重','全局引用验证'])]),
 ('记忆与追踪子系统',[
  ('分层记忆',['会话工作记忆','用户语义记忆','案例组织记忆','策略记忆管理']),
  ('执行追踪',['根子轨迹关联','节点耗时记录','检索阶段追踪','会话历史查询'])]),
 ('反馈评测子系统',[
  ('反馈演化',['用户反馈采集','失败案例审核','策略候选生成','冻结轨迹回放']),
  ('发布与观测',['回放门禁校验','人工批准灰度','策略晋升回滚','评测指标观测'])]),
]
fw=2740
f=Drawing('系统功能结构图',fw,800)
f.box(fw/2-185,35,370,56,'政衡可信政务问答系统',size=26,bold=True)
centers=[245+i*450 for i in range(6)]
f.line([(fw/2,91),(fw/2,126)])
f.line([(centers[0],126),(centers[-1],126)])
for center,(name,categories) in zip(centers,groups):
    f.line([(center,126),(center,166)])
    f.box(center-126,166,252,48,name,size=22)
    subcenters=[center-112,center+112]
    f.line([(center,214),(center,250)])
    f.line([(subcenters[0],250),(subcenters[-1],250)])
    for cx,(title,leaves) in zip(subcenters,categories):
        f.line([(cx,250),(cx,281)])
        f.box(cx-23,281,46,140,'\n'.join(title),size=21)
        leafx=[cx+(i-(len(leaves)-1)/2)*49 for i in range(len(leaves))]
        f.line([(cx,421),(cx,461)])
        f.line([(leafx[0],461),(leafx[-1],461)])
        for lx,label in zip(leafx,leaves):
            f.line([(lx,461),(lx,498)])
            f.box(lx-20,498,40,205,'\n'.join(label),size=19)
f.text(0,720,fw,38,'系统功能结构图',27,True)
f.text(40,764,fw-80,24,'按后端、前端与脚本的已实现能力归纳；文档及策略管理部分通过 API / 脚本操作，多部门协同为 V1.1 可选模式。',18,color='#777')
f.save('zhengheng-functions')

# Logical sequence participants: deployment-internal functions are deliberately grouped.
phases=[
 ('一、登录认证',[
  (0,1,'输入邮箱和密码'),(1,2,'提交登录请求'),(2,5,'按邮箱查询用户'),
  (5,2,'返回用户与密码摘要',True),(2,2,'校验密码，签发 JWT'),
  (2,1,'返回 access_token 与用户信息',True),(1,0,'保存到 sessionStorage，提示登录成功',True)]),
 ('二、政策文档入库、索引与版本发布（管理员通过 API / 脚本）',[
  (0,1,'提交政策文件与部门元数据'),(1,2,'上传文件 / 导入税务数据'),
  (2,2,'解析正文、分块、生成版本'),(2,5,'保存文档、PARSED 版本与分块'),
  (5,2,'返回版本记录',True),(2,1,'返回 version_id 与 PARSED 状态',True),
  (1,2,'发起 reindex 请求'),(2,5,'读取版本与分块，设置 INDEXING'),
  (2,4,'BGE 向量化，写 OpenSearch / Milvus'),(4,2,'索引数量与检索探针校验通过',True),
  (2,5,'将版本状态更新为 READY'),(2,1,'返回 READY，等待显式发布',True),
  (0,1,'确认发布当前政策版本'),(1,2,'提交 publish 请求'),
  (2,5,'事务发布 ACTIVE、切换当前版本、归档旧版本'),
  (5,2,'返回发布结果',True),(2,1,'返回当前有效版本',True),(1,0,'显示发布成功',True)]),
 ('三、多部门可信问答（V1.1 可选路径）',[
  (0,1,'输入政策问题'),(1,2,'提交 query、session_id 与 Bearer JWT'),
  (2,5,'校验令牌对应的用户'),(2,6,'读取工作记忆 / 会话上下文'),
  (2,5,'读取长期记忆，供根节点构建只读快照'),(2,7,'调用意图识别、改写与路由语义节点'),
  (7,2,'返回结构化语义结果',True),(2,2,'静态注册表校验，确定目标部门'),
  ('note','par：对选中的税务 / 人社 / 住建 Agent 有界并行调用；以下展示单个部门的执行过程'),
  (2,3,'发送部门任务与裁剪后的只读快照'),(3,3,'固定 DEPT_ID，构建检索过滤条件'),
  (3,4,'查询向量化；并行 BM25 + Dense；RRF 融合'),
  (4,5,'读取候选对应的规范证据文本'),(5,4,'返回候选证据',True),
  (4,4,'执行 BGE Reranker 重排'),(4,5,'复核 canonical ACTIVE 与当前版本指针'),
  (5,4,'返回当前有效证据',True),(4,3,'返回最终证据及检索阶段统计',True),
  (3,7,'仅依据证据执行回答与验证语义节点'),(7,3,'返回结构化回答 / 验证结果',True),
  (3,3,'本地引用与声明校验'),(3,5,'写入子 Trace 与检索、验证记录'),
  (3,2,'返回部门状态、答案、引用与 child_trace_id',True),
  ('note','alt：单部门超时 / 验证失败 → 隔离该结果；无成功结果或全局验证失败 → 拒答'),
  (2,7,'多个有效部门结果时，仅请求展示顺序'),(7,2,'返回部门排序；失败则使用确定性顺序',True),
  (2,2,'聚合已验证段落、引用去重、全局验证'),
  (2,5,'保存根 Trace；根节点写一次案例记忆'),
  (2,1,'返回答案 / 拒答、引用、验证与编排状态',True),(1,0,'展示回答、来源与部分失败提示',True)]),
 ('四、用户反馈、冻结回放与策略审核（管理步骤通过 API / 脚本）',[
  (0,1,'提交反馈 / 纠错'),(1,2,'提交反馈类型、内容与 trace_id'),
  (2,5,'保存反馈，按规则关联失败案例'),(2,1,'返回反馈记录',True),
  (0,1,'管理员审核案例并提交策略候选'),(1,2,'提交审核 / propose 请求'),
  (2,5,'保存审核状态与受约束的策略 DSL'),
  (1,2,'提交源 Trace ID，发起冻结回放'),(2,5,'读取源 Trace，冻结输入与证据'),
  (2,2,'执行候选回放，对比基线，计算 Replay Gate'),
  (2,5,'保存回放报告与通过 / 拒绝状态'),(2,1,'返回回放结果，等待人工决策',True),
  (0,1,'人工批准通过回放的候选进入灰度'),(1,2,'提交 approve-gray 与灰度比例'),
  (2,5,'校验 REPLAY_PASSED，记录 GRAY 与审批人'),
  (2,1,'返回灰度状态；后续可晋升或回滚',True),(1,0,'展示策略审核与发布结果',True)])
]
row=84
height=230+sum(80+sum(80 if e[0]=='note' else row for e in events) for _,events in phases)+140
s=Drawing('业务时序图',2100,height)
xs=[95,365,660,955,1230,1500,1765,1990]
labels=['用户 / 管理员','Web / API 调用端','FastAPI / 全局编排','部门 Agent','检索与索引组件','MongoDB','Redis','语义运行时']
fills=['#fff4aa','#e8e6fa','#e8e6fa','#e8e6fa','#e8e6fa','#f9dddd','#e1f2eb','#fff5c7']
s.text(0,25,2100,46,'政衡可信政务问答系统业务时序图',31,True)
s.text(35,79,2030,35,'按真实调用顺序归纳；虚线箭头表示返回，黄色条表示业务阶段，激活条表示处理区间。',18,color='#777')
# actor
s.svg.append('<circle cx="95" cy="141" r="11" fill="#f2da62" stroke="#555" stroke-width="2"/>')
s.cell(84,130,22,22,'','ellipse;fillColor=#f2da62;strokeColor=#555;')
for p in [[(95,152),(95,181)],[(71,164),(119,164)],[(95,181),(75,204)],[(95,181),(115,204)]]: s.line(p)
s.text(15,204,160,28,labels[0],18)
for x,label in zip(xs[1:],labels[1:]): s.box(x-103,143,206,53,label,'#e8e6fa',20)
for x in xs: s.line([(x,237),(x,height-106)],dash=True)
y=250; n=0; phase_crops=[]
for title,events in phases:
    start=y
    s.box(295,y,1665,38,title,'#f5df61',21)
    y+=80
    # Active client and backend intervals. Smaller participant bars accompany each message.
    end=y+sum(80 if e[0]=='note' else row for e in events)-25
    for idx in [1,2]: s.rect(xs[idx]-9,y-25,18,end-(y-25), '#f0f4f4')
    for event in events:
        if event[0]=='note':
            s.box(740,y-25,1300,40,event[1],'#fff9db',17)
            y+=80; continue
        a,b,label,*ret=event; n+=1
        if a==b:
            x=xs[a]+9
            s.line([(x,y),(x+100,y),(x+100,y+22),(x,y+22)],True)
            s.text(x+17,y-29,400,29,f'{n}. {label}',18,back=True)
        else:
            ax=xs[a]+(9 if b>a and a in [1,2] else -9 if a in [1,2] else 0)
            bx=xs[b]+(-9 if b>a and b in [1,2] else 9 if b in [1,2] else 0)
            if b>2 and not ret:
                s.rect(xs[b]-8,y-12,16,38,fills[b])
                bx=xs[b]-8 if b>a else xs[b]+8
            s.line([(ax,y),(bx,y)],True,bool(ret))
            # Wrap long labels to keep them inside the available horizontal span.
            label=f'{n}. {label}'
            chunks=wrap_label(label,abs(bx-ax)-24)
            h=len(chunks)*22
            s.text(min(ax,bx)+8,y-h-5,abs(bx-ax)-16,h,'\n'.join(chunks),17,back=True)
        y+=row
    phase_crops.append((start,y))
s.text(30,height-88,2040,28,'说明：检索与索引组件合并表示 Python 检索逻辑、BGE、OpenSearch 和 Milvus；不代表额外独立部署的服务。',18,color='#777')
s.text(30,height-52,2040,28,'语义运行时可选 Pi / 兼容 LLM 接口；Compose 默认 Faux。回放内部调用已折叠，不表示无检索或无模型执行。',18,color='#777')
s.save('zhengheng-sequence')
combined=ET.Element('mxfile',host='app.diagrams.net')
combined.append(copy.deepcopy(s.page)); combined.append(copy.deepcopy(f.page))
ET.indent(combined)
ET.ElementTree(combined).write(OUT/'zhengheng-business-diagrams.drawio',encoding='utf-8',xml_declaration=True)
# Separate readable detail crops for review without reducing the full sequence.
from PIL import Image
im=Image.open(OUT/'zhengheng-sequence-preview.png')
for i,(top,bottom) in enumerate(phase_crops,1):
    im.crop((0,top-5,2100,bottom+15)).save(OUT/f'sequence-phase-{i}.png')
print('Sequence messages:',n)

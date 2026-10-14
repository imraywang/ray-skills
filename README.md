# ray-skills

Ray 的一些奇思妙想 Skill 集。

这里收录从真实问题出发做成的独立 Skill。每个 Skill 单独占一个目录，可以按需使用，不依赖统一入口。

其中 `ray-benchmark`、`ray-launch`、`ray-metrics`、`ray-report`、`ray-vps` 来自 [rayskills](https://github.com/imraywang/rayskills) v3 精简（2026-07-28）：方法论和 eval 场景完整保留，只是日常使用频率不高，从主工具箱移到这里按需取用。

`ray-broll`、`ray-consult`、`ray-multimodel`、`ray-trend-search` 来自 rayskills v4 精简（2026-10-13），原因同样是使用频率低；方法论、脚本和 eval 场景完整保留，已与 rayskills 的 `/ray` 总入口解耦，原来指向 ray-writer / ray-kb 等的交接改为“装了 rayskills 才用”的可选项。

## 现有 Skill

### grok-live-search

用本机官方 Grok CLI 做 X / Reddit / 网页实时检索。运行时跟随当前默认模型，不写死 `grok-4.5`。一次安装后同时给 Codex、Claude Code 和通用 Agent 用。详情见 [grok-live-search/README.md](grok-live-search/README.md)。

```bash
bash grok-live-search/install.sh
```

### ray-aluframe

帮助个人玩家和小工作室把铝型材架子的想法或参考图，整理成可核对、可询价的结构方案，包括：

- 尺寸和使用条件澄清
- 可在结构图与真实效果间切换、可旋转、可点选构件、可联动清单和装配步骤的交互预览
- 型材下料与用量
- 连接件和附件清单
- 型材、角码、螺栓、槽螺母、底脚和板材固定件的统一搭配清单
- 内置的型材、光轴、连接件和附件产品库，生成清单时不依赖外部网站
- 加工位置与装配顺序
- 变形、超载和高风险用途检查

详情见 [ray-aluframe/SKILL.md](ray-aluframe/SKILL.md)。

### ray-benchmark

拆一个对标对象（账号 / 产品 / 公司 / 赛道）：先过五重过滤劝退学不会的对象，再拆产品形态、定价变现、增长引擎和护城河，严格区分“因机制成功（能抄）”与“因禀赋成功（抄不来）”。详情见 [ray-benchmark/SKILL.md](ray-benchmark/SKILL.md)。

### ray-broll

把口播句或选题做成编辑隐喻拼贴视频：单句 5 秒 B-roll，或 45–60 秒带旁白、字幕的完整拼贴讲解片。隐喻 → 静帧 → 视频三道闸门按成本递增逐级确认，静帧和视频走 Gemini（视频可经 fal 切可灵 / Seedance），刚体组装镜头可改走 HyperFrames 确定性动画压成本。不做需要精确时间线的动画和真人实拍。详情见 [ray-broll/SKILL.md](ray-broll/SKILL.md)。

### ray-consult

企业知识库 / AI 落地咨询：先用 GROUND 六维诊断就绪度和风险，再出方案蓝图——建什么、怎么选型、分几期、谁来运营，并给出报价结构。用于评估企业能否上知识库、RAG 或智能体，不用于个人知识管理。详情见 [ray-consult/SKILL.md](ray-consult/SKILL.md)。

### ray-launch

把写好的落地页 / 官网 / B2B 询盘站从“代码就绪”带到“线上可访问、SEO 就绪、数据流通、可交接”：Vercel 部署、域名 DNS、ISR 数据流、表单询盘链路与真机验证。详情见 [ray-launch/SKILL.md](ray-launch/SKILL.md)。

### ray-metrics

X 账号数据周报：周环比、top / bottom 内容、可复现的传播规律与下周动作。详情见 [ray-metrics/SKILL.md](ray-metrics/SKILL.md)。

### ray-multimodel

在 Grok、Claude、Codex 之间分工协作，由当前会话主控验收：`fast` 让 Grok 先做清晰任务、`review` 找独立第二意见、`race` 两条通道竞争、`scout` 用 Grok 隔离搜索 X / Reddit 实时内容。简单问答不用。详情见 [ray-multimodel/SKILL.md](ray-multimodel/SKILL.md)。

其中 `scout` 的搜索组件（`scripts/run_search.py`、`scripts/reddit_dates.py` 与 `references/grok-search-reliability.md`）打包自 [sudoHG/codex-grok-search](https://github.com/sudoHG/codex-grok-search) v0.1.2，MIT 许可，版权与许可全文见 [ray-multimodel/LICENSE.codex-grok-search](ray-multimodel/LICENSE.codex-grok-search)。该组件固定使用 `grok-4.5`，与上面 `grok-live-search` 跟随默认模型的做法不同。

### ray-report

magazine 风格的 HTML / PDF 深度报告与公众号长报告，自带设计系统与印刷 CSS，不做成霓虹 SaaS dashboard。详情见 [ray-report/SKILL.md](ray-report/SKILL.md)。

### ray-trend-search

跨 X、Reddit、YouTube、Hacker News、Polymarket、抖音、视频号和网页做近期趋势调研，严格核对日期和证据。用于“最近大家怎么讨论”“近 N 天热点”“热门视频”“社区情绪”，不用于稳定事实或只查本地知识库。X / Reddit 依赖同目录下的 `ray-multimodel` 搜索脚本（两个目录需要一起安装）；YouTube / HN / Polymarket 依赖另装的 [last30days](https://github.com/mvanhorn/last30days-skill) Skill。详情见 [ray-trend-search/SKILL.md](ray-trend-search/SKILL.md)。

### ray-vps

VPS 开荒（加固、代理栈、防火墙、验证与交接）与节点巡检（`check` 模式只读不改）。详情见 [ray-vps/SKILL.md](ray-vps/SKILL.md)。

## 目录约定

```text
ray-skills/
├── grok-live-search/
├── ray-aluframe/
├── ray-benchmark/
├── ray-broll/
├── ray-consult/
├── ray-launch/
├── ray-metrics/
├── ray-multimodel/
├── ray-report/
├── ray-trend-search/
├── ray-vps/
└── 未来的其他 Skill/
```

每个目录都是一个可以独立使用和迭代的 Skill。

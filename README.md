# ray-skills

Ray 的一些奇思妙想 Skill 集。

这里收录从真实问题出发做成的独立 Skill。每个 Skill 单独占一个目录，可以按需使用，不依赖统一入口。

其中 `ray-benchmark`、`ray-launch`、`ray-metrics`、`ray-report`、`ray-vps` 来自 [rayskills](https://github.com/imraywang/rayskills) v3 精简（2026-07-28）：方法论和 eval 场景完整保留，只是日常使用频率不高，从主工具箱移到这里按需取用。

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

### ray-launch

把写好的落地页 / 官网 / B2B 询盘站从“代码就绪”带到“线上可访问、SEO 就绪、数据流通、可交接”：Vercel 部署、域名 DNS、ISR 数据流、表单询盘链路与真机验证。详情见 [ray-launch/SKILL.md](ray-launch/SKILL.md)。

### ray-metrics

X 账号数据周报：周环比、top / bottom 内容、可复现的传播规律与下周动作。详情见 [ray-metrics/SKILL.md](ray-metrics/SKILL.md)。

### ray-report

magazine 风格的 HTML / PDF 深度报告与公众号长报告，自带设计系统与印刷 CSS，不做成霓虹 SaaS dashboard。详情见 [ray-report/SKILL.md](ray-report/SKILL.md)。

### ray-vps

VPS 开荒（加固、代理栈、防火墙、验证与交接）与节点巡检（`check` 模式只读不改）。详情见 [ray-vps/SKILL.md](ray-vps/SKILL.md)。

## 目录约定

```text
ray-skills/
├── grok-live-search/
├── ray-aluframe/
├── ray-benchmark/
├── ray-launch/
├── ray-metrics/
├── ray-report/
├── ray-vps/
└── 未来的其他 Skill/
```

每个目录都是一个可以独立使用和迭代的 Skill。

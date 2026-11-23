# WP-SEO-GEO-Coach-Agent

A WordPress independent site audit and "white-hat" SEO coaching service—acting as a technical supervisor for foreign trade business owners and a hands-on, guided mentor for novice operators.

**给外贸老板当「技术监理」、给零基础运营当「带锁教练」的 WordPress 独立站体检与白帽 SEO 陪跑 MCP 引擎。**

*An engineering-grade WordPress Technical SEO Audit & Deterministic Coaching MCP Engine built for B2B Export Factories & Growth Teams.*

![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB.svg)
![MCP](https://img.shields.io/badge/Protocol-MCP_Server_(stdio%20%2F%20HTTP)-10B981.svg)
![Tests](https://img.shields.io/badge/Smoke_Tests-8%2F8_Passed-brightgreen.svg)

---

> [!TIP]
> **开源免费 + 懒人省心包（抖音同款）**
>
> 本仓库核心引擎 `wp_seo_coach.py`、测试套件与 `SKILL.md` 协议 **100% 开源免费**，懂技术的团队直接拉取即可投入生产。
>
> 如果你是外贸企业老板/高管，不想花半天折腾 Windows 环境和提示词，欢迎获取配套整理好的**《零基础员工 3 分钟开跑懒人包》**（含排版好的 WPS/PDF 操作手册、Windows 避坑清单、璇玑/Cursor 3 套老站起手式提示词与万能推进话术）：
> - **抖音互动领取**：关注抖音号 **马厂长的外贸笔记**，三连对应视频后评论区回复 **`体检`** 即可领取。
> - **配套客户端推荐**：这里顺便推荐一下我个人用了半年的国人自研智能体 **【璇玑】**，如果你也不希望被海外工具卡脖子，可以直接扫码注册配合本引擎使用：
>
> <img width="220" alt="璇玑智能体注册二维码" src="https://github.com/user-attachments/assets/48f39e8f-3734-4cd6-991c-7137287a457f" />

---

## 一、为什么写这个工具？（解决外贸老板最痛的 3 件事）

在给大量外贸工厂与 B2B 出口企业做独立站技术诊断时，最常见的问题不是“员工不努力”，而是**缺少一把能验收外包、能锁死流程的工程尺子**：

| 常见翻车现场 | 真实商业损失 | 本引擎的确定性解法 |
| :--- | :--- | :--- |
| **外包交付“精装样板房”** | 表面大气，底层却藏着**多 H1 冲突、AI 巨型 Base64 乱码图标、源站 IP 裸奔、虚假星级 Schema**，上线半年零询盘，老板不懂代码无从验收。 | **1 条命令免费全身体检（`audit`）**：无需服务器密码，几秒输出客观红绿体检单与修复方案，直接拿去验收外包。 |
| **新人不懂 SEO，乱用 AI 灌水** | 客户搜“厂家批发”却给看几千字科普长文；AI 瞎编公司背景和假评价；改坏网站没备份不敢动。 | **5 阶段 × 18 节点带锁状态机**：四步固定节拍（取任务 → 出清单等审批 → 执行并自动体检 → 交回执解锁），强制人类提供真实公司/工厂素材。 |
| **外链开发把公司邮箱干废** | 业务员直接拿公司主域名企业邮箱群发冷开发信，导致域名信誉拉黑，正常给老客户发的报价邮件全进海外垃圾箱。 | **外链漏斗 + 邮箱隔离硬锁**：自动剔除社媒/电商/高权威站和竞品，并发抓取 Contact/About 邮箱，生成英文草稿与 Excel 台账，**架构级禁止直连主域发信**。 |

---

## 二、核心架构与安全边界（企业高管放心交付版）

本项目采用**单文件零外部配置封装**（`wp_seo_coach.py`），内置完整的 `SKILL.md` 教官协议、状态机剧本库、体检引擎与 MCP 服务端，可直接挂载到 **璇玑桌面端、Cursor、Claude Code** 等支持 MCP 的 Agent 客户端。

### 1. 六条不可逾越的工程硬护栏
1. **凭证零接触（Local Encrypted Vault）**：所有 SSH、WP 应用密码、Cloudflare Token、SMTP 与调研 API 密钥全部通过 `Fernet` 加密存储在本地 `.wp_coach_vault/`，**严禁进入 AI 对话历史或云端记忆**，远端日志自动执行密钥脱敏。
2. **两段式审批锁（Plan → Confirm → Execute）**：任何涉及服务器、DNS、页面或配置的写操作，必须先调用 `workflow_plan_action` 生成可读 Diff 与 `plan_id`，经人类明确确认后才放行执行。
3. **客观体检验收锁（Signed Audit Receipt）**：AI 不允许口头宣称“已完成”，必须通过 `site_run_audit` 抓取真实线上页面/DNS/本地产物并签发防篡改回执，才能调用 `workflow_advance_stage` 解锁下一关。
4. **真实资产锁（Human Moat Lock）**：拒绝 `Lorem ipsum`、占位图与 AI 虚构背书；公司主体、实拍图与至少 2 条一线行业实操洞察必须由人类通过 `workflow_submit_asset` 登记入库。
5. **商业意图分流锁（Intent Split Lock）**：采购/定制/批发类商业词强制锁定为「自定义产品系列页」（首屏矩阵 + MOQ/参数 + CTA），拦截带 `Quick Answer` 等科普灌水套话；低 KD 信息词锁定为对比/指南博文并强制内链 200 预检。
6. **并发安全锁（Multi-Agent FileLock）**：内置文件级 `FileLock` 与原子状态写盘，支持多 Agent 并行调研（`seo_build_blueprint`）与主控教官单路串行写盘。

### 2. 内置 7 个高内聚 MCP 元工具
| 工具名 | 所属节拍 | 作用说明 |
| :--- | :--- | :--- |
| `workflow_get_task` | 第 1 拍：取任务 | 返回当前关卡原理、人类准备清单、允许动作与是否处于老站免 VPS 模式 |
| `workflow_submit_asset` | 人类素材锁 | 登记真实公司主体、实拍图、一线避坑洞察等资产，自动拦截占位符 |
| `workflow_plan_action` | 第 2 拍：出计划 | 生成可读修改 Diff 与 `plan_id`，拦截明文密钥入参和越权跳步动作 |
| `workflow_execute_plan` | 第 3 拍：受控执行 | 凭人类确认后的 `plan_id` 执行 SSH / Cloudflare / WP REST / SEO 管线 |
| `site_run_audit` | 第 3 拍：客观体检 | 实测 HTTPS、CDN、邮局端口/DNS、唯一 H1、Base64、Schema 及外链产物 |
| `seo_build_blueprint` | 只读调研（可并行） | 关键词商业/信息意图分流预览、外链 SERP 黑名单清洗预览 |
| `workflow_advance_stage` | 第 4 拍：通关解锁 | 校验回执签名与必填人类素材，全部达标后解锁下一节点/阶段 |

---

## 三、3 分钟极速上手

### 1. 环境准备（推荐 Python 3.11 / 3.12）
> [!IMPORTANT]
> 本引擎当前基于 `mcp` v1 接口构建，安装时请务必保留 `"mcp<2"` 双引号锁版本（Windows 环境下请勿省略双引号）。

```bash
pip install "mcp<2" pydantic httpx beautifulsoup4 dnspython cryptography paramiko filelock
```

*(国内网络如安装缓慢，可在 `install` 后追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`)*

### 2. 先跑 1 秒本地自测（验证环境无误）
```bash
python test_wp_seo_coach.py -v
```
看到输出 `Ran 8 tests ... OK` 即表示本地加密库、体检拦截器、18 节点状态机与 10 路并发锁全部就绪。

---

### 3. 零门槛体验：1 条命令给任意网站免费体检（无需 VPS / 无需密码）
```bash
python wp_seo_coach.py audit [https://你的域名.com](https://你的域名.com) --model b2b_export
```

**体检项全覆盖**：HTTPS 强制跳转与死循环检测 / Cloudflare 等 CDN 隐藏源站检测 / 邮局端口与 MX·SPF·DKIM·DMARC 解耦检测 / 唯一 H1 核验 / AI Base64·SVG 膨胀扫描 / JSON-LD Schema 真实性与防造假检测 / `robots.txt` 与 XML Sitemap / 合规条款页检测。

---

### 4. 三种已有老站直通起手式（免 VPS / 免 SSH）
如果你已经有现成的 WordPress 独立站，直接用 `init-existing` 命令把域名录入本地加密 Vault（WordPress 应用密码、Serper/Hunter API 均可直接回车跳过，零额外 API 费用即可配合 Agent 自带搜索跑通）：

```bash
# 模式 1（推荐）：跳过前 8 关建站基建，直接从 Stage 3 站内 SEO 体检切入
python wp_seo_coach.py vault init-existing --alias my_site --stage stage_03_onpage

# 模式 2：站内技术底子已 OK，直接从 Stage 4 关键词意图分流与内容工程切入
python wp_seo_coach.py vault init-existing --alias my_site --stage stage_04_content

# 模式 3：纯跑 Stage 5 外链 SERP 黑名单清洗、抓站长邮箱与导出开发信/CSV 台账
python wp_seo_coach.py vault init-existing --alias my_site --stage stage_05_outreach
```

*(如需从零买 Linux VPS 跟着跑 Stage 1 备份还原演练与全流程建站，使用 `python wp_seo_coach.py vault init --alias my_site`)*

---

### 5. 接入桌面端 AI Agent（璇玑 / Cursor / Claude Code）

1. **导出协议文件**：仓库已附带 `SKILL.md`（也可随时运行下面命令生成 UTF-8 版本），导入你的 Agent 作为 Skill 协议：
   ```bash
   python -c "import wp_seo_coach, pathlib; pathlib.Path('SKILL.md').write_text(wp_seo_coach.SKILL_MD.strip(), encoding='utf-8')"
   ```
2. **挂载本地 MCP（默认 `stdio` 模式）**：
   - **Command**：填入本机 `python.exe` 绝对路径（Windows 可在命令行运行 `where python` 获取第一行）。
   - **Args**：填入 `wp_seo_coach.py` 的纯英文无空格绝对路径（如 `F:\wp_seo_coach\wp_seo_coach.py`）。
   - 如需远程模式，启动参数追加 `--http` 即可切换为 `streamable-http`。
3. **在对话框发出开工指令**：
   > “严格遵循 `wp-seo-coach-workflow` 协议，查看 `my_site` 的当前关卡，并立刻跑一次 `site_run_audit` 体检，用大白话告诉我现在最该改哪几项。”

---

## 四、项目目录说明与隐私提醒

```text
WP-SEO-GEO-Coach-Agent/
├── wp_seo_coach.py          # 单文件全功能主引擎（CLI + Vault + 体检 + 执行器 + MCP 服务端）
├── test_wp_seo_coach.py     # 8 项零外部依赖冒烟测试与 10 路并发锁压测套件
├── SKILL.md                 # Agent 教官总纲协议（含四拍节拍与六条硬护栏）
├── .gitignore               # 已屏蔽本地加密保险箱与工作区数据
└── LICENSE                  # Apache-2.0 开源协议
```

> [!CAUTION]
> **二次开发或提交代码前请务必确认**：运行后本地自动生成的 `.wp_coach_vault/`（加密主密钥与凭证）和 `.wp_coach_workspaces/`（站点状态与外链台账）**绝不可提交至公开仓库**。

---

## 五、关于作者与独立诊断服务

- **作者**：马厂长（外贸独立站第三方技术诊断 · 只看不改 · 判断归我，执行归你）
- **独立站主页**：[machangzhang.com](https://machangzhang.com)
- **边界说明**：本开源工具免费交给你的内部运营或执行方在本地使用；如你的老站已经建好、有流量/产品页但询盘不动，需要第三方深度排查**站内抢词、6 通道 AI 爬虫真实穿透（ChatGPT / Perplexity / ClaudeBot）及商业页承接断点**，欢迎前往 [machangzhang.com](https://machangzhang.com) 提交站点，先给你 3 条能自己复核的真实读数。

---

## License

本项目基于 [Apache-2.0 License](./LICENSE) 开源。允许免费学习、企业内部部署与二次开发，请保留原作者版权与归属声明；严禁将本工具用于未授权站点扫描或垃圾邮件群发。

---

## ☕ 自愿打赏与支持

如果这套开源工具帮你避开了外包大坑或省下了团队摸索时间，欢迎自愿请喝杯咖啡支持持续迭代（打赏备注邮箱可同步接收最新懒人包与版本更新通知）：

<img width="220" alt="自愿打赏支持" src="https://github.com/user-attachments/assets/7fa4e373-27ff-416c-9261-ed9ecaf46aad" />

# WP-SEO-GEO-Coach-Agent
给外贸老板当‘技术监理’、给零基础运营当‘带锁教练’的 WordPress 独立站体检与白帽 SEO 陪跑引擎.A WordPress independent site audit and "white-hat" SEO coaching service—acting as a technical supervisor for foreign trade business owners and a hands-on, guided mentor for novice operators.
# WP-SEO-GEO-Coach-Agent

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
> - **方式 1（抖音互动领取）**：关注抖音号 **`【马厂长的外贸笔记】`**，三连对应视频后评论区回复 **`体检`** ， 此外我和团队还做了一个中国人自己的agent 名字叫【璇玑】，如果你也不希望被别人卡脖子，可以用用看，不会让大家吃亏的。扫描二维码注册👉<img width="900" height="900" alt="f9d1cabb6bfbdbfb1b1952c57fc3f86f" src="https://github.com/user-attachments/assets/48f39e8f-3734-4cd6-991c-7137287a457f" />

> - **方式 2（自愿打赏支持）**：如果这个工具帮你避开了几万块的外包大坑，欢迎扫码请喝杯咖啡，打赏备注邮箱可顺手获赠最新懒人包更新通知：
>
> <!-- 提示：在 GitHub 网页编辑 README 时，直接把你的打赏二维码图片拖进编辑框即可自动生成图片链接替换下面这行 -->
> <img src="【<img width="828" height="1124" alt="89b7498a0b28e09ba716b7a3c0715571" src="https://github.com/user-attachments/assets/7fa4e373-27ff-416c-9261-ed9ecaf46aad" />】" width="220" alt="自愿打赏支持" />

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

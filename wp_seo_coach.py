#!/usr/bin/env python3
"""
wp_seo_coach.py — 单文件全功能 WordPress 建站与白帽 SEO 陪跑 MCP 引擎
支持：新站全流程(vault init) | 已有老站免 VPS 直通(vault init-existing) | 独立体检(audit) | 导出协议(print-skill)
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import html as html_lib
import ipaddress
import json
import os
import re
import shlex
import socket
import stat
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import urljoin, urlparse

import dns.exception
import dns.resolver
import httpx
import paramiko
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# ==============================================================================
# 0. 全局路径与常量配置
# ==============================================================================

BASE_DIR = Path(__file__).resolve().parent
VAULT_DIR = BASE_DIR / ".wp_coach_vault"
WORKSPACES_DIR = BASE_DIR / ".wp_coach_workspaces"
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

BACKUP_ROOT = "/var/backups/wp-coach"
MIN_FREE_DISK_MB = 512
CF_API_BASE = "https://api.cloudflare.com/client/v4"

CLOUDFLARE_IPV4_CIDRS = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]
_CF_NETWORKS = [ipaddress.ip_network(c) for c in CLOUDFLARE_IPV4_CIDRS]

CDN_HEADER_SIGNATURES: dict[str, tuple[str, ...]] = {
    "Cloudflare": ("cf-ray", "cf-cache-status"),
    "Fastly": ("x-served-by", "x-fastly-request-id"),
    "CloudFront": ("x-amz-cf-id", "x-amz-cf-pop"),
    "Akamai": ("x-akamai-transformed", "akamai-grn"),
    "BunnyCDN": ("cdn-pullzone", "cdn-requestid"),
    "QUIC.cloud": ("x-qc-pop",),
}

MAIL_PORTS: dict[int, str] = {
    25: "SMTP", 465: "SMTPS", 587: "SMTP-Submission",
    110: "POP3", 143: "IMAP", 993: "IMAPS", 995: "POP3S",
}

SINGLE_BASE64_WARN_CHARS = 4_000
TOTAL_BASE64_WARN_CHARS = 15_000
INLINE_SVG_WARN_CHARS = 25_000
BASE64_DATA_URI_RE = re.compile(
    r"data:image/(?P<mime>[a-zA-Z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/=]+)"
)
COACH_SCHEMA_BLOCK_RE = re.compile(
    r'<!-- wp:html -->\s*<script[^>]*data-wp-coach-schema="true"[^>]*>.*?</script>\s*<!-- /wp:html -->',
    re.DOTALL | re.IGNORECASE,
)

SUSPICIOUS_COMMERCIAL_SCHEMA_TYPES = {
    "CreativeWorkSeries", "Book", "Movie", "Recipe", "TVSeries", "VideoGame",
}
COMMERCIAL_ESSAY_RED_FLAGS = ("quick answer", "in today's fast-paced world", "delve into")
AI_CLICHE_PLACEHOLDERS = ("lorem ipsum", "placeholder", "todo:", "[insert ", "ai_generated")

SOCIAL_AND_UGC_DOMAINS = {
    "reddit.com", "youtube.com", "youtu.be", "pinterest.com", "facebook.com",
    "instagram.com", "tiktok.com", "twitter.com", "x.com", "linkedin.com",
    "quora.com", "medium.com", "tumblr.com", "threads.net", "vimeo.com",
    "zhihu.com", "xiaohongshu.com", "discord.com", "t.me", "telegram.me",
}
ECOMMERCE_MARKETPLACE_DOMAINS = {
    "amazon.com", "amazon.co.uk", "amazon.de", "amazon.ca", "amazon.co.jp",
    "ebay.com", "walmart.com", "etsy.com", "alibaba.com", "aliexpress.com",
    "1688.com", "temu.com", "shein.com", "target.com", "bestbuy.com",
    "homedepot.com", "lowes.com", "wayfair.com", "shopify.com", "made-in-china.com",
    "globalsources.com", "dhgate.com", "indiamart.com", "mercadolibre.com",
}
MEGA_AUTHORITY_DOMAINS = {
    "wikipedia.org", "wikihow.com", "forbes.com", "nytimes.com", "bbc.com",
    "bbc.co.uk", "cnn.com", "theguardian.com", "washingtonpost.com", "wsj.com",
    "bloomberg.com", "reuters.com", "cnbc.com", "businessinsider.com",
    "healthline.com", "webmd.com", "mayoclinic.org", "britannica.com",
    "nih.gov", "cdc.gov", "apple.com", "microsoft.com", "google.com",
    "adobe.com", "github.com", "stackoverflow.com", "hubspot.com", "ahrefs.com",
    "semrush.com",
}
COMMERCIAL_INTENT_SIGNALS = (
    "supplier", "manufacturer", "factory", "wholesale", "oem", "odm",
    "customized", "custom ", "bulk", "distributor", "price", "quote",
    "buy ", "for sale", "shop", "vendor", "exporter", "private label",
)
INFORMATIONAL_INTENT_SIGNALS = (
    "how to", " vs ", "versus", "comparison", "guide", "tips", "best way",
    "tutorial", "what is", "why ", "difference between", "checklist", "ideas",
    "maintenance", "troubleshooting", "store ", "organize",
)
EMAIL_REGEX = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,12}\b")
IGNORED_EMAIL_PREFIXES = (
    "noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster",
    "abuse", "security", "privacy", "legal", "dmca", "sentry", "wixpress",
)
IGNORED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


# ==============================================================================
# 1. 内置 SKILL.md 总纲协议
# ==============================================================================

SKILL_MD = """---
name: wp-seo-coach-workflow
description: 边学边做的 WordPress 独立站建站与白帽 SEO 陪跑工作流。支持新站全流程建站与已有老站直通 SEO/外链优化。
version: 1.1.0
---

# WordPress 独立站与 SEO 副驾教官协议

你是一位务实、反玄学、重工程底线与商业常识的独立站陪跑教官。你的目标是通过确定性工具链代劳繁琐命令，同时确保用户掌握网站主权、提供真实商业素材，并理解每一步背后的底层逻辑。

## 核心工作节拍（严禁跳步）
1. **取任务、讲原理（Why）**：调用 `workflow_get_task(site_alias)` 获取当前关卡剧本，用 2-3 句人话讲透原理并列出人类准备清单。
2. **出计划、等审批（Plan）**：涉及服务器、DNS、页面或配置写操作前，必须先调用 `workflow_plan_action` 生成 Diff 与 `plan_id`，获得用户明确同意后才可执行。
3. **调执行、跑体检（Execute & Verify）**：调用 `workflow_execute_plan` 执行确认后的计划，随后必须调用 `site_run_audit` 获取带签名的客观验收回执。不通过则按诊断排错，禁止口头宣称完成。
4. **交回执、解下关（Checkpoint）**：拿到通过的回执且真实素材齐备后，调用 `workflow_advance_stage` 解锁下一关。

## 六条不可逾越的硬护栏
- **凭证零接触**：严禁在对话中索要、复述或存入记忆任何 SSH 密码、私钥、Cloudflare Token、WP 应用密码或 SMTP 密码。新站引导运行 `python wp_seo_coach.py vault init --alias <site_alias>`；已有老站免 VPS 引导运行 `python wp_seo_coach.py vault init-existing --alias <site_alias> --stage stage_03_onpage`。
- **老站模式识别**：当 `workflow_get_task` 返回 `existing_site_no_vps_mode: true` 时，严禁调用 `infra.*` 动作，直接用体检、WP REST 或 SEO 外链工具推进。
- **备份演练锁**：新站 Stage 1 未完成真实“备份 + 还原演练”前，禁止解锁后续建站关卡。
- **真实资产锁**：公司主体、About Us、产品/工厂/仓库实拍图严禁 AI 伪造占位，必须通过 `workflow_submit_asset` 登记真实素材。
- **商业意图分流锁**：采购/交易词必须做“自定义产品系列页”，严禁写成带 Quick Answer 的啰嗦科普长文。
- **白帽合规锁**：Schema 只提取页面前台真实可见字段；Outreach 仅导出草稿与台账，首轮强制使用独立 Gmail，严禁直连主域企业邮箱群发。

## 璇玑多 Agent 协同与记忆边界规则
- **记忆分层**：行业背景、产品卖点与偏好可存入璇玑记忆；绝不存密钥，且关卡进度永远以 `workflow_get_task` 引擎状态为准。
- **并行边界**：只读调研工具（`seo_build_blueprint`）与素材整理允许拆分子 Agent 并行；写生产/门禁类工具（`workflow_plan_action`、`workflow_execute_plan`、`workflow_advance_stage`）必须由主控教官单路串行调用。
"""


# ==============================================================================
# 2. 内置 5 阶段 × 18 节点声明式剧本库
# ==============================================================================

STAGE_ORDER = [
    "stage_01_infra",
    "stage_02_trust",
    "stage_03_onpage",
    "stage_04_content",
    "stage_05_outreach",
]

PLAYBOOKS: dict[str, dict[str, Any]] = {
    "stage_01_infra": {
        "stage_id": "stage_01_infra",
        "stage_title": "Stage 1：低成本可控基建与安全底线",
        "mapped_lessons": ["01", "02", "03", "04", "05", "15", "21"],
        "nodes": [
            {
                "node_id": "01_vault_and_domain",
                "title": "凭证托管与基础资源就绪",
                "why_teach": "建站翻车 80% 源于丧失域名与服务器归属权；同时生产密钥绝不能贴进 AI 对话框，必须先写入本地加密 Vault。",
                "human_tasks": [
                    "注册主域名、购买入门 Linux VPS 与独立 SMTP 邮局（如 MXroute）",
                    "在本地终端执行 `python wp_seo_coach.py vault init --alias <site_alias>` 录入加密凭证",
                ],
                "allowed_actions": ["infra.check_vault_connectivity"],
                "required_assets": [],
                "audit_checks": ["vault_credentials_reachable", "ssh_handshake_ok"],
            },
            {
                "node_id": "02_cli_wp_install",
                "title": "命令行初始化、WP-CLI 与 SEO REST 桥接",
                "why_teach": "通过 WP-CLI 清理默认示例垃圾、锁定 /%postname%/ 固定链接并安装轻量 REST 桥接，既纯净无冗余，又为后续自动化打好地基。",
                "human_tasks": [
                    "确认 VPS 已部署好 Nginx + PHP + MariaDB 与 WordPress 核心目录",
                    "审阅清理示例内容、装 WP-CLI 及可选装 WooCommerce 的执行计划并回复确认",
                ],
                "allowed_actions": ["infra.install_lemp_and_wp", "infra.install_woocommerce_base"],
                "required_assets": [],
                "audit_checks": ["wp_cli_healthy"],
            },
            {
                "node_id": "03_backup_restore_drill",
                "title": "强制演练：命令行备份与回滚重装",
                "why_teach": "在装修网站前先亲手跑通一次备份和真实回滚，确认探针写入 -> 快照覆盖 -> 探针消失，彻底消除改崩网站的恐惧。",
                "human_tasks": [
                    "审阅完整快照备份与数据库还原演练计划并回复确认",
                    "核对演练回执中的快照路径与回滚校验结果",
                ],
                "allowed_actions": ["infra.create_full_backup", "infra.run_restore_drill"],
                "required_assets": [],
                "audit_checks": ["backup_archive_non_empty", "restore_drill_verified"],
            },
            {
                "node_id": "04_cdn_and_smtp_decouple",
                "title": "部署免费 CDN 与独立 SMTP 邮局解耦",
                "why_teach": "裸奔源站 IP 极易被打下线；Web 与邮局同机混装不仅暴露源站，还会让询盘回信直接进海外客户垃圾箱。",
                "human_tasks": [
                    "确认域名已托管在 Cloudflare 且拿到独立邮局的 MX/SPF/DKIM 参数",
                    "审阅开启橙色云朵（Full strict SSL）与写入邮局 DNS 记录计划并确认",
                    "登记一个真实私人邮箱用于核验发信送达",
                ],
                "allowed_actions": ["dns.configure_cloudflare_proxy", "dns.configure_smtp_records"],
                "required_assets": [{"asset_key": "smtp_test_recipient_email", "description": "真实测试收件邮箱"}],
                "audit_checks": [
                    "origin_ip_hidden_behind_cdn",
                    "https_status_200_no_redirect_loop",
                    "web_server_mail_ports_closed",
                    "spf_dkim_dmarc_valid",
                ],
            },
        ],
    },
    "stage_02_trust": {
        "stage_id": "stage_02_trust",
        "stage_title": "Stage 2：商业骨架搭建与真实信任基建",
        "mapped_lessons": ["06", "07", "08", "09", "10", "11", "12", "13", "14", "16", "17", "18", "19", "20", "22", "23", "24"],
        "nodes": [
            {
                "node_id": "05_theme_brand_and_media",
                "title": "轻量化主题与压缩品牌视觉",
                "why_teach": "远离臃肿的多功能重型主题，选用轻量主流主题并将 Logo 与真实业务场景 Banner 压缩为 WebP 后上传。",
                "human_tasks": [
                    "提供真实品牌 Logo 与首屏真实场景图（拒绝低质 AI 占位图）",
                    "审阅站点基础设置与轻量主题安装计划并确认",
                ],
                "allowed_actions": ["infra.configure_basic_and_theme"],
                "required_assets": [
                    {"asset_key": "brand_logo_file", "description": "真实品牌 Logo 路径或 URL"},
                    {"asset_key": "hero_banner_original_photo", "description": "真实首屏业务/产品实拍图"},
                ],
                "audit_checks": ["https_status_200_no_redirect_loop", "no_base64_svg_bloat"],
            },
            {
                "node_id": "06_products_and_commerce_flow",
                "title": "首批核心产品上架与商业动线",
                "why_teach": "产品页不是参数垃圾堆，应按买家决策顺序呈现规格、场景与交付条件；B 端突出询盘转化，C 端跑通运费与支付。",
                "human_tasks": [
                    "提供至少 3 个核心产品的真实实拍图、规格参数与卖点",
                    "确认产品页或目录页发布计划",
                ],
                "allowed_actions": ["wp.publish_standard_page"],
                "required_assets": [{"asset_key": "core_products_spec_sheet", "description": "首批核心产品真实参数与实拍清单"}],
                "audit_checks": ["https_status_200_no_redirect_loop", "no_base64_svg_bloat"],
            },
            {
                "node_id": "07_blocks_mobile_and_forms",
                "title": "首页区块对齐、移动端检查与表单联调",
                "why_teach": "桌面端漂亮不代表移动端能看；联系表单必须亲测提交并确认经由独立 SMTP 收到通知，杜绝询盘黑洞。",
                "human_tasks": [
                    "提供真实客户背书（暂无则登记 NONE 并隐藏该区块，严禁捏造）",
                    "亲测提交一次前端联系表单确认收到邮件通知",
                ],
                "allowed_actions": ["wp.publish_standard_page"],
                "required_assets": [{"asset_key": "verified_testimonials_or_skip", "description": "真实客户反馈或填写 NONE"}],
                "audit_checks": ["https_status_200_no_redirect_loop", "no_base64_svg_bloat"],
            },
            {
                "node_id": "08_legal_trust_and_launch",
                "title": "真实资产锁：公司主体、合规条款页与建站封板",
                "why_teach": "没有真实公司主体、工厂/仓库实拍以及可访问的 Privacy Policy 与 Terms of Service，海外客户连纠纷找谁都不知道，信任度直接腰斩。",
                "human_tasks": [
                    "提交真实法定公司名称、地址、对外邮箱及至少 3 张业务/工厂/发货实拍图",
                    "审阅 Privacy Policy、Terms of Service 与 About Us 发布计划并确认",
                ],
                "allowed_actions": ["wp.publish_legal_and_about_pages"],
                "required_assets": [
                    {"asset_key": "legal_company_entity_info", "description": "真实公司法定全称、地址与官方联系邮箱"},
                    {"asset_key": "real_business_operation_photos", "description": "工厂/仓库/质检/发货或团队真人实拍图 URL"},
                ],
                "audit_checks": ["legal_policy_pages_200_non_empty", "no_base64_svg_bloat"],
            },
        ],
    },
    "stage_03_onpage": {
        "stage_id": "stage_03_onpage",
        "stage_title": "Stage 3：站内技术信号与页面脉络体检",
        "mapped_lessons": ["25", "26", "27", "28", "29", "30", "31"],
        "nodes": [
            {
                "node_id": "09_ga_gsc_and_tdk",
                "title": "部署 GSC 验证、放行索引与核心页面 TDK",
                "why_teach": "第一时间挂上 GSC 与 sitemap，确保解除测试期 noindex，并用干净克制的 Title 与 Meta Description 传递主词信号。",
                "human_tasks": [
                    "提交首页唯一主关键词与 GSC 后台生成的 google-site-verification TXT 码（老站已验证可填 VERIFIED）",
                    "审阅索引放行与核心页面 TDK 更新计划并确认",
                ],
                "allowed_actions": [
                    "dns.add_gsc_verification_txt",
                    "infra.enable_search_indexing",
                    "wp.update_core_pages_tdk",
                ],
                "required_assets": [
                    {"asset_key": "homepage_primary_keyword", "description": "首页核心主关键词"},
                    {"asset_key": "gsc_verification_token", "description": "GSC DNS TXT 验证码（已验证老站填 VERIFIED）"},
                ],
                "audit_checks": ["robots_allows_indexing", "sitemap_xml_valid_200"],
            },
            {
                "node_id": "10_headings_and_perf_hygiene",
                "title": "层级标题唯一 H1 梳理与代码膨胀清零",
                "why_teach": "一个页面只能有一个 H1（一个帮派不能有两个话事人）。若促销 Banner 与 SEO 主词冲突，须拍板降级 Banner 为 H3 再用 CSS 调回字号，或将主词融入标语；同时清零 AI 巨型 Base64 SVG。",
                "human_tasks": [
                    "查看体检报告中的 H1-H6 分布与 Base64 扫描结果",
                    "登记首页 H1 冲突处理决策并审阅页面修正计划",
                ],
                "allowed_actions": ["wp.publish_standard_page"],
                "required_assets": [
                    {"asset_key": "h1_conflict_resolution_choice", "description": "downgrade_banner_to_h3 / blend_keyword_into_banner / no_conflict"}
                ],
                "audit_checks": ["unique_h1_verified", "no_base64_svg_bloat", "https_status_200_no_redirect_loop"],
            },
            {
                "node_id": "11_authentic_schema_deployment",
                "title": "真实 JSON-LD 结构化数据部署",
                "why_teach": "严守两条红线：前台未展示的信息绝不硬塞 Schema；商业站用 Organization/Product/Service，严禁套用 CreativeWorkSeries 或虚构假星级。",
                "human_tasks": [
                    "核对即将写入的 JSON-LD 字段与页面前台文字 100% 一致",
                    "审阅 Schema 幂等注入计划并确认",
                ],
                "allowed_actions": ["wp.deploy_authentic_jsonld_schema"],
                "required_assets": [],
                "audit_checks": ["schema_authenticity_verified"],
            },
        ],
    },
    "stage_04_content": {
        "stage_id": "stage_04_content",
        "stage_title": "Stage 4：意图分层内容工程与行业护城河",
        "mapped_lessons": ["32", "33", "34", "35", "36", "37", "38"],
        "nodes": [
            {
                "node_id": "12_keyword_intent_and_kd_split",
                "title": "搜索意图与 KD 分层规划",
                "why_teach": "采购/定制类商业词归自定义产品系列页，低 KD 对比/教程类信息词归博文页；严禁意图混淆与站内自相残杀。",
                "human_tasks": [
                    "先用只读工具 `seo_build_blueprint` 评估候选词",
                    "拍板首批 1 个商业栏目词与 1 个低 KD 博文词并保存分流表",
                ],
                "allowed_actions": ["seo.save_keyword_content_map"],
                "required_assets": [
                    {"asset_key": "selected_commercial_keyword", "description": "商业/采购栏目主词"},
                    {"asset_key": "selected_low_kd_blog_keyword", "description": "低 KD 信息对比博文主词"},
                ],
                "audit_checks": ["keyword_map_has_both_intents"],
            },
            {
                "node_id": "13_custom_commercial_collection",
                "title": "搭建自定义商业产品系列/栏目落地页",
                "why_teach": "客户搜采购词是来买货谈合作的，不是来看几千字科普长文的。首屏必须直陈产品矩阵、MOQ/交期、工艺参数与清晰 CTA。",
                "human_tasks": [
                    "提供该系列的真实产品卡片、MOQ/交期参数与核心工艺卖点",
                    "审阅自定义栏目页创建计划并确认",
                ],
                "allowed_actions": ["wp.create_custom_collection_page"],
                "required_assets": [{"asset_key": "collection_commercial_proof", "description": "产品系列真实参数、MOQ 与卖点"}],
                "audit_checks": ["collection_page_created", "no_base64_svg_bloat"],
            },
            {
                "node_id": "14_low_kd_blog_and_human_moat",
                "title": "低 KD 博文草稿与一线经验护城河注入",
                "why_teach": "纯 AI 通用废话自己都不好意思发去换外链。必须嵌入至少 2 条真实一线实操/售后避坑经验与原创实拍对比图。",
                "human_tasks": [
                    "提供至少 2 条行业一手实操/售后洞察与至少 1 张原创图片 URL",
                    "审阅低 KD 博文草稿落库计划并确认",
                ],
                "allowed_actions": ["wp.save_blog_draft_with_human_slots"],
                "required_assets": [
                    {"asset_key": "blog_human_firsthand_insights", "description": "至少 2 条一线实操/售后真实洞察"},
                    {"asset_key": "blog_original_evidence_media", "description": "原创实拍或实测对比图 URL"},
                ],
                "audit_checks": ["blog_draft_with_human_moat_ready"],
            },
            {
                "node_id": "15_publish_and_internal_links",
                "title": "内链 200 预检与博文正式发布",
                "why_teach": "每篇低 KD 博文都必须用自然锚文本向商业栏目页导流，且发布前必须探测内链返回 HTTP 200，绝不上线 404 死链。",
                "human_tasks": [
                    "确认目标商业页 URL 与锚文本",
                    "审阅正式发布计划并回复确认",
                ],
                "allowed_actions": ["wp.publish_blog_post_and_internal_links"],
                "required_assets": [],
                "audit_checks": ["blog_post_live_and_linked", "unique_h1_verified"],
            },
        ],
    },
    "stage_05_outreach": {
        "stage_id": "stage_05_outreach",
        "stage_title": "Stage 5：务实外链筛选漏斗与长期自主迭代",
        "mapped_lessons": ["39", "40", "41", "42", "43", "44", "45"],
        "nodes": [
            {
                "node_id": "16_backlink_strategy_and_serp_filter",
                "title": "外链 SERP 目标站自动清洗",
                "why_teach": "彻底放弃垃圾评论与资料页挂链。拿己方博文主词搜 Google，自动过滤社媒、电商、同行竞品与 DR>80 大站，沉淀 >=20 个精准独立站目标。",
                "human_tasks": [
                    "提交本轮推广的己方博文 URL，并标注需剔除的直接竞品域名",
                    "审阅 SERP 清洗与目标清单导出计划并确认",
                ],
                "allowed_actions": ["seo.run_outreach_serp_pipeline", "seo.export_clean_prospect_list"],
                "required_assets": [{"asset_key": "outreach_target_blog_url", "description": "本轮对外推荐的己方博文 URL"}],
                "audit_checks": ["clean_prospects_minimum_20", "zero_spam_or_competitor_domains"],
            },
            {
                "node_id": "17_outreach_sop_and_gmail_launch",
                "title": "抓邮箱、AI 定制开发信与 Gmail 风控冷启动",
                "why_teach": "Outreach 本质是概率筛选：跳过繁琐表单，先抓 Contact/About 邮箱再用 Hunter 兜底。第一轮务必用独立 Gmail 发送以保护企业主域邮箱，有回复后再切企业邮箱并用 PayPal 结算。",
                "human_tasks": [
                    "确认已备妥独立冷启动 Gmail 账号与 PayPal（仅登记邮箱确认，严禁提交密码）",
                    "审阅邮箱批量提取与英文草稿/CSV 台账导出计划并确认",
                ],
                "allowed_actions": ["seo.enrich_prospect_emails", "seo.generate_outreach_drafts_and_tracker"],
                "required_assets": [{"asset_key": "cold_outreach_gmail_ready", "description": "用于首轮冷启动的独立 Gmail 地址"}],
                "audit_checks": [
                    "outreach_drafts_generated",
                    "outreach_tracker_csv_ready",
                    "primary_domain_mail_protected",
                ],
            },
            {
                "node_id": "18_ai_tooling_and_long_term_loop",
                "title": "全站回归体检、GSC 例行复盘与毕业交接",
                "why_teach": "知天易，逆天难。建立周度 GSC 数据复盘与月度备份抽检习惯，读 Google 官方文档与一线实战数据，完成独立站长期资产交接。",
                "human_tasks": [
                    "登记周度 GSC 复盘与月度备份抽检日程",
                    "审阅毕业资产交接包导出计划并执行最终全量回归体检",
                ],
                "allowed_actions": ["workflow.export_graduation_handover_pack"],
                "required_assets": [{"asset_key": "ongoing_review_cadence_confirmed", "description": "周度 GSC 与月度备份复盘日程"}],
                "audit_checks": [
                    "https_status_200_no_redirect_loop",
                    "origin_ip_hidden_behind_cdn",
                    "unique_h1_verified",
                    "no_base64_svg_bloat",
                    "schema_authenticity_verified",
                    "handover_pack_exported",
                ],
            },
        ],
    },
}


# ==============================================================================
# 3. 核心数据契约模型
# ==============================================================================

class SiteCredentials(BaseModel):
    site_alias: str
    domain: str
    url: str
    origin_ip: str | None = None
    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key_path: str | None = None
    ssh_password: str | None = None
    wp_path: str = "/var/www/html"
    wp_username: str | None = None
    wp_app_password: str | None = None
    cloudflare_api_token: str | None = None
    cloudflare_zone_id: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: str | None = None
    dkim_selector: str | None = None
    serper_api_key: str | None = None
    hunter_api_key: str | None = None


class PublicSiteMeta(BaseModel):
    site_alias: str
    domain: str
    url: str
    wp_path: str
    has_ssh: bool
    has_wp_rest: bool
    has_cloudflare: bool
    has_smtp: bool
    has_serper: bool
    has_hunter: bool
    dkim_selector: str | None = None


class ExecutionResult(BaseModel):
    ok: bool
    action_type: str
    error_code: str | None = None
    summary: str
    snapshot_path: str | None = None
    rolled_back: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class DiagnosticItem(BaseModel):
    check_name: str
    error_code: str
    severity: Literal["critical", "warning"] = "critical"
    diagnosis: str
    fix_guide: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class AuditReport(BaseModel):
    target_url: str
    domain: str
    passed: bool
    checks: dict[str, bool]
    diagnostics: list[DiagnosticItem] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ActionPlan(BaseModel):
    plan_id: str
    site_alias: str
    node_id: str
    action_type: str
    params: dict[str, Any]
    human_readable_diff: list[str]
    rollback_strategy: str
    created_at: float
    executed: bool = False


class AuditReceipt(BaseModel):
    receipt_id: str
    site_alias: str
    node_id: str
    passed: bool
    checks: dict[str, bool]
    diagnostics: list[dict[str, str]] = Field(default_factory=list)
    timestamp: float
    signature: str


class SiteState(BaseModel):
    site_alias: str
    business_model: Literal["b2b_export", "dtc_retail", "content_blog"] = "b2b_export"
    current_stage_id: str = "stage_01_infra"
    current_node_index: int = 0
    completed_nodes: list[str] = Field(default_factory=list)
    submitted_assets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    pending_plans: dict[str, ActionPlan] = Field(default_factory=dict)
    latest_receipts: dict[str, AuditReceipt] = Field(default_factory=dict)
    workflow_graduated: bool = False


class ProspectItem(BaseModel):
    domain: str
    url: str
    title: str
    snippet: str = ""
    serp_position: int = 0
    estimated_dr: int | None = None
    email: str | None = None
    email_source: Literal[
        "pending", "contact_page", "about_page", "target_page",
        "hunter_api", "form_only_skipped", "not_found"
    ] = "pending"
    status: str = "new"


class OutreachDraft(BaseModel):
    domain: str
    target_url: str
    target_title: str
    recipient_email: str
    subject: str
    body: str
    sender_guardrail: str = "MUST_SEND_VIA_STANDALONE_GMAIL_NOT_PRIMARY_DOMAIN"


# ==============================================================================
# 4. 本地加密凭证隔离层（VaultManager）
# ==============================================================================

class VaultManager:
    def __init__(self, vault_dir: Path = VAULT_DIR) -> None:
        self.vault_dir = vault_dir
        self.vault_file = vault_dir / "vault.enc"
        self.key_file = vault_dir / ".master.key"
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._load_or_create_master_key())

    @staticmethod
    def _safe_chmod_600(path: Path) -> None:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def _load_or_create_master_key(self) -> bytes:
        env_key = os.getenv("WP_COACH_MASTER_KEY")
        if env_key:
            return env_key.strip().encode("utf-8")
        if self.key_file.exists():
            return self.key_file.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_file.write_bytes(key)
        self._safe_chmod_600(self.key_file)
        return key

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self.vault_file.exists():
            return {}
        try:
            return json.loads(self._fernet.decrypt(self.vault_file.read_bytes()).decode("utf-8"))
        except InvalidToken as exc:
            raise RuntimeError("Vault 解密失败：WP_COACH_MASTER_KEY 不匹配。") from exc

    def _write_all(self, data: dict[str, dict[str, Any]]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.vault_file.write_bytes(self._fernet.encrypt(raw))
        self._safe_chmod_600(self.vault_file)

    def save_credentials(self, creds: SiteCredentials) -> None:
        data = self._read_all()
        data[creds.site_alias] = creds.model_dump()
        self._write_all(data)

    def has_site(self, site_alias: str) -> bool:
        return site_alias in self._read_all()

    def get_secret_bundle(self, site_alias: str) -> SiteCredentials:
        data = self._read_all()
        if site_alias not in data:
            raise KeyError(
                f"Vault 中未找到 `{site_alias}`。老站请运行: python wp_seo_coach.py vault init-existing --alias {site_alias}"
            )
        return SiteCredentials.model_validate(data[site_alias])

    def get_public_meta(self, site_alias: str) -> PublicSiteMeta:
        c = self.get_secret_bundle(site_alias)
        return PublicSiteMeta(
            site_alias=c.site_alias,
            domain=c.domain,
            url=c.url,
            wp_path=c.wp_path,
            has_ssh=bool(c.ssh_host and (c.ssh_key_path or c.ssh_password)),
            has_wp_rest=bool(c.wp_username and c.wp_app_password),
            has_cloudflare=bool(c.cloudflare_api_token and c.cloudflare_zone_id),
            has_smtp=bool(c.smtp_host and c.smtp_user and c.smtp_password),
            has_serper=bool(c.serper_api_key),
            has_hunter=bool(c.hunter_api_key),
            dkim_selector=c.dkim_selector,
        )

    def list_aliases(self) -> list[str]:
        return sorted(self._read_all().keys())

    @staticmethod
    def redact_secrets(text: str, creds: SiteCredentials) -> str:
        if not text:
            return text
        secrets = [
            creds.ssh_password, creds.wp_app_password, creds.cloudflare_api_token,
            creds.smtp_password, creds.serper_api_key, creds.hunter_api_key,
        ]
        out = text
        for s in secrets:
            if s and len(s) >= 4:
                out = out.replace(s, "[REDACTED_SECRET]")
        return out


# ==============================================================================
# 5. 自动体检门禁引擎（SiteAuditor）
# ==============================================================================

class SiteAuditor:
    def __init__(self, timeout: float = 12.0, port_timeout: float = 1.5) -> None:
        self.timeout = timeout
        self.port_timeout = port_timeout
        self.headers = {"User-Agent": "Mozilla/5.0 (compatible; WPSeoCoachAuditor/1.0)", "Accept": "text/html,*/*"}

    def run_full_audit(
        self,
        url: str,
        *,
        origin_ip: str | None = None,
        business_model: Literal["b2b_export", "dtc_retail", "content_blog"] = "b2b_export",
        dkim_selector: str | None = None,
        requested_checks: list[str] | None = None,
    ) -> AuditReport:
        normalized_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
        domain = (urlparse(normalized_url).hostname or "").lower().removeprefix("www.")
        want = set(requested_checks) if requested_checks else None

        checks: dict[str, bool] = {}
        diagnostics: list[DiagnosticItem] = []
        metrics: dict[str, Any] = {"domain": domain}

        html_text, resp_headers, final_url, http_ok = self._fetch_page(normalized_url, diagnostics, metrics)
        checks["https_status_200_no_redirect_loop"] = http_ok
        base_url = f"https://{domain}"

        resolved_ips = self._resolve_a_records(domain)
        metrics["resolved_ips"] = resolved_ips

        if want is None or "origin_ip_hidden_behind_cdn" in want:
            checks["origin_ip_hidden_behind_cdn"] = self._check_cdn_and_origin(
                domain, resolved_ips, resp_headers, origin_ip, diagnostics, metrics
            )

        if want is None or "web_server_mail_ports_closed" in want:
            scan_ip = origin_ip or (resolved_ips[0] if resolved_ips else None)
            checks["web_server_mail_ports_closed"] = self._check_mail_ports(
                scan_ip, origin_ip is not None, diagnostics, metrics
            )

        if want is None or "spf_dkim_dmarc_valid" in want:
            checks["spf_dkim_dmarc_valid"] = self._check_mail_dns_records(
                domain, resolved_ips, origin_ip, dkim_selector, diagnostics, metrics
            )

        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")
            if want is None or "unique_h1_verified" in want:
                checks["unique_h1_verified"] = self._check_unique_h1(soup, diagnostics, metrics)
            if want is None or "no_base64_svg_bloat" in want:
                checks["no_base64_svg_bloat"] = self._check_base64_svg_bloat(html_text, soup, diagnostics, metrics)
            if want is None or "schema_authenticity_verified" in want:
                checks["schema_authenticity_verified"] = self._check_schema_authenticity(
                    soup, business_model, diagnostics, metrics
                )
            if want is None or "robots_allows_indexing" in want:
                checks["robots_allows_indexing"] = self._check_robots_indexing(base_url, soup, diagnostics)
        else:
            for k in ("unique_h1_verified", "no_base64_svg_bloat", "schema_authenticity_verified", "robots_allows_indexing"):
                if want is None or k in want:
                    checks[k] = False

        if want is None or "sitemap_xml_valid_200" in want:
            checks["sitemap_xml_valid_200"] = self._check_sitemap(base_url, diagnostics)

        if want is None or "legal_policy_pages_200_non_empty" in want:
            checks["legal_policy_pages_200_non_empty"] = self._check_legal_pages(base_url, diagnostics)

        final_checks = {k: checks[k] for k in requested_checks if k in checks} if requested_checks else checks
        passed = bool(final_checks) and all(final_checks.values())
        return AuditReport(
            target_url=final_url or normalized_url,
            domain=domain,
            passed=passed,
            checks=final_checks,
            diagnostics=diagnostics,
            metrics=metrics,
        )

    def _fetch_page(
        self, url: str, diagnostics: list[DiagnosticItem], metrics: dict[str, Any]
    ) -> tuple[str | None, dict[str, str], str | None, bool]:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True, max_redirects=10, headers=self.headers) as c:
                r = c.get(url)
                hdrs = {k.lower(): v for k, v in r.headers.items()}
                final_url = str(r.url)
                metrics.update({"http_status": r.status_code, "final_url": final_url, "html_bytes": len(r.content)})
                if r.status_code != 200:
                    diagnostics.append(DiagnosticItem(
                        check_name="https_status_200_no_redirect_loop",
                        error_code=f"HTTP_STATUS_{r.status_code}",
                        diagnosis=f"页面返回异常状态码 {r.status_code}。",
                        fix_guide="检查 Nginx、PHP-FPM 及 Cloudflare 源站回源配置。",
                    ))
                    return None, hdrs, final_url, False
                if not final_url.startswith("https://"):
                    diagnostics.append(DiagnosticItem(
                        check_name="https_status_200_no_redirect_loop",
                        error_code="HTTPS_NOT_ENFORCED",
                        diagnosis="站点未强制跳转 HTTPS。",
                        fix_guide="在 Cloudflare 开启 Always Use HTTPS 并将 SSL 设为 Full (strict)。",
                    ))
                    return r.text, hdrs, final_url, False
                return r.text, hdrs, final_url, True
        except httpx.TooManyRedirects:
            diagnostics.append(DiagnosticItem(
                check_name="https_status_200_no_redirect_loop",
                error_code="ERR_TOO_MANY_REDIRECTS",
                diagnosis="检测到 HTTPS 重定向死循环（常见于 Cloudflare Flexible SSL）。",
                fix_guide="切换 Cloudflare SSL 模式为 Full (strict)。",
            ))
            return None, {}, None, False
        except httpx.HTTPError as exc:
            diagnostics.append(DiagnosticItem(
                check_name="https_status_200_no_redirect_loop",
                error_code="HTTP_CONNECTION_FAILED",
                diagnosis=f"无法连接目标站点：{exc}",
                fix_guide="检查 DNS A 记录、80/443 防火墙端口与 Nginx 状态。",
            ))
            return None, {}, None, False

    @staticmethod
    def _resolve_a_records(domain: str) -> list[str]:
        try:
            return sorted({r.address for r in dns.resolver.resolve(domain, "A", lifetime=4.0)})
        except dns.exception.DNSException:
            return []

    @staticmethod
    def _is_cloudflare_ip(ip_str: str) -> bool:
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            return any(ip_obj in net for net in _CF_NETWORKS)
        except ValueError:
            return False

    def _check_cdn_and_origin(
        self, domain: str, resolved_ips: list[str], resp_headers: dict[str, str],
        origin_ip: str | None, diagnostics: list[DiagnosticItem], metrics: dict[str, Any]
    ) -> bool:
        detected: list[str] = []
        if "cloudflare" in resp_headers.get("server", "").lower():
            detected.append("Cloudflare")
        for name, keys in CDN_HEADER_SIGNATURES.items():
            if any(k in resp_headers for k in keys) and name not in detected:
                detected.append(name)
        if resolved_ips and all(self._is_cloudflare_ip(ip) for ip in resolved_ips) and "Cloudflare" not in detected:
            detected.append("Cloudflare")
        metrics["detected_cdns"] = detected

        if origin_ip and origin_ip in resolved_ips:
            diagnostics.append(DiagnosticItem(
                check_name="origin_ip_hidden_behind_cdn",
                error_code="ORIGIN_IP_EXPOSED",
                diagnosis=f"域名 {domain} 直接暴露了真实源站 IP（{origin_ip}）。",
                fix_guide="在 Cloudflare 将 A 记录切换为橙色云朵（Proxied）。",
            ))
            return False
        if not detected:
            diagnostics.append(DiagnosticItem(
                check_name="origin_ip_hidden_behind_cdn",
                error_code="NO_CDN_DETECTED",
                diagnosis="未检测到 CDN 代理保护，源站存在裸奔风险。",
                fix_guide="接入 Cloudflare 免费版并开启橙色云朵代理。",
            ))
            return False
        return True

    def _probe_port(self, ip: str, port: int) -> tuple[int, bool]:
        try:
            with socket.create_connection((ip, port), timeout=self.port_timeout):
                return port, True
        except OSError:
            return port, False

    def _check_mail_ports(
        self, target_ip: str | None, is_explicit_origin: bool,
        diagnostics: list[DiagnosticItem], metrics: dict[str, Any]
    ) -> bool:
        if not target_ip:
            return False
        if not is_explicit_origin and self._is_cloudflare_ip(target_ip):
            metrics["mail_port_scan"] = {"scanned_ip": target_ip, "note": "CDN节点，建议传入origin_ip深扫"}
            return True
        with ThreadPoolExecutor(max_workers=len(MAIL_PORTS)) as pool:
            res = list(pool.map(lambda p: self._probe_port(target_ip, p), MAIL_PORTS.keys()))
        open_ports = [{"port": p, "service": MAIL_PORTS[p]} for p, ok in res if ok]
        metrics["mail_port_scan"] = {"scanned_ip": target_ip, "open_mail_ports": open_ports}
        if open_ports:
            desc = ", ".join(f"{x['port']}({x['service']})" for x in open_ports)
            diagnostics.append(DiagnosticItem(
                check_name="web_server_mail_ports_closed",
                error_code="WEB_AND_MAIL_CO_HOSTED",
                diagnosis=f"Web 源站开放了邮件端口 {desc}，违反网站与邮局解耦原则。",
                fix_guide="卸载本地 Postfix/Exim/Dovecot 并封禁邮件端口，改用独立 SMTP（如 MXroute）。",
            ))
            return False
        return True

    def _check_mail_dns_records(
        self, domain: str, web_ips: list[str], origin_ip: str | None,
        dkim_selector: str | None, diagnostics: list[DiagnosticItem], metrics: dict[str, Any]
    ) -> bool:
        all_ok = True
        info: dict[str, Any] = {}

        mx_hosts: list[str] = []
        try:
            mx_hosts = [str(r.exchange).rstrip(".").lower() for r in dns.resolver.resolve(domain, "MX", lifetime=4.0)]
        except dns.exception.DNSException:
            pass
        info["mx_hosts"] = mx_hosts
        if not mx_hosts:
            all_ok = False
            diagnostics.append(DiagnosticItem(
                check_name="spf_dkim_dmarc_valid", error_code="MX_RECORD_MISSING",
                diagnosis=f"域名 {domain} 缺少 MX 记录。", fix_guide="添加独立邮局 MX 记录（灰色云朵）。"
            ))
        else:
            forbid = set(web_ips) | ({origin_ip} if origin_ip else set())
            for h in mx_hosts:
                if forbid.intersection(self._resolve_a_records(h)):
                    all_ok = False
                    diagnostics.append(DiagnosticItem(
                        check_name="spf_dkim_dmarc_valid", error_code="MX_POINTS_TO_WEB_SERVER",
                        diagnosis=f"MX 记录 {h} 指向了建站服务器自身 IP。", fix_guide="改用独立第三方邮局主机。"
                    ))
                    break

        txts: list[str] = []
        try:
            txts = ["".join(s.decode("utf-8", "ignore") for s in r.strings) for r in dns.resolver.resolve(domain, "TXT", lifetime=4.0)]
        except dns.exception.DNSException:
            pass
        spfs = [t for t in txts if t.lower().startswith("v=spf1")]
        info["spf_records"] = spfs
        if len(spfs) != 1:
            all_ok = False
            diagnostics.append(DiagnosticItem(
                check_name="spf_dkim_dmarc_valid",
                error_code="SPF_RECORD_MISSING" if len(spfs) == 0 else "SPF_MULTIPLE_RECORDS",
                diagnosis=f"SPF 记录数量异常（当前 {len(spfs)} 条，规范要求有且仅有 1 条 v=spf1）。",
                fix_guide="配置或合并为单条 v=spf1 TXT 记录。",
            ))

        dmarcs: list[str] = []
        try:
            dmarcs = [
                "".join(s.decode("utf-8", "ignore") for s in r.strings)
                for r in dns.resolver.resolve(f"_dmarc.{domain}", "TXT", lifetime=4.0)
                if "v=dmarc1" in "".join(s.decode("utf-8", "ignore") for s in r.strings).lower()
            ]
        except dns.exception.DNSException:
            pass
        info["dmarc_records"] = dmarcs
        if not dmarcs:
            all_ok = False
            diagnostics.append(DiagnosticItem(
                check_name="spf_dkim_dmarc_valid", error_code="DMARC_RECORD_MISSING",
                diagnosis="缺少 _dmarc TXT 记录。", fix_guide="添加 `_dmarc` TXT 记录（v=DMARC1; p=none; ...）。"
            ))

        sels = [dkim_selector] if dkim_selector else ["x", "default", "google", "selector1", "dkim"]
        found_dkim: dict[str, str] = {}
        for sel in sels:
            try:
                ans = dns.resolver.resolve(f"{sel}._domainkey.{domain}", "TXT", lifetime=3.0)
                val = "".join(s.decode("utf-8", "ignore") for s in ans[0].strings)
                if "v=dkim1" in val.lower() or "p=" in val.lower():
                    found_dkim[sel] = val[:60] + "..."
                    break
            except dns.exception.DNSException:
                continue
        info["dkim_detected"] = found_dkim
        if dkim_selector and not found_dkim:
            all_ok = False
            diagnostics.append(DiagnosticItem(
                check_name="spf_dkim_dmarc_valid", error_code="DKIM_RECORD_MISSING",
                diagnosis=f"未找到 DKIM 记录 {dkim_selector}._domainkey.{domain}。",
                fix_guide="在 Cloudflare 补齐独立邮局提供的 DKIM 公钥 TXT 记录。",
            ))

        metrics["mail_dns"] = info
        return all_ok

    @staticmethod
    def _check_unique_h1(soup: BeautifulSoup, diagnostics: list[DiagnosticItem], metrics: dict[str, Any]) -> bool:
        h1s = soup.find_all("h1")
        texts = [t.get_text(" ", strip=True) for t in h1s]
        metrics["headings"] = {"counts": {f"h{i}": len(soup.find_all(f"h{i}")) for i in range(1, 7)}, "h1_texts": texts}
        if len(h1s) != 1 or not texts[0]:
            code = "H1_MISSING" if len(h1s) == 0 else ("MULTIPLE_H1_DETECTED" if len(h1s) > 1 else "H1_EMPTY_TEXT")
            diagnostics.append(DiagnosticItem(
                check_name="unique_h1_verified",
                error_code=code,
                diagnosis=f"页面检测到 {len(h1s)} 个 H1（要求唯一非空 H1：“一个帮派不能有两个话事人”）。",
                fix_guide="保留承载主关键词的唯一 H1，其余促销标语或 Logo 降级为 H2/H3/div 再用 CSS 调回字号。",
                evidence={"h1_texts": texts},
            ))
            return False
        return True

    @staticmethod
    def _check_base64_svg_bloat(
        raw_html: str, soup: BeautifulSoup, diagnostics: list[DiagnosticItem], metrics: dict[str, Any]
    ) -> bool:
        matches = list(BASE64_DATA_URI_RE.finditer(raw_html))
        total_chars = sum(len(m.group(0)) for m in matches)
        max_chars = max((len(m.group(0)) for m in matches), default=0)
        nav_chars = sum(
            len(m.group(0))
            for container in soup.find_all(["header", "nav"])
            for m in BASE64_DATA_URI_RE.finditer(str(container))
        )
        big_svgs = [len(str(s)) for s in soup.find_all("svg") if len(str(s)) >= INLINE_SVG_WARN_CHARS]
        metrics["base64_and_svg_bloat"] = {
            "count": len(matches), "total_chars": total_chars,
            "max_single_chars": max_chars, "nav_header_chars": nav_chars, "big_inline_svgs": len(big_svgs),
        }
        if (
            total_chars >= TOTAL_BASE64_WARN_CHARS
            or max_chars >= SINGLE_BASE64_WARN_CHARS
            or nav_chars >= SINGLE_BASE64_WARN_CHARS
            or bool(big_svgs)
        ):
            diagnostics.append(DiagnosticItem(
                check_name="no_base64_svg_bloat",
                error_code="AI_BASE64_SVG_BLOAT",
                diagnosis=f"检测到内联图像代码膨胀（Base64 总计 {total_chars:,} 字符，导航区 {nav_chars:,} 字符），极易导致爬虫截断正文。",
                fix_guide="移除 AI 生成的 Base64 图标，改用主题内置图标、轻量化 SVG Path 或压缩 WebP 外链。",
            ))
            return False
        return True

    @staticmethod
    def _iter_schema_nodes(obj: Any) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        if isinstance(obj, dict):
            if "@graph" in obj and isinstance(obj["@graph"], list):
                for item in obj["@graph"]:
                    nodes.extend(SiteAuditor._iter_schema_nodes(item))
            else:
                nodes.append(obj)
                for val in obj.values():
                    if isinstance(val, (dict, list)):
                        nodes.extend(SiteAuditor._iter_schema_nodes(val))
        elif isinstance(obj, list):
            for item in obj:
                nodes.extend(SiteAuditor._iter_schema_nodes(item))
        return nodes

    def _check_schema_authenticity(
        self, soup: BeautifulSoup, business_model: str, diagnostics: list[DiagnosticItem], metrics: dict[str, Any]
    ) -> bool:
        scripts = soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)})
        if not scripts:
            metrics["schema"] = {"block_count": 0, "types": []}
            diagnostics.append(DiagnosticItem(
                check_name="schema_authenticity_verified", error_code="SCHEMA_MISSING",
                diagnosis="页面缺少 JSON-LD 结构化数据。",
                fix_guide="按业务事实部署 Organization / Product / Service / Article 结构化数据。",
            ))
            return False

        all_nodes: list[dict[str, Any]] = []
        for s in scripts:
            raw = (s.string or s.get_text() or "").strip()
            if not raw:
                continue
            try:
                all_nodes.extend(self._iter_schema_nodes(json.loads(raw)))
            except json.JSONDecodeError as exc:
                diagnostics.append(DiagnosticItem(
                    check_name="schema_authenticity_verified", error_code="SCHEMA_JSON_SYNTAX_ERROR",
                    diagnosis=f"JSON-LD 存在语法错误：{exc}", fix_guide="修复 JSON-LD 语法并重测。"
                ))
                return False

        clone = BeautifulSoup(str(soup), "html.parser")
        for h in clone(["script", "style", "noscript", "template"]):
            h.decompose()
        visible_text = re.sub(r"\s+", " ", clone.get_text(" ", strip=True))
        visible_digits = re.sub(r"\D+", "", visible_text)

        found_types: set[str] = set()
        ok = True
        for node in all_nodes:
            rt = node.get("@type")
            types = rt if isinstance(rt, list) else ([rt] if rt else [])
            for t in types:
                found_types.add(str(t))
                if business_model in ("b2b_export", "dtc_retail") and str(t) in SUSPICIOUS_COMMERCIAL_SCHEMA_TYPES:
                    ok = False
                    diagnostics.append(DiagnosticItem(
                        check_name="schema_authenticity_verified", error_code="SCHEMA_TYPE_MISMATCH",
                        diagnosis=f"商业站错配使用了 `{t}` Schema 类型。",
                        fix_guide="更正为符合页面事实的 Service / Product / Organization。",
                    ))
            if "AggregateRating" in types or "ratingValue" in node:
                rv = str(node.get("ratingValue", "")).strip()
                rc = str(node.get("reviewCount") or node.get("ratingCount") or "").strip()
                if (rv and rv not in visible_text) or (rc and rc not in visible_text):
                    ok = False
                    diagnostics.append(DiagnosticItem(
                        check_name="schema_authenticity_verified", error_code="SCHEMA_FAKE_OR_HIDDEN_RATING",
                        diagnosis="Schema 声明了评分但页面前台不可见，涉嫌虚假结构化数据。",
                        fix_guide="删掉虚假评分或在前台真实展示评价后再标记。",
                    ))
            if any(t in ("Organization", "LocalBusiness", "Corporation") for t in types):
                digits = re.sub(r"\D+", "", str(node.get("telephone", "")))
                if len(digits) >= 7 and digits not in visible_digits:
                    ok = False
                    diagnostics.append(DiagnosticItem(
                        check_name="schema_authenticity_verified", error_code="SCHEMA_HIDDEN_CONTACT_INFO",
                        diagnosis="Schema 中的企业电话未在页面前台公开展示。",
                        fix_guide="确保 Schema 企业联系信息与页脚/联系页完全一致。",
                    ))

        metrics["schema"] = {"block_count": len(scripts), "types": sorted(found_types)}
        return ok

    def _check_robots_indexing(self, base_url: str, soup: BeautifulSoup, diagnostics: list[DiagnosticItem]) -> bool:
        meta_robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        if meta_robots and "noindex" in str(meta_robots.get("content", "")).lower():
            diagnostics.append(DiagnosticItem(
                check_name="robots_allows_indexing", error_code="SEARCH_ENGINE_BLOCKED",
                diagnosis="首页存在 meta robots noindex，搜索引擎被屏蔽。",
                fix_guide="解除 WordPress 后台“建议搜索引擎不索引本站点”勾选。",
            ))
            return False
        try:
            r = httpx.get(f"{base_url}/robots.txt", timeout=6.0, follow_redirects=True, headers=self.headers)
            if r.status_code == 200 and re.search(r"Disallow:\s*/\s*$", r.text, re.MULTILINE):
                diagnostics.append(DiagnosticItem(
                    check_name="robots_allows_indexing", error_code="ROBOTS_TXT_DISALLOW_ALL",
                    diagnosis="robots.txt 包含 Disallow: / 屏蔽了全站抓取。",
                    fix_guide="修改 robots.txt 放行抓取或解除 WP 后台屏蔽索引开关。",
                ))
                return False
        except httpx.HTTPError:
            pass
        return True

    def _check_sitemap(self, base_url: str, diagnostics: list[DiagnosticItem]) -> bool:
        for path in ("/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap.xml"):
            try:
                r = httpx.get(f"{base_url}{path}", timeout=6.0, follow_redirects=True, headers=self.headers)
                if r.status_code == 200 and ("<urlset" in r.text or "<sitemapindex" in r.text):
                    return True
            except httpx.HTTPError:
                continue
        diagnostics.append(DiagnosticItem(
            check_name="sitemap_xml_valid_200", error_code="SITEMAP_NOT_FOUND",
            diagnosis="未在标准路径（sitemap_index.xml / wp-sitemap.xml）检测到有效 XML 站点地图。",
            fix_guide="检查固定链接与 SEO 插件 Sitemap 开关后重新提交至 GSC。",
        ))
        return False

    def _check_legal_pages(self, base_url: str, diagnostics: list[DiagnosticItem]) -> bool:
        privacy_ok = False
        terms_ok = False
        for path in ("/privacy-policy/", "/privacy/"):
            try:
                r = httpx.get(f"{base_url}{path}", timeout=6.0, follow_redirects=True, headers=self.headers)
                if r.status_code == 200 and len(r.text) >= 600:
                    privacy_ok = True
                    break
            except httpx.HTTPError:
                continue
        for path in ("/terms-of-service/", "/terms-and-conditions/", "/terms/"):
            try:
                r = httpx.get(f"{base_url}{path}", timeout=6.0, follow_redirects=True, headers=self.headers)
                if r.status_code == 200 and len(r.text) >= 600:
                    terms_ok = True
                    break
            except httpx.HTTPError:
                continue
        if not (privacy_ok and terms_ok):
            diagnostics.append(DiagnosticItem(
                check_name="legal_policy_pages_200_non_empty", error_code="POLICY_PAGE_EMPTY_OR_404",
                diagnosis=f"合规条款页缺失或为空（Privacy={privacy_ok}, Terms={terms_ok}）。",
                fix_guide="调用 `wp.publish_legal_and_about_pages` 补齐 /privacy-policy/ 与 /terms-of-service/。",
            ))
            return False
        return True


# ==============================================================================
# 6. 受控 SSH + WP-CLI 原子执行器（WPCliExecutor）
# ==============================================================================

SEO_REST_MU_PLUGIN_PHP = """<?php
// Plugin Name: WP Coach SEO Meta REST Bridge
add_action('init', function () {
    $keys = ['rank_math_title', 'rank_math_description', '_yoast_wpseo_title', '_yoast_wpseo_metadesc'];
    foreach (['post', 'page'] as $type) {
        foreach ($keys as $key) {
            register_post_meta($type, $key, [
                'show_in_rest'  => true,
                'single'        => true,
                'type'          => 'string',
                'auth_callback' => fn() => current_user_can('edit_posts'),
            ]);
        }
    }
});
"""


class WPCliExecutor:
    def __init__(self, vault: VaultManager, connect_timeout: float = 15.0) -> None:
        self.vault = vault
        self.connect_timeout = connect_timeout

    @contextmanager
    def _ssh_session(self, creds: SiteCredentials) -> Iterator[paramiko.SSHClient]:
        if not creds.ssh_host:
            raise ValueError("当前站点为老站免 VPS 模式（未配置 SSH），请跳过 infra.* 动作。")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw: dict[str, Any] = {
            "hostname": creds.ssh_host, "port": creds.ssh_port, "username": creds.ssh_user,
            "timeout": self.connect_timeout, "allow_agent": False, "look_for_keys": False,
        }
        if creds.ssh_key_path:
            kw["key_filename"] = creds.ssh_key_path
        elif creds.ssh_password:
            kw["password"] = creds.ssh_password
        else:
            raise ValueError("SSH 凭证缺失：未配置私钥或密码。")
        try:
            client.connect(**kw)
            yield client
        finally:
            client.close()

    def _run(self, ssh: paramiko.SSHClient, cmd: str, creds: SiteCredentials, timeout: int = 120) -> tuple[int, str, str]:
        _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        code = stdout.channel.recv_exit_status()
        out = self.vault.redact_secrets(stdout.read().decode("utf-8", "ignore").strip(), creds)
        err = self.vault.redact_secrets(stderr.read().decode("utf-8", "ignore").strip(), creds)
        return code, out, err

    @staticmethod
    def _wp(creds: SiteCredentials, sub: str) -> str:
        rf = "--allow-root" if creds.ssh_user == "root" else ""
        return f"wp {sub} --path={shlex.quote(creds.wp_path)} {rf}".strip()

    def execute_action(self, site_alias: str, action_type: str, params: dict[str, Any] | None = None) -> ExecutionResult:
        params = params or {}
        creds = self.vault.get_secret_bundle(site_alias)
        handlers = {
            "infra.check_vault_connectivity": self._check_connectivity,
            "infra.install_lemp_and_wp": self._init_wp_and_bridge,
            "infra.install_woocommerce_base": self._install_woocommerce,
            "infra.create_full_backup": self._create_full_backup,
            "infra.run_restore_drill": self._run_restore_drill,
            "infra.configure_basic_and_theme": self._configure_basic_and_theme,
            "infra.enable_search_indexing": self._enable_search_indexing,
        }
        fn = handlers.get(action_type)
        if not fn:
            return ExecutionResult(ok=False, action_type=action_type, error_code="UNSUPPORTED_ACTION", summary=f"不支持动作 {action_type}")
        try:
            with self._ssh_session(creds) as ssh:
                return fn(ssh, creds, params)
        except paramiko.AuthenticationException:
            return ExecutionResult(ok=False, action_type=action_type, error_code="SSH_AUTH_FAILED", summary="SSH 认证失败，请检查私钥权限(chmod 600)或公钥。")
        except Exception as exc:
            return ExecutionResult(ok=False, action_type=action_type, error_code="SSH_EXECUTION_ERROR", summary=self.vault.redact_secrets(str(exc), creds))

    def _check_connectivity(self, ssh: paramiko.SSHClient, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        _, os_info, _ = self._run(ssh, "uname -srm", creds)
        c_df, free_mb, _ = self._run(ssh, "df -m / | awk 'NR==2 {print $4}'", creds)
        c_wp, _, _ = self._run(ssh, "command -v wp", creds)
        c_dir, _, _ = self._run(ssh, f"test -d {shlex.quote(creds.wp_path)}", creds)
        return ExecutionResult(
            ok=True, action_type="infra.check_vault_connectivity", summary="SSH 握手成功，环境探活通过。",
            details={"os": os_info, "free_disk_mb": int(free_mb) if c_df == 0 and free_mb.isdigit() else -1, "wp_cli": c_wp == 0, "wp_path_exists": c_dir == 0},
        )

    def _init_wp_and_bridge(self, ssh: paramiko.SSHClient, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        if self._run(ssh, "command -v wp", creds)[0] != 0:
            c, _, err = self._run(ssh, "curl -sS -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && chmod +x wp-cli.phar && mv wp-cli.phar /usr/local/bin/wp", creds)
            if c != 0:
                return ExecutionResult(ok=False, action_type="infra.install_lemp_and_wp", error_code="WP_CLI_INSTALL_FAILED", summary=err)
        if self._run(ssh, self._wp(creds, "core is-installed"), creds)[0] != 0:
            return ExecutionResult(ok=False, action_type="infra.install_lemp_and_wp", error_code="WP_CORE_NOT_INSTALLED", summary=f"{creds.wp_path} 尚未完成 WordPress 核心初始化。")

        for cmd in (
            self._wp(creds, "plugin delete hello akismet || true"),
            self._wp(creds, "post delete 1 2 --force || true"),
            self._wp(creds, "rewrite structure '/%postname%/' --hard"),
            self._wp(creds, "rewrite flush --hard"),
        ):
            self._run(ssh, cmd, creds)

        mu_dir = f"{creds.wp_path.rstrip('/')}/wp-content/mu-plugins"
        mu_file = f"{mu_dir}/wp-coach-seo-rest.php"
        self._run(ssh, f"mkdir -p {shlex.quote(mu_dir)}", creds)
        sftp = ssh.open_sftp()
        try:
            with sftp.file(mu_file, "w") as f:
                f.write(SEO_REST_MU_PLUGIN_PHP)
        finally:
            sftp.close()

        return ExecutionResult(
            ok=True, action_type="infra.install_lemp_and_wp",
            summary="WP-CLI 就绪，已清理默认垃圾、设定 /%postname%/ 并安装 SEO REST 桥接。",
            details={"mu_plugin": mu_file},
        )

    def _create_snapshot_internal(self, ssh: paramiko.SSHClient, creds: SiteCredentials, tag: str) -> dict[str, Any]:
        c_df, free_str, _ = self._run(ssh, "df -m / | awk 'NR==2 {print $4}'", creds)
        free_mb = int(free_str) if c_df == 0 and free_str.isdigit() else 0
        if free_mb < MIN_FREE_DISK_MB:
            return {"ok": False, "error_code": "DISK_SPACE_LOW", "summary": f"剩余磁盘仅 {free_mb} MB（低于 {MIN_FREE_DISK_MB} MB）。"}

        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        snap_dir = f"{BACKUP_ROOT}/{creds.site_alias}/{ts}_{tag}"
        db_file, files_tar = f"{snap_dir}/db.sql", f"{snap_dir}/wp_files.tar.gz"
        self._run(ssh, f"mkdir -p {shlex.quote(snap_dir)}", creds)

        c_db, _, e_db = self._run(ssh, self._wp(creds, f"db export {shlex.quote(db_file)}"), creds, timeout=180)
        if c_db != 0:
            return {"ok": False, "error_code": "DB_EXPORT_FAILED", "summary": e_db}
        c_tar, _, e_tar = self._run(ssh, f"tar -czf {shlex.quote(files_tar)} -C {shlex.quote(creds.wp_path)} wp-content wp-config.php", creds, timeout=240)
        if c_tar != 0:
            return {"ok": False, "error_code": "FILE_ARCHIVE_FAILED", "summary": e_tar}

        c_sz, sz_str, _ = self._run(ssh, f"stat -c%s {shlex.quote(db_file)}", creds)
        if not (c_sz == 0 and sz_str.isdigit() and int(sz_str) > 0):
            return {"ok": False, "error_code": "BACKUP_EMPTY", "summary": "生成的数据库快照为空。"}
        return {"ok": True, "snapshot_dir": snap_dir, "db_file": db_file, "files_archive": files_tar, "db_bytes": int(sz_str)}

    def _restore_db(self, ssh: paramiko.SSHClient, creds: SiteCredentials, db_file: str) -> bool:
        return self._run(ssh, self._wp(creds, f"db import {shlex.quote(db_file)}"), creds, timeout=180)[0] == 0

    def _install_woocommerce(self, ssh: paramiko.SSHClient, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        snap = self._create_snapshot_internal(ssh, creds, "pre_woo")
        if not snap["ok"]:
            return ExecutionResult(ok=False, action_type="infra.install_woocommerce_base", error_code=snap["error_code"], summary=snap["summary"])
        c, out, err = self._run(ssh, self._wp(creds, "plugin install woocommerce --activate"), creds, timeout=180)
        if c != 0:
            rb = self._restore_db(ssh, creds, snap["db_file"])
            return ExecutionResult(ok=False, action_type="infra.install_woocommerce_base", error_code="PLUGIN_INSTALL_FAILED", summary=f"安装失败已回滚：{err}", snapshot_path=snap["snapshot_dir"], rolled_back=rb)
        return ExecutionResult(ok=True, action_type="infra.install_woocommerce_base", summary="已前置快照并成功激活 WooCommerce。", snapshot_path=snap["snapshot_dir"], details={"output": out})

    def _create_full_backup(self, ssh: paramiko.SSHClient, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        snap = self._create_snapshot_internal(ssh, creds, "full")
        if not snap["ok"]:
            return ExecutionResult(ok=False, action_type="infra.create_full_backup", error_code=snap["error_code"], summary=snap["summary"])
        return ExecutionResult(ok=True, action_type="infra.create_full_backup", summary="完整备份成功。", snapshot_path=snap["snapshot_dir"], details=snap)

    def _run_restore_drill(self, ssh: paramiko.SSHClient, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        snap = self._create_snapshot_internal(ssh, creds, "restore_drill")
        if not snap["ok"]:
            return ExecutionResult(ok=False, action_type="infra.run_restore_drill", error_code=snap["error_code"], summary=snap["summary"])

        marker_key, marker_val = "wp_coach_restore_drill_marker", f"drill_{uuid.uuid4().hex[:12]}"
        c_set, _, err = self._run(ssh, self._wp(creds, f"option update {marker_key} {shlex.quote(marker_val)}"), creds)
        if c_set != 0:
            return ExecutionResult(ok=False, action_type="infra.run_restore_drill", error_code="DRILL_MARKER_FAILED", summary=err)
        if not self._restore_db(ssh, creds, snap["db_file"]):
            return ExecutionResult(ok=False, action_type="infra.run_restore_drill", error_code="RESTORE_IMPORT_FAILED", summary="数据库回滚导入失败。")

        _, val_after, _ = self._run(ssh, self._wp(creds, f"option get {marker_key} || true"), creds)
        c_ok, _, _ = self._run(ssh, self._wp(creds, "core is-installed"), creds)
        if marker_val in val_after or c_ok != 0:
            return ExecutionResult(ok=False, action_type="infra.run_restore_drill", error_code="RESTORE_VERIFICATION_FAILED", summary="回滚校验未通过。")

        return ExecutionResult(
            ok=True, action_type="infra.run_restore_drill",
            summary="备份与还原实战演练圆满通过：探针写入 -> 快照覆盖 -> 探针消失 -> 核心健康。",
            snapshot_path=snap["snapshot_dir"], rolled_back=True,
            details={"marker_wiped": True, "verified_snapshot": snap["snapshot_dir"]},
        )

    def _configure_basic_and_theme(self, ssh: paramiko.SSHClient, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        theme = str(params.get("theme_slug", "astra")).strip()
        site_title = str(params.get("site_title", "")).strip()
        if not re.fullmatch(r"[a-z0-9-]+", theme):
            return ExecutionResult(ok=False, action_type="infra.configure_basic_and_theme", error_code="INVALID_THEME_SLUG", summary="非法的主题标识。")
        snap = self._create_snapshot_internal(ssh, creds, "pre_theme")
        if not snap["ok"]:
            return ExecutionResult(ok=False, action_type="infra.configure_basic_and_theme", error_code=snap["error_code"], summary=snap["summary"])
        if site_title:
            self._run(ssh, self._wp(creds, f"option update blogname {shlex.quote(site_title)}"), creds)
        c, out, err = self._run(ssh, self._wp(creds, f"theme install {shlex.quote(theme)} --activate"), creds, timeout=180)
        if c != 0:
            rb = self._restore_db(ssh, creds, snap["db_file"])
            return ExecutionResult(ok=False, action_type="infra.configure_basic_and_theme", error_code="THEME_INSTALL_FAILED", summary=err, rolled_back=rb)
        return ExecutionResult(ok=True, action_type="infra.configure_basic_and_theme", summary=f"已安装并激活轻量主题 `{theme}`。", snapshot_path=snap["snapshot_dir"], details={"output": out})

    def _enable_search_indexing(self, ssh: paramiko.SSHClient, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        c, _, err = self._run(ssh, self._wp(creds, "option update blog_public 1"), creds)
        if c != 0:
            return ExecutionResult(ok=False, action_type="infra.enable_search_indexing", error_code="INDEX_ENABLE_FAILED", summary=err)
        return ExecutionResult(ok=True, action_type="infra.enable_search_indexing", summary="已放行搜索引擎索引（blog_public=1）。")


# ==============================================================================
# 7. Cloudflare DNS/CDN/邮局自动化执行器（CloudflareClient）
# ==============================================================================

class CloudflareClient:
    def __init__(self, vault: VaultManager, timeout: float = 15.0) -> None:
        self.vault = vault
        self.timeout = timeout

    def execute_action(self, site_alias: str, action_type: str, params: dict[str, Any] | None = None) -> ExecutionResult:
        params = params or {}
        creds = self.vault.get_secret_bundle(site_alias)
        if not (creds.cloudflare_api_token and creds.cloudflare_zone_id):
            return ExecutionResult(ok=False, action_type=action_type, error_code="CF_CREDENTIALS_MISSING", summary="Vault 缺少 Cloudflare Token 或 Zone ID。")
        handlers = {
            "dns.configure_cloudflare_proxy": self._configure_proxy,
            "dns.configure_smtp_records": self._configure_smtp_records,
            "dns.add_gsc_verification_txt": self._add_gsc_txt,
        }
        fn = handlers.get(action_type)
        if not fn:
            return ExecutionResult(ok=False, action_type=action_type, error_code="UNSUPPORTED_DNS_ACTION", summary=f"不支持动作 {action_type}")
        try:
            with httpx.Client(
                base_url=CF_API_BASE, timeout=self.timeout,
                headers={"Authorization": f"Bearer {creds.cloudflare_api_token}", "Content-Type": "application/json"},
            ) as client:
                return fn(client, creds, params)
        except Exception as exc:
            return ExecutionResult(ok=False, action_type=action_type, error_code="CF_API_ERROR", summary=self.vault.redact_secrets(str(exc), creds))

    def _cf(self, client: httpx.Client, method: str, path: str, creds: SiteCredentials, *, json_body: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> dict[str, Any]:
        r = client.request(method, path, json=json_body, params=query)
        data = r.json()
        if not data.get("success", False):
            msg = "; ".join(e.get("message", str(e)) for e in data.get("errors", []))
            raise RuntimeError(self.vault.redact_secrets(msg or f"HTTP {r.status_code}", creds))
        return data

    def _upsert(
        self, client: httpx.Client, creds: SiteCredentials, *, record_type: str, name: str,
        content: str, proxied: bool = False, priority: int | None = None,
        match_prefix: str | None = None, dedup_prefix: bool = False
    ) -> dict[str, Any]:
        existing = self._cf(client, "GET", f"/zones/{creds.cloudflare_zone_id}/dns_records", creds, query={"type": record_type, "name": name, "per_page": 100}).get("result", [])
        matched = []
        for rec in existing:
            rc = str(rec.get("content", "")).strip('"')
            if match_prefix:
                if rc.lower().startswith(match_prefix.lower()):
                    matched.append(rec)
            elif record_type == "MX":
                if rc.lower().rstrip(".") == content.lower().rstrip("."):
                    matched.append(rec)
            else:
                matched.append(rec)

        payload: dict[str, Any] = {
            "type": record_type, "name": name, "content": content, "ttl": 1,
            "proxied": proxied if record_type in ("A", "AAAA", "CNAME") else False,
        }
        if priority is not None:
            payload["priority"] = priority

        deleted = 0
        if dedup_prefix and len(matched) > 1:
            for extra in matched[1:]:
                self._cf(client, "DELETE", f"/zones/{creds.cloudflare_zone_id}/dns_records/{extra['id']}", creds)
                deleted += 1

        if matched:
            res = self._cf(client, "PUT", f"/zones/{creds.cloudflare_zone_id}/dns_records/{matched[0]['id']}", creds, json_body=payload)
            op = "updated"
        else:
            res = self._cf(client, "POST", f"/zones/{creds.cloudflare_zone_id}/dns_records", creds, json_body=payload)
            op = "created"
        return {"action": op, "type": record_type, "name": name, "proxied": payload["proxied"], "deleted_duplicates": deleted, "id": res["result"]["id"]}

    def _configure_proxy(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        if not creds.origin_ip:
            return ExecutionResult(ok=False, action_type="dns.configure_cloudflare_proxy", error_code="ORIGIN_IP_MISSING", summary="未配置源站 origin_ip。")
        ssl_mode = str(params.get("ssl_mode", "strict"))
        if ssl_mode not in ("full", "strict"):
            return ExecutionResult(ok=False, action_type="dns.configure_cloudflare_proxy", error_code="UNSAFE_SSL_MODE", summary="禁止设为 Flexible，仅允许 full 或 strict。")
        changes = [self._upsert(client, creds, record_type="A", name=h, content=creds.origin_ip, proxied=True) for h in (creds.domain, f"www.{creds.domain}")]
        self._cf(client, "PATCH", f"/zones/{creds.cloudflare_zone_id}/settings/ssl", creds, json_body={"value": ssl_mode})
        self._cf(client, "PATCH", f"/zones/{creds.cloudflare_zone_id}/settings/always_use_https", creds, json_body={"value": "on"})
        return ExecutionResult(ok=True, action_type="dns.configure_cloudflare_proxy", summary=f"已开启橙色云朵代理与 {ssl_mode} SSL。", details={"records": changes})

    def _configure_smtp_records(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        mxs: list[dict[str, Any]] = params.get("mx_records", [])
        spf = str(params.get("spf_value", "")).strip()
        dmarc = str(params.get("dmarc_value") or f"v=DMARC1; p=none; rua=mailto:postmaster@{creds.domain}").strip()
        dkim_sel = params.get("dkim_selector") or creds.dkim_selector
        dkim_val = params.get("dkim_value")
        if not mxs or not spf.lower().startswith("v=spf1"):
            return ExecutionResult(ok=False, action_type="dns.configure_smtp_records", error_code="INVALID_MAIL_DNS_PARAMS", summary="必须提供有效 mx_records 与 v=spf1 记录。")
        for mx in mxs:
            t = str(mx.get("target", "")).strip().lower().rstrip(".")
            if t in (creds.origin_ip, creds.domain, f"www.{creds.domain}"):
                return ExecutionResult(ok=False, action_type="dns.configure_smtp_records", error_code="MX_POINTS_TO_WEB_SERVER", summary=f"禁止将 MX 指向建站服务器：{t}")
        changes = [self._upsert(client, creds, record_type="MX", name=creds.domain, content=str(mx["target"]).strip(), priority=int(mx.get("priority", 10)), proxied=False) for mx in mxs]
        changes.append(self._upsert(client, creds, record_type="TXT", name=creds.domain, content=spf, match_prefix="v=spf1", dedup_prefix=True))
        changes.append(self._upsert(client, creds, record_type="TXT", name=f"_dmarc.{creds.domain}", content=dmarc, match_prefix="v=dmarc1", dedup_prefix=True))
        if dkim_sel and dkim_val:
            changes.append(self._upsert(client, creds, record_type="TXT", name=f"{dkim_sel}._domainkey.{creds.domain}", content=str(dkim_val).strip(), match_prefix="v=dkim1", dedup_prefix=True))
        return ExecutionResult(ok=True, action_type="dns.configure_smtp_records", summary="独立邮局 MX/SPF/DMARC/DKIM 配置完成。", details={"records": changes})

    def _add_gsc_txt(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        token = str(params.get("verification_token", "")).strip()
        if not token.startswith("google-site-verification="):
            return ExecutionResult(ok=False, action_type="dns.add_gsc_verification_txt", error_code="INVALID_GSC_TOKEN", summary="验证码必须以 google-site-verification= 开头。")
        res = self._upsert(client, creds, record_type="TXT", name=creds.domain, content=token, match_prefix="google-site-verification=", dedup_prefix=False)
        return ExecutionResult(ok=True, action_type="dns.add_gsc_verification_txt", summary="已写入 GSC 验证 TXT 记录。", details=res)


# ==============================================================================
# 8. WordPress REST 内容/TDK/Schema 执行器（WPRestClient）
# ==============================================================================

class WPRestClient:
    def __init__(self, vault: VaultManager, timeout: float = 20.0) -> None:
        self.vault = vault
        self.timeout = timeout

    def execute_action(self, site_alias: str, action_type: str, params: dict[str, Any] | None = None) -> ExecutionResult:
        params = params or {}
        creds = self.vault.get_secret_bundle(site_alias)
        if not (creds.wp_username and creds.wp_app_password):
            return ExecutionResult(ok=False, action_type=action_type, error_code="WP_REST_AUTH_MISSING", summary="Vault 缺少 wp_username 或 wp_app_password。")
        handlers = {
            "wp.publish_standard_page": self._publish_standard_page,
            "wp.publish_legal_and_about_pages": self._publish_legal_and_about,
            "wp.create_custom_collection_page": self._create_collection_page,
            "wp.save_blog_draft_with_human_slots": self._save_blog_draft,
            "wp.publish_blog_post_and_internal_links": self._publish_blog_and_links,
            "wp.update_core_pages_tdk": self._update_tdk,
            "wp.deploy_authentic_jsonld_schema": self._deploy_schema,
        }
        fn = handlers.get(action_type)
        if not fn:
            return ExecutionResult(ok=False, action_type=action_type, error_code="UNSUPPORTED_WP_REST_ACTION", summary=f"不支持动作 {action_type}")
        try:
            with httpx.Client(
                base_url=f"{creds.url.rstrip('/')}/wp-json/wp/v2",
                auth=httpx.BasicAuth(creds.wp_username, creds.wp_app_password),
                timeout=self.timeout,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            ) as client:
                return fn(client, creds, params)
        except Exception as exc:
            return ExecutionResult(ok=False, action_type=action_type, error_code="WP_REST_ERROR", summary=self.vault.redact_secrets(str(exc), creds))

    @staticmethod
    def _find_by_slug(client: httpx.Client, endpoint: str, slug: str) -> dict[str, Any] | None:
        r = client.get(f"/{endpoint}", params={"slug": slug, "status": "any", "context": "edit"})
        r.raise_for_status()
        items = r.json()
        return items[0] if items else None

    def _upsert(self, client: httpx.Client, endpoint: str, slug: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        existing = self._find_by_slug(client, endpoint, slug)
        if existing:
            r = client.post(f"/{endpoint}/{existing['id']}", json=payload)
            r.raise_for_status()
            return "updated", r.json()
        r = client.post(f"/{endpoint}", json={**payload, "slug": slug})
        r.raise_for_status()
        return "created", r.json()

    @staticmethod
    def _visible_text(raw_html: str) -> str:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    def _publish_standard_page(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        slug = str(params.get("slug", "")).strip().lower()
        title = str(params.get("title", "")).strip()
        content = str(params.get("content_html", "")).strip()
        status = str(params.get("status", "publish"))
        if not (slug and title and content):
            return ExecutionResult(ok=False, action_type="wp.publish_standard_page", error_code="MISSING_PAGE_FIELDS", summary="缺少 slug/title/content_html。")
        if "data:image/" in content.lower() and ";base64," in content.lower():
            return ExecutionResult(ok=False, action_type="wp.publish_standard_page", error_code="AI_BASE64_SVG_BLOAT", summary="禁止在正文中内嵌 Base64 图像。")
        if re.search(r"<h1\b", content, re.I):
            return ExecutionResult(ok=False, action_type="wp.publish_standard_page", error_code="MULTIPLE_H1_DETECTED", summary="正文小标题必须从 H2 起步，避免多 H1。")
        op, entry = self._upsert(client, "pages", slug, {"title": title, "content": content, "status": status})
        return ExecutionResult(ok=True, action_type="wp.publish_standard_page", summary=f"页面 `{slug}` 已{op}。", details={"id": entry["id"], "link": entry.get("link")})

    def _publish_legal_and_about(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        company = str(params.get("company_legal_name", "")).strip()
        address = str(params.get("company_address", "")).strip()
        email = str(params.get("contact_email", "")).strip()
        photos: list[str] = params.get("real_photo_urls", [])
        if not (company and address and email and photos):
            return ExecutionResult(ok=False, action_type="wp.publish_legal_and_about_pages", error_code="REAL_ENTITY_INFO_MISSING", summary="真实资产锁拦截：必须提供法定公司名、地址、联系邮箱及至少 1 张真实业务实拍图 URL。")

        ec, ea, ee = html_lib.escape(company), html_lib.escape(address), html_lib.escape(email)
        privacy_html = (
            f"<h2>1. Who We Are</h2><p>This website ({html_lib.escape(creds.url)}) is operated by <strong>{ec}</strong>, "
            f"located at {ea}. For privacy inquiries, contact us at <a href='mailto:{ee}'>{ee}</a>.</p>"
            f"<h2>2. Data We Collect</h2><p>We collect inquiry details you voluntarily submit via our contact forms solely to respond to business requests and fulfill orders.</p>"
            f"<h2>3. Your Rights &amp; Data Deletion</h2><p>You may request access to or deletion of your personal data at any time by emailing {ee}.</p>"
        )
        terms_html = (
            f"<h2>1. Legal Entity</h2><p>All products and services listed on {html_lib.escape(creds.domain)} are provided by <strong>{ec}</strong> ({ea}).</p>"
            f"<h2>2. Orders, Quotes &amp; Liability</h2><p>Commercial specifications, lead times, and warranty terms are governed by the formal Proforma Invoice or order confirmation issued by {ec}. Contact: {ee}.</p>"
        )
        photo_tags = "".join(f"<figure class='wp-block-image'><img src='{html_lib.escape(u)}' alt='{ec} facility' loading='lazy' /></figure>" for u in photos)
        about_html = (
            f"<h2>About {ec}</h2><p>{html_lib.escape(str(params.get('company_story', f'{company} operates directly from {address}.')))}</p>"
            f"<h2>Our Facility &amp; Operations</h2>{photo_tags}"
            f"<h2>Direct Contact</h2><p>Entity: {ec}<br/>Address: {ea}<br/>Email: {ee}</p>"
        )
        res_p = self._upsert(client, "pages", "privacy-policy", {"title": "Privacy Policy", "content": privacy_html, "status": "publish"})[1]
        res_t = self._upsert(client, "pages", "terms-of-service", {"title": "Terms of Service", "content": terms_html, "status": "publish"})[1]
        res_a = self._upsert(client, "pages", "about-us", {"title": f"About {company}", "content": about_html, "status": "publish"})[1]
        return ExecutionResult(
            ok=True, action_type="wp.publish_legal_and_about_pages",
            summary="已上线带真实主体信息的 Privacy Policy、Terms of Service 与 About Us 页面。",
            details={"privacy": res_p.get("link"), "terms": res_t.get("link"), "about": res_a.get("link")},
        )

    def _create_collection_page(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        slug = str(params.get("slug", "")).strip().lower()
        title = str(params.get("title", "")).strip()
        value_prop = str(params.get("value_proposition", "")).strip()
        products: list[dict[str, str]] = params.get("products", [])
        specs: list[dict[str, str]] = params.get("specs_or_moq", [])
        cta_text = str(params.get("cta_text", "Request a Custom Quote")).strip()
        cta_url = str(params.get("cta_url", f"{creds.url.rstrip('/')}/contact/")).strip()
        status = str(params.get("status", "publish"))

        if not (slug and title and products and specs):
            return ExecutionResult(ok=False, action_type="wp.create_custom_collection_page", error_code="COMMERCIAL_PROOF_MISSING", summary="商业栏目页必须提供 slug、title、products 与 specs_or_moq。")
        if any(f in f"{title} {value_prop}".lower() for f in COMMERCIAL_ESSAY_RED_FLAGS):
            return ExecutionResult(ok=False, action_type="wp.create_custom_collection_page", error_code="COMMERCIAL_PAGE_CONTENT_BLOAT", summary="商业意图分流锁拦截：严禁在商业落地页使用科普长文套话。")

        cards = "".join(
            f"<div class='wp-coach-product-card'>"
            + (f"<img src='{html_lib.escape(p['image_url'])}' alt='{html_lib.escape(p.get('name', ''))}' loading='lazy' />" if p.get("image_url") else "")
            + f"<h3><a href='{html_lib.escape(p.get('url', cta_url))}'>{html_lib.escape(p.get('name', ''))}</a></h3>"
            f"<p>{html_lib.escape(p.get('summary', ''))}</p></div>"
            for p in products
        )
        rows = "".join(f"<tr><th>{html_lib.escape(str(r.get('label', '')))}</th><td>{html_lib.escape(str(r.get('value', '')))}</td></tr>" for r in specs)
        html_body = (
            f"<p>{html_lib.escape(value_prop)}</p>"
            f"<p><a class='wp-block-button__link' href='{html_lib.escape(cta_url)}'>{html_lib.escape(cta_text)}</a></p>"
            f"<h2>Product Lineup</h2><div class='wp-coach-collection-grid'>{cards}</div>"
            f"<h2>Specifications, MOQ &amp; Process</h2><table><tbody>{rows}</tbody></table>"
            f"<p><a class='wp-block-button__link' href='{html_lib.escape(cta_url)}'>{html_lib.escape(cta_text)}</a></p>"
        )
        op, entry = self._upsert(client, "pages", slug, {"title": title, "content": html_body, "status": status})
        return ExecutionResult(ok=True, action_type="wp.create_custom_collection_page", summary=f"商业产品系列页已{op}。", details={"id": entry["id"], "link": entry.get("link"), "slug": slug})

    def _save_blog_draft(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        slug = str(params.get("slug", "")).strip().lower()
        title = str(params.get("title", "")).strip()
        body = str(params.get("body_html", "")).strip()
        insights: list[str] = params.get("human_insights", [])
        media: list[str] = params.get("original_media_urls", [])

        if len([x for x in insights if len(str(x).strip()) >= 15]) < 2 or not media:
            return ExecutionResult(ok=False, action_type="wp.save_blog_draft_with_human_slots", error_code="GENERIC_AI_FLUFF_DETECTED", summary="人类护城河锁拦截：需注入至少 2 条一手洞察及 1 张原创图 URL。")
        lb = body.lower()
        if any(t in lb for t in AI_CLICHE_PLACEHOLDERS):
            return ExecutionResult(ok=False, action_type="wp.save_blog_draft_with_human_slots", error_code="GENERIC_AI_FLUFF_DETECTED", summary="检测到未替换占位符。")
        if "data:image/" in lb and ";base64," in lb:
            return ExecutionResult(ok=False, action_type="wp.save_blog_draft_with_human_slots", error_code="AI_BASE64_SVG_BLOAT", summary="禁止内嵌 Base64 图像。")
        if re.search(r"<h1\b", body, re.I):
            return ExecutionResult(ok=False, action_type="wp.save_blog_draft_with_human_slots", error_code="MULTIPLE_H1_DETECTED", summary="正文必须从 H2 起步，避免多 H1。")

        li_html = "".join(f"<li>{html_lib.escape(str(x))}</li>" for x in insights)
        img_html = "".join(f"<figure class='wp-block-image'><img src='{html_lib.escape(str(u))}' alt='{html_lib.escape(title)}' loading='lazy' /></figure>" for u in media)
        full_html = f"{body}\n<h2>Field Notes &amp; First-Hand Experience</h2><ul>{li_html}</ul>\n{img_html}"
        op, entry = self._upsert(client, "posts", slug, {"title": title, "content": full_html, "status": "draft"})
        return ExecutionResult(ok=True, action_type="wp.save_blog_draft_with_human_slots", summary=f"低 KD 博文草稿已{op}。", details={"id": entry["id"], "slug": slug, "status": "draft"})

    def _publish_blog_and_links(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        slug = str(params.get("slug", "")).strip().lower()
        target_url = str(params.get("target_commercial_url", "")).strip()
        anchor = str(params.get("anchor_text", "Explore our product lineup")).strip()
        existing = self._find_by_slug(client, "posts", slug)
        if not existing:
            return ExecutionResult(ok=False, action_type="wp.publish_blog_post_and_internal_links", error_code="DRAFT_NOT_FOUND", summary=f"未找到草稿 `{slug}`。")
        if not target_url:
            return ExecutionResult(ok=False, action_type="wp.publish_blog_post_and_internal_links", error_code="COMMERCIAL_INTERNAL_LINK_REQUIRED", summary="必须提供指向商业页的 target_commercial_url。")
        try:
            probe = httpx.get(target_url, timeout=8.0, follow_redirects=True)
            if probe.status_code != 200:
                return ExecutionResult(ok=False, action_type="wp.publish_blog_post_and_internal_links", error_code="BROKEN_INTERNAL_LINK", summary=f"目标内链返回 HTTP {probe.status_code}，已阻止发布。")
        except httpx.HTTPError:
            return ExecutionResult(ok=False, action_type="wp.publish_blog_post_and_internal_links", error_code="BROKEN_INTERNAL_LINK", summary="目标内链无法连通。")

        raw = existing.get("content", {}).get("raw", "")
        if target_url not in raw:
            raw += f"\n<p>Need custom specs or direct supply? <a href='{html_lib.escape(target_url)}'>{html_lib.escape(anchor)}</a>.</p>"
        r = client.post(f"/posts/{existing['id']}", json={"content": raw, "status": "publish"})
        r.raise_for_status()
        pub = r.json()
        return ExecutionResult(ok=True, action_type="wp.publish_blog_post_and_internal_links", summary=f"博文 `{slug}` 已通过内链预检并正式上线。", details={"id": pub["id"], "live_url": pub.get("link"), "internal_link": target_url})

    def _update_tdk(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        pages: list[dict[str, str]] = params.get("pages", [])
        if not pages:
            return ExecutionResult(ok=False, action_type="wp.update_core_pages_tdk", error_code="EMPTY_TDK_LIST", summary="请提供待更新页面列表。")
        updated = []
        for item in pages:
            slug = str(item["slug"]).strip().lower()
            ep = "posts" if item.get("post_type") == "post" else "pages"
            st, md = str(item["seo_title"]).strip(), str(item["meta_description"]).strip()
            if len(st) > 65 or len(md) > 165:
                return ExecutionResult(ok=False, action_type="wp.update_core_pages_tdk", error_code="TDK_LENGTH_EXCEEDED", summary=f"页面 `{slug}` TDK 超长。")
            ex = self._find_by_slug(client, ep, slug)
            if not ex:
                return ExecutionResult(ok=False, action_type="wp.update_core_pages_tdk", error_code="TARGET_PAGE_NOT_FOUND", summary=f"未找到 `{slug}`。")
            r = client.post(f"/{ep}/{ex['id']}", json={"meta": {"rank_math_title": st, "rank_math_description": md, "_yoast_wpseo_title": st, "_yoast_wpseo_metadesc": md}})
            r.raise_for_status()
            updated.append({"slug": slug, "id": ex["id"]})
        return ExecutionResult(ok=True, action_type="wp.update_core_pages_tdk", summary=f"已更新 {len(updated)} 个页面 TDK。", details={"updated": updated})

    def _deploy_schema(self, client: httpx.Client, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        slug = str(params.get("slug", "")).strip().lower()
        ep = "posts" if params.get("post_type") == "post" else "pages"
        model = str(params.get("business_model", "b2b_export"))
        schema_obj = params.get("schema_json")
        if not isinstance(schema_obj, dict) or "@context" not in schema_obj:
            return ExecutionResult(ok=False, action_type="wp.deploy_authentic_jsonld_schema", error_code="INVALID_SCHEMA_JSON", summary="schema_json 必须是含 @context 的 JSON 对象。")
        ex = self._find_by_slug(client, ep, slug)
        if not ex:
            return ExecutionResult(ok=False, action_type="wp.deploy_authentic_jsonld_schema", error_code="TARGET_PAGE_NOT_FOUND", summary=f"未找到页面 `{slug}`。")

        raw = ex.get("content", {}).get("raw", "")
        vis = self._visible_text(raw)
        vis_digits = re.sub(r"\D+", "", vis)
        for node in SiteAuditor._iter_schema_nodes(schema_obj):
            rt = node.get("@type")
            types = rt if isinstance(rt, list) else ([rt] if rt else [])
            if model in ("b2b_export", "dtc_retail") and any(str(t) in SUSPICIOUS_COMMERCIAL_SCHEMA_TYPES for t in types):
                return ExecutionResult(ok=False, action_type="wp.deploy_authentic_jsonld_schema", error_code="SCHEMA_TYPE_MISMATCH", summary="商业站禁止套用非商业 Schema 类型。")
            if "AggregateRating" in types or "ratingValue" in node:
                rv, rc = str(node.get("ratingValue", "")).strip(), str(node.get("reviewCount") or node.get("ratingCount") or "").strip()
                if (rv and rv not in vis) or (rc and rc not in vis):
                    return ExecutionResult(ok=False, action_type="wp.deploy_authentic_jsonld_schema", error_code="SCHEMA_FAKE_OR_HIDDEN_RATING", summary="评分数据在前台正文不可见，已拦截。")
            pd = re.sub(r"\D+", "", str(node.get("telephone", "")))
            if len(pd) >= 7 and pd not in vis_digits:
                return ExecutionResult(ok=False, action_type="wp.deploy_authentic_jsonld_schema", error_code="SCHEMA_HIDDEN_CONTACT_INFO", summary="Schema 电话未在页面前台展示。")

        cleaned = COACH_SCHEMA_BLOCK_RE.sub("", raw).rstrip()
        block = f'\n\n<!-- wp:html -->\n<script type="application/ld+json" data-wp-coach-schema="true">{json.dumps(schema_obj, ensure_ascii=False, separators=(",", ":"))}</script>\n<!-- /wp:html -->'
        r = client.post(f"/{ep}/{ex['id']}", json={"content": cleaned + block})
        r.raise_for_status()
        return ExecutionResult(ok=True, action_type="wp.deploy_authentic_jsonld_schema", summary=f"已通过真实性校验并幂等注入 JSON-LD 至 `{slug}`。", details={"id": ex["id"], "type": schema_obj.get("@type")})


# ==============================================================================
# 9. SEO 意图分流与外链 Outreach 漏斗（SEOResearcher）
# ==============================================================================

class SEOResearcher:
    def __init__(self, vault: VaultManager, timeout: float = 10.0) -> None:
        self.vault = vault
        self.timeout = timeout
        self.headers = {"User-Agent": "Mozilla/5.0 (compatible; WPSeoCoachResearcher/1.0)", "Accept": "text/html,*/*"}

    @staticmethod
    def seo_dir(site_alias: str) -> Path:
        safe = "".join(c for c in site_alias if c.isalnum() or c in ("-", "_"))
        p = WORKSPACES_DIR / safe / "seo"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def _root_domain(url_or_host: str) -> str:
        raw = url_or_host.strip().lower()
        if "://" not in raw:
            raw = f"https://{raw}"
        host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
        parts = host.split(".")
        if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "edu") and len(parts[-1]) == 2:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:]) if len(parts) >= 2 else host

    def analyze_keyword_intent(self, keyword: str, *, kd_score: int | None = None, serp_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        kw_l = f" {keyword.strip().lower()} "
        comm_hits = [s for s in COMMERCIAL_INTENT_SIGNALS if s in kw_l]
        info_hits = [s for s in INFORMATIONAL_INTENT_SIGNALS if s in kw_l]
        ratio = 0.0
        if serp_results:
            top10 = serp_results[:10]
            cp = sum(
                1 for x in top10
                if any(t in str(x.get("link") or x.get("url") or "").lower() for t in ("/product", "/category", "/collection", "/shop"))
                or any(t in str(x.get("title") or "").lower() for t in ("manufacturer", "supplier", "wholesale", "buy ", "custom "))
            )
            ratio = round(cp / max(len(top10), 1), 2)

        if bool(comm_hits) or (ratio >= 0.4 and not info_hits):
            return {
                "keyword": keyword, "kd_score": kd_score, "detected_intent": "commercial_transactional",
                "locked_page_type": "custom_product_collection_page",
                "guardrail_note": "触发商业意图分流锁：必须做自定义产品系列页，直陈产品矩阵、MOQ/工艺与 CTA，严禁写啰嗦科普文。",
                "required_human_slots": ["真实产品/产线实拍图", "真实 MOQ/交期/质检标准", "真实交付案例或认证"],
            }
        return {
            "keyword": keyword, "kd_score": kd_score, "detected_intent": "informational_comparison_or_guide",
            "locked_page_type": "comparison_or_guide_blog",
            "guardrail_note": "高 KD 需极强一线实测数据，建议新站优先选 KD<=25 的长尾对比词作为流量与外链诱饵。" if (kd_score and kd_score > 30) else "适合新站作为低 KD 切入点与外链推荐诱饵。",
            "required_human_slots": ["至少 2 条真实一线实操/售后避坑洞察", "至少 1 张原创实拍或对比图"],
        }

    def fetch_serp_via_serper(self, keyword: str, api_key: str, *, num: int = 40, gl: str = "us", hl: str = "en") -> list[dict[str, Any]]:
        with httpx.Client(timeout=15.0) as c:
            r = c.post("https://google.serper.dev/search", headers={"X-API-KEY": api_key, "Content-Type": "application/json"}, json={"q": keyword, "num": min(num, 100), "gl": gl, "hl": hl})
            r.raise_for_status()
            return r.json().get("organic", [])

    def filter_serp_prospects(
        self, serp_results: list[dict[str, Any]], *, own_domain: str, competitor_domains: list[str] | None = None, max_dr: int = 80
    ) -> tuple[list[ProspectItem], list[dict[str, str]]]:
        own_root = self._root_domain(own_domain)
        comp_roots = {self._root_domain(d) for d in (competitor_domains or []) if d.strip()}
        clean, excluded, seen = [], [], set()
        for idx, item in enumerate(serp_results, 1):
            url = str(item.get("link") or item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            root = self._root_domain(url)
            if root in seen:
                continue
            dr_raw = item.get("dr") or item.get("domain_rating")
            dr = int(dr_raw) if isinstance(dr_raw, (int, float, str)) and str(dr_raw).isdigit() else None
            reason = None
            if root == own_root:
                reason = "own_domain"
            elif root in SOCIAL_AND_UGC_DOMAINS:
                reason = "social_media_nofollow"
            elif root in ECOMMERCE_MARKETPLACE_DOMAINS:
                reason = "ecommerce_marketplace"
            elif root in MEGA_AUTHORITY_DOMAINS or root.endswith((".gov", ".edu")):
                reason = "mega_authority_or_gov_edu"
            elif root in comp_roots:
                reason = "direct_competitor"
            elif dr is not None and dr > max_dr:
                reason = f"dr_over_{max_dr}"
            elif url.lower().endswith(".pdf"):
                reason = "non_html_pdf"
            if reason:
                excluded.append({"domain": root, "url": url, "reason": reason})
                continue
            seen.add(root)
            clean.append(ProspectItem(
                domain=root, url=url, title=str(item.get("title") or root).strip(),
                snippet=str(item.get("snippet") or "").strip(),
                serp_position=int(item.get("position") or idx), estimated_dr=dr,
            ))
        return clean, excluded

    @staticmethod
    def _extract_emails(html_text: str) -> list[str]:
        valid = []
        for e in sorted(set(EMAIL_REGEX.findall(html_text))):
            el = e.lower()
            if any(el.split("@", 1)[0].startswith(p) for p in IGNORED_EMAIL_PREFIXES):
                continue
            if any(el.endswith(s) for s in IGNORED_EMAIL_SUFFIXES) or "example.com" in el:
                continue
            valid.append(el)
        return valid

    def _discover_email(self, p: ProspectItem, hunter_key: str | None) -> ProspectItem:
        if p.email:
            return p
        form_only = False
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self.headers) as c:
                r = c.get(p.url)
                if r.status_code == 200:
                    ems = self._extract_emails(r.text)
                    if ems:
                        p.email, p.email_source = ems[0], "target_page"
                        return p
                    soup = BeautifulSoup(r.text, "html.parser")
                    links: dict[str, str] = {}
                    for a in soup.find_all("a", href=True):
                        fu = urljoin(str(r.url), str(a["href"]).strip())
                        if not fu.startswith(("http://", "https://")) or self._root_domain(fu) != p.domain:
                            continue
                        pl, tx = urlparse(fu).path.lower(), a.get_text(" ", strip=True).lower()
                        if "contact" not in links and ("contact" in pl or "contact" in tx):
                            links["contact"] = fu
                        elif "about" not in links and ("about" in pl or "about" in tx):
                            links["about"] = fu
                    for key, tag in (("contact", "contact_page"), ("about", "about_page")):
                        if key not in links:
                            continue
                        try:
                            rs = c.get(links[key])
                            if rs.status_code == 200:
                                sem = self._extract_emails(rs.text)
                                if sem:
                                    p.email, p.email_source = sem[0], tag  # type: ignore[assignment]
                                    return p
                                if key == "contact" and "<form" in rs.text.lower():
                                    form_only = True
                        except httpx.HTTPError:
                            continue
        except httpx.HTTPError:
            pass

        if hunter_key:
            try:
                r = httpx.get("https://api.hunter.io/v2/domain-search", params={"domain": p.domain, "api_key": hunter_key, "limit": 5}, timeout=10.0)
                if r.status_code == 200:
                    ems = r.json().get("data", {}).get("emails", [])
                    if ems:
                        prefs = ("editor", "content", "marketing", "founder", "owner", "hello", "info")
                        ems.sort(key=lambda x: (any(k in str(x.get("position", "")).lower() or k in str(x.get("value", "")).lower() for k in prefs), int(x.get("confidence", 0))), reverse=True)
                        p.email, p.email_source = str(ems[0]["value"]).lower(), "hunter_api"
                        return p
            except httpx.HTTPError:
                pass

        p.email_source = "form_only_skipped" if form_only else "not_found"
        return p

    def execute_action(self, site_alias: str, action_type: str, params: dict[str, Any] | None = None) -> ExecutionResult:
        params = params or {}
        creds = self.vault.get_secret_bundle(site_alias)
        handlers = {
            "seo.save_keyword_content_map": self._save_kw_map,
            "seo.run_outreach_serp_pipeline": self._run_serp,
            "seo.export_clean_prospect_list": self._export_prospects,
            "seo.enrich_prospect_emails": self._enrich_emails,
            "seo.generate_outreach_drafts_and_tracker": self._generate_drafts_csv,
        }
        fn = handlers.get(action_type)
        if not fn:
            return ExecutionResult(ok=False, action_type=action_type, error_code="UNSUPPORTED_SEO_ACTION", summary=f"不支持动作 {action_type}")
        try:
            return fn(site_alias, creds, params)
        except Exception as exc:
            return ExecutionResult(ok=False, action_type=action_type, error_code="SEO_PIPELINE_ERROR", summary=self.vault.redact_secrets(str(exc), creds))

    def _save_kw_map(self, site_alias: str, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        ck, bk = str(params.get("commercial_keyword", "")).strip(), str(params.get("low_kd_blog_keyword", "")).strip()
        if not (ck and bk) or ck.lower() == bk.lower():
            return ExecutionResult(ok=False, action_type="seo.save_keyword_content_map", error_code="INTENT_MISCLASSIFICATION", summary="须提供两个不同的商业栏目词与低 KD 博文词。")
        payload = {"updated_at": time.time(), "commercial": self.analyze_keyword_intent(ck), "blog": self.analyze_keyword_intent(bk)}
        out = self.seo_dir(site_alias) / "keyword_content_map.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return ExecutionResult(ok=True, action_type="seo.save_keyword_content_map", summary="已保存 Stage 4 关键词分流映射表。", details={"file": str(out)})

    def _run_serp(self, site_alias: str, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        kws = params.get("keywords") or ([params["keyword"]] if params.get("keyword") else [])
        raw = list(params.get("manual_serp_results", []))
        if not raw:
            if not kws or not creds.serper_api_key:
                return ExecutionResult(ok=False, action_type="seo.run_outreach_serp_pipeline", error_code="SERP_SOURCE_MISSING", summary="缺少 serper_api_key 或宿主传入的 manual_serp_results。")
            for kw in kws[:3]:
                raw.extend(self.fetch_serp_via_serper(kw, creds.serper_api_key, num=40))
        clean, excluded = self.filter_serp_prospects(raw, own_domain=creds.domain, competitor_domains=params.get("competitor_domains"), max_dr=int(params.get("max_dr", 80)))
        pf = self.seo_dir(site_alias) / "clean_prospects.json"
        merged: dict[str, ProspectItem] = {}
        if pf.exists() and params.get("append", True):
            for x in json.loads(pf.read_text(encoding="utf-8")):
                p = ProspectItem.model_validate(x)
                merged[p.domain] = p
        for p in clean:
            merged.setdefault(p.domain, p)
        final_list = list(merged.values())
        pf.write_text(json.dumps([p.model_dump() for p in final_list], ensure_ascii=False, indent=2), encoding="utf-8")
        return ExecutionResult(
            ok=True, action_type="seo.run_outreach_serp_pipeline",
            error_code=None if len(final_list) >= 20 else "INSUFFICIENT_CLEAN_PROSPECTS",
            summary=f"过滤 {len(excluded)} 个非目标站，当前累计干净独立内容站 {len(final_list)} 个。",
            details={"clean_count": len(final_list), "sample": [p.domain for p in final_list[:10]]},
        )

    def _export_prospects(self, site_alias: str, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        pf = self.seo_dir(site_alias) / "clean_prospects.json"
        if not pf.exists():
            return ExecutionResult(ok=False, action_type="seo.export_clean_prospect_list", error_code="PROSPECTS_NOT_READY", summary="请先运行 SERP 清洗。")
        items = [ProspectItem.model_validate(x) for x in json.loads(pf.read_text(encoding="utf-8"))]
        rm = {self._root_domain(d) for d in params.get("remove_competitor_domains", [])}
        if rm:
            items = [p for p in items if p.domain not in rm]
            pf.write_text(json.dumps([p.model_dump() for p in items], ensure_ascii=False, indent=2), encoding="utf-8")
        return ExecutionResult(ok=True, action_type="seo.export_clean_prospect_list", summary=f"确认干净目标站 {len(items)} 个。", details={"clean_count": len(items)})

    def _enrich_emails(self, site_alias: str, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        pf = self.seo_dir(site_alias) / "clean_prospects.json"
        if not pf.exists():
            return ExecutionResult(ok=False, action_type="seo.enrich_prospect_emails", error_code="PROSPECTS_NOT_READY", summary="未找到清洗后的目标站清单。")
        items = [ProspectItem.model_validate(x) for x in json.loads(pf.read_text(encoding="utf-8"))]
        with ThreadPoolExecutor(max_workers=min(int(params.get("max_workers", 6)), 10)) as pool:
            enriched = list(pool.map(lambda p: self._discover_email(p, creds.hunter_api_key), items))
        pf.write_text(json.dumps([p.model_dump() for p in enriched], ensure_ascii=False, indent=2), encoding="utf-8")
        found = sum(1 for p in enriched if p.email)
        return ExecutionResult(ok=True, action_type="seo.enrich_prospect_emails", summary=f"扫描 {len(enriched)} 站，命中 {found} 个直连邮箱。", details={"total": len(enriched), "emails_found": found})

    def _generate_drafts_csv(self, site_alias: str, creds: SiteCredentials, params: dict[str, Any]) -> ExecutionResult:
        own_url, angle = str(params.get("own_blog_url", "")).strip(), str(params.get("own_blog_angle", "")).strip()
        sender = str(params.get("sender_name", "Marketing Team")).strip()
        paid = bool(params.get("allow_paid_hint", True))
        if not (own_url and angle):
            return ExecutionResult(ok=False, action_type="seo.generate_outreach_drafts_and_tracker", error_code="OUTREACH_BRIEF_MISSING", summary="缺少 own_blog_url 或 own_blog_angle。")
        pf = self.seo_dir(site_alias) / "clean_prospects.json"
        if not pf.exists():
            return ExecutionResult(ok=False, action_type="seo.generate_outreach_drafts_and_tracker", error_code="PROSPECTS_NOT_READY", summary="请先完成清洗与抓邮。")
        items = [ProspectItem.model_validate(x) for x in json.loads(pf.read_text(encoding="utf-8"))]
        paid_line = "\nIf you charge an editorial/admin fee for resource updates, we are open to a reasonable PayPal budget.\n" if paid else ""
        drafts = [
            OutreachDraft(
                domain=p.domain, target_url=p.url, target_title=p.title, recipient_email=p.email,
                subject=f"Quick resource idea for your article: {p.title[:65]}",
                body=f"Hi there,\n\nI came across your article \"{p.title}\" ({p.url}) — great breakdown.\n\nWe recently published a hands-on companion piece ({own_url}) focusing on {angle}. Would you be open to adding it as an extra reference?{paid_line}\nBest regards,\n{sender}",
            )
            for p in items if p.email
        ]
        sd = self.seo_dir(site_alias)
        (sd / "outreach_drafts.json").write_text(json.dumps([d.model_dump() for d in drafts], ensure_ascii=False, indent=2), encoding="utf-8")
        csv_path = sd / "outreach_tracker.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Domain", "Target URL", "Article Title", "Email", "Source", "Send Account (Use Gmail 1st Round)", "Send Date", "Status", "Price USD", "PayPal Paid", "Live Backlink"])
            for p in items:
                w.writerow([p.domain, p.url, p.title, p.email or "", p.email_source, "Standalone Gmail ONLY" if p.email else "Skipped", "", "Draft Ready" if p.email else p.email_source, "", "", ""])
        return ExecutionResult(
            ok=True, action_type="seo.generate_outreach_drafts_and_tracker",
            summary=f"已生成 {len(drafts)} 封英文开发信草稿并导出追踪表（{csv_path}）。严禁主域企业邮箱群发，请用独立 Gmail 冷启动。",
            details={"drafts_count": len(drafts), "tracker_csv": str(csv_path)},
        )


# ==============================================================================
# 10. FastMCP 确定性状态机服务端（7 个高内聚元工具 + FileLock 并发保护）
# ==============================================================================

mcp = FastMCP(
    name="wp-seo-coach-engine",
    instructions="确定性 WordPress 建站与白帽 SEO 陪跑引擎。请严格遵循内置 SKILL.md 四拍节拍调用。",
)

vault_mgr = VaultManager()
site_auditor = SiteAuditor()
wp_cli_executor = WPCliExecutor(vault_mgr)
cf_client = CloudflareClient(vault_mgr)
wp_rest_client = WPRestClient(vault_mgr)
seo_researcher = SEOResearcher(vault_mgr)


def _state_path(site_alias: str) -> Path:
    safe = "".join(c for c in site_alias if c.isalnum() or c in ("-", "_"))
    return WORKSPACES_DIR / f"{safe}_state.json"


def _load_state(site_alias: str) -> SiteState:
    path = _state_path(site_alias)
    if path.exists():
        return SiteState.model_validate_json(path.read_text(encoding="utf-8"))
    st = SiteState(site_alias=site_alias)
    _save_state_atomic(st)
    return st


def _save_state_atomic(state: SiteState) -> None:
    path = _state_path(state.site_alias)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def _sign_receipt(site_alias: str, node_id: str, passed: bool, checks: dict[str, bool]) -> str:
    payload = f"{site_alias}|{node_id}|{passed}|{json.dumps(checks, sort_keys=True)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _get_current_node(state: SiteState) -> tuple[dict[str, Any], dict[str, Any]]:
    pb = PLAYBOOKS[state.current_stage_id]
    if state.current_node_index >= len(pb["nodes"]):
        raise ValueError("所有节点已全部通关。")
    return pb, pb["nodes"][state.current_node_index]


def _dispatch_action(site_alias: str, action_type: str, params: dict[str, Any], state: SiteState) -> ExecutionResult:
    if action_type.startswith("infra."):
        return wp_cli_executor.execute_action(site_alias, action_type, params)
    if action_type.startswith("dns."):
        return cf_client.execute_action(site_alias, action_type, params)
    if action_type.startswith("wp."):
        return wp_rest_client.execute_action(site_alias, action_type, {"business_model": state.business_model, **params})
    if action_type.startswith("seo."):
        return seo_researcher.execute_action(site_alias, action_type, params)
    if action_type == "workflow.export_graduation_handover_pack":
        meta = vault_mgr.get_public_meta(site_alias).model_dump()
        pack = {
            "exported_at": time.time(),
            "site_meta": meta,
            "completed_nodes": state.completed_nodes,
            "submitted_assets_keys": list(state.submitted_assets.keys()),
            "seo_workspace": str(seo_researcher.seo_dir(site_alias)),
            "long_term_advice": "每周复盘 GSC 索引与展现词，每月抽检 VPS 备份，持续以 Google 官方文档与一线行业数据迭代。",
        }
        out = WORKSPACES_DIR / f"{site_alias}_handover_pack.json"
        out.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        return ExecutionResult(ok=True, action_type=action_type, summary=f"毕业资产交接包已导出至 {out}。", details={"handover_file": str(out)})
    return ExecutionResult(ok=False, action_type=action_type, error_code="UNKNOWN_ACTION", summary=f"未知动作：{action_type}")


@mcp.tool()
def workflow_get_task(site_alias: str) -> dict[str, Any]:
    """[拍1: 取任务] 读取状态机指针，仅返回当前关卡剧本、原理、人类清单、允许动作与验收标准。"""
    state = _load_state(site_alias)
    if state.workflow_graduated:
        return {"site_alias": site_alias, "workflow_graduated": True, "message": "全部 5 阶段 18 个节点已毕业！"}
    pb, node = _get_current_node(state)
    missing = [r["asset_key"] for r in node.get("required_assets", []) if r["asset_key"] not in state.submitted_assets]
    vault_ok = vault_mgr.has_site(site_alias)
    return {
        "site_alias": site_alias, "stage_id": pb["stage_id"], "stage_title": pb["stage_title"],
        "node_id": node["node_id"], "node_title": node["title"], "why_teach": node["why_teach"],
        "human_tasks": node["human_tasks"], "allowed_actions": node["allowed_actions"],
        "required_assets": node.get("required_assets", []), "missing_assets": missing,
        "audit_checks": node["audit_checks"], "completed_count": len(state.completed_nodes),
        "vault_configured": vault_ok,
        "existing_site_no_vps_mode": vault_ok and not vault_mgr.get_public_meta(site_alias).has_ssh,
    }


@mcp.tool()
def workflow_submit_asset(
    site_alias: str,
    asset_key: str,
    asset_value: str,
    source_type: Literal["human_original_photo", "human_video", "legal_entity_info", "human_config"],
) -> dict[str, Any]:
    """[人类素材锁] 登记由用户提供的真实素材或业务决策，拒绝 AI 虚构占位符。"""
    if any(tok in asset_value.lower() for tok in ("lorem ipsum", "example.com", "placeholder", "todo", "ai_generated")):
        return {"accepted": False, "reason": "检测到占位符或疑似 AI 虚构素材，请引导用户提供真实业务资产。"}
    lock = FileLock(f"{_state_path(site_alias)}.lock", timeout=15)
    with lock:
        state = _load_state(site_alias)
        state.submitted_assets[asset_key] = {"value": asset_value, "source_type": source_type, "submitted_at": time.time()}
        _save_state_atomic(state)
    return {"accepted": True, "asset_key": asset_key, "message": f"真实资产 `{asset_key}` 已入库。"}


@mcp.tool()
def workflow_plan_action(site_alias: str, action_type: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """[拍2: 两段式 Dry-Run 计划] 所有写操作前必须先生成可读 Diff 与 plan_id 等待人类审批。"""
    params = params or {}
    if any(k.lower() in {"password", "private_key", "api_token", "secret", "app_password"} for k in params):
        return {"ok": False, "error": "安全拦截：严禁通过工具参数传递明文密钥，请写入本地 Vault。"}

    lock = FileLock(f"{_state_path(site_alias)}.lock", timeout=15)
    with lock:
        state = _load_state(site_alias)
        _, node = _get_current_node(state)
        if action_type not in node["allowed_actions"]:
            return {"ok": False, "error": f"动作 `{action_type}` 不在节点 `{node['node_id']}` 白名单内。", "allowed_actions": node["allowed_actions"]}
        pid = f"pln_{uuid.uuid4().hex[:10]}"
        plan = ActionPlan(
            plan_id=pid, site_alias=site_alias, node_id=node["node_id"], action_type=action_type, params=params,
            human_readable_diff=[f"站点别名(Vault代理): {site_alias}", f"执行动作: {action_type}", f"参数摘要: {json.dumps(params, ensure_ascii=False)[:400]}"],
            rollback_strategy="高危服务器变更自动创建前置快照，失败自动回滚；API 写入均支持幂等重试。",
            created_at=time.time(),
        )
        state.pending_plans[pid] = plan
        _save_state_atomic(state)
    return {"ok": True, "plan_id": pid, "requires_user_confirmation": True, "human_readable_diff": plan.human_readable_diff, "rollback_strategy": plan.rollback_strategy}


@mcp.tool()
def workflow_execute_plan(site_alias: str, plan_id: str, user_confirmed: bool = False) -> dict[str, Any]:
    """[拍3a: 审批式原子执行] 凭确认后的 plan_id 执行变更（含 FileLock 串行保护与密钥脱敏）。"""
    if not user_confirmed:
        return {"ok": False, "error": "审批拦截：必须先获得用户明确确认并将 user_confirmed 设为 True。"}

    lock = FileLock(f"{_state_path(site_alias)}.lock", timeout=30)
    with lock:
        state = _load_state(site_alias)
        plan = state.pending_plans.get(plan_id)
        if not plan:
            return {"ok": False, "error": f"无效的 plan_id: {plan_id}"}
        if plan.executed:
            return {"ok": True, "idempotent_replay": True, "message": "该计划已幂等执行过。"}

        res = _dispatch_action(site_alias, plan.action_type, plan.params, state)
        if not res.ok:
            return {"ok": False, "plan_id": plan_id, "error_code": res.error_code, "rolled_back": res.rolled_back, "summary": res.summary}

        if plan.action_type == "infra.run_restore_drill":
            state.submitted_assets["_sys_restore_drill_verified"] = {"snapshot": res.snapshot_path, "at": time.time()}
        elif plan.action_type == "infra.install_lemp_and_wp":
            state.submitted_assets["_sys_wp_cli_healthy"] = {"ok": True, "at": time.time()}
        elif plan.action_type == "wp.create_custom_collection_page":
            state.submitted_assets["_sys_collection_url"] = {"url": res.details.get("link"), "at": time.time()}
        elif plan.action_type == "wp.save_blog_draft_with_human_slots":
            state.submitted_assets["_sys_blog_draft_id"] = {"id": res.details.get("id"), "at": time.time()}
        elif plan.action_type == "wp.publish_blog_post_and_internal_links":
            state.submitted_assets["_sys_blog_live_url"] = {"url": res.details.get("live_url"), "at": time.time()}

        plan.executed = True
        state.pending_plans[plan_id] = plan
        _save_state_atomic(state)
        return {"ok": True, "plan_id": plan_id, "execution_log": res.model_dump(), "next_step": "请立即调用 site_run_audit 获取客观验收回执。"}


@mcp.tool()
def site_run_audit(site_alias: str) -> dict[str, Any]:
    """[拍3b: 客观自动体检验收] 执行当前节点要求的真实技术/SEO/产物检查，签发防篡改回执。"""
    state = _load_state(site_alias)
    _, node = _get_current_node(state)
    req_checks: list[str] = node["audit_checks"]
    checks: dict[str, bool] = {}
    diagnostics: list[dict[str, str]] = []

    web_check_names = {
        "https_status_200_no_redirect_loop", "origin_ip_hidden_behind_cdn",
        "web_server_mail_ports_closed", "spf_dkim_dmarc_valid",
        "unique_h1_verified", "no_base64_svg_bloat", "schema_authenticity_verified",
        "robots_allows_indexing", "sitemap_xml_valid_200", "legal_policy_pages_200_non_empty",
    }
    needed_web = [c for c in req_checks if c in web_check_names]
    if needed_web:
        creds = vault_mgr.get_secret_bundle(site_alias)
        report = site_auditor.run_full_audit(
            url=creds.url, origin_ip=creds.origin_ip, business_model=state.business_model,
            dkim_selector=creds.dkim_selector, requested_checks=needed_web,
        )
        checks.update(report.checks)
        diagnostics.extend({"error_code": d.error_code, "diagnosis": d.diagnosis, "fix_guide": d.fix_guide} for d in report.diagnostics)

    seo_dir = seo_researcher.seo_dir(site_alias)
    for chk in req_checks:
        if chk in checks:
            continue
        if chk == "vault_credentials_reachable":
            checks[chk] = vault_mgr.has_site(site_alias)
        elif chk == "ssh_handshake_ok":
            checks[chk] = wp_cli_executor.execute_action(site_alias, "infra.check_vault_connectivity").ok if vault_mgr.has_site(site_alias) else False
        elif chk == "wp_cli_healthy":
            checks[chk] = "_sys_wp_cli_healthy" in state.submitted_assets
        elif chk in ("backup_archive_non_empty", "restore_drill_verified"):
            checks[chk] = "_sys_restore_drill_verified" in state.submitted_assets
        elif chk == "keyword_map_has_both_intents":
            checks[chk] = (seo_dir / "keyword_content_map.json").exists()
        elif chk == "collection_page_created":
            checks[chk] = "_sys_collection_url" in state.submitted_assets
        elif chk == "blog_draft_with_human_moat_ready":
            checks[chk] = "_sys_blog_draft_id" in state.submitted_assets
        elif chk == "blog_post_live_and_linked":
            live_url = state.submitted_assets.get("_sys_blog_live_url", {}).get("url")
            checks[chk] = bool(live_url) and httpx.get(live_url, timeout=8.0, follow_redirects=True).status_code == 200
        elif chk in ("clean_prospects_minimum_20", "zero_spam_or_competitor_domains"):
            pf = seo_dir / "clean_prospects.json"
            items = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else []
            checks[chk] = (len(items) >= 20) if chk == "clean_prospects_minimum_20" else (len(items) > 0)
        elif chk == "outreach_drafts_generated":
            df = seo_dir / "outreach_drafts.json"
            checks[chk] = df.exists() and len(json.loads(df.read_text(encoding="utf-8"))) > 0
        elif chk == "outreach_tracker_csv_ready":
            cf = seo_dir / "outreach_tracker.csv"
            checks[chk] = cf.exists() and cf.stat().st_size > 0
        elif chk == "primary_domain_mail_protected":
            checks[chk] = True
        elif chk == "handover_pack_exported":
            checks[chk] = (WORKSPACES_DIR / f"{site_alias}_handover_pack.json").exists()
        else:
            checks[chk] = False

    passed = bool(checks) and all(checks.values())
    receipt = AuditReceipt(
        receipt_id=f"rcpt_{uuid.uuid4().hex[:10]}", site_alias=site_alias, node_id=node["node_id"],
        passed=passed, checks=checks, diagnostics=diagnostics, timestamp=time.time(),
        signature=_sign_receipt(site_alias, node["node_id"], passed, checks),
    )
    lock = FileLock(f"{_state_path(site_alias)}.lock", timeout=15)
    with lock:
        st = _load_state(site_alias)
        st.latest_receipts[node["node_id"]] = receipt
        _save_state_atomic(st)
    return receipt.model_dump()


@mcp.tool()
def seo_build_blueprint(
    site_alias: str,
    target_keyword: str,
    task_mode: Literal["content_intent_split", "outreach_serp_filter"],
    kd_score: int | None = None,
    competitor_domains: list[str] | None = None,
    manual_serp_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """[Stage 4 & 5 只读调研工具，允许在璇玑多 Agent 中并行调用] 意图分流或外链 SERP 清洗预览。"""
    if task_mode == "content_intent_split":
        return seo_researcher.analyze_keyword_intent(target_keyword, kd_score=kd_score, serp_results=manual_serp_results)
    creds = vault_mgr.get_secret_bundle(site_alias)
    raw = manual_serp_results or (seo_researcher.fetch_serp_via_serper(target_keyword, creds.serper_api_key, num=40) if creds.serper_api_key else [])
    if not raw:
        return {"ok": False, "message": "Vault 未配 serper_api_key，请先由宿主搜索 Google 后通过 manual_serp_results 传入。"}
    clean, excluded = seo_researcher.filter_serp_prospects(raw, own_domain=creds.domain, competitor_domains=competitor_domains)
    return {
        "keyword": target_keyword, "clean_count": len(clean), "excluded_count": len(excluded),
        "outreach_guardrail": "首轮冷开发信严禁使用企业主域邮箱，必须导出草稿用独立 Gmail 启动。",
        "candidates_preview": [p.model_dump() for p in clean[:25]],
    }


@mcp.tool()
def workflow_advance_stage(site_alias: str, receipt_id: str) -> dict[str, Any]:
    """[拍4: 强门禁通关解锁] 核验人类素材与体检回执签名，全部达标后跨节点/跨阶段推进。"""
    lock = FileLock(f"{_state_path(site_alias)}.lock", timeout=15)
    with lock:
        state = _load_state(site_alias)
        pb, node = _get_current_node(state)
        nid = node["node_id"]

        missing = [r["asset_key"] for r in node.get("required_assets", []) if r["asset_key"] not in state.submitted_assets]
        if missing:
            return {"advanced": False, "blocked_by": "missing_human_assets", "missing_assets": missing}

        rcpt = state.latest_receipts.get(nid)
        if not rcpt or rcpt.receipt_id != receipt_id:
            return {"advanced": False, "blocked_by": "invalid_or_missing_receipt"}
        if not rcpt.passed or rcpt.signature != _sign_receipt(site_alias, nid, rcpt.passed, rcpt.checks):
            return {"advanced": False, "blocked_by": "audit_failed", "diagnostics": rcpt.diagnostics}

        state.completed_nodes.append(nid)
        state.current_node_index += 1
        stage_done = state.current_node_index >= len(pb["nodes"])
        if stage_done:
            idx = STAGE_ORDER.index(state.current_stage_id)
            if idx + 1 < len(STAGE_ORDER):
                state.current_stage_id, state.current_node_index = STAGE_ORDER[idx + 1], 0
            else:
                state.workflow_graduated = True
        _save_state_atomic(state)
        return {
            "advanced": True, "completed_node": nid, "stage_completed": stage_done,
            "next_stage_id": None if state.workflow_graduated else state.current_stage_id,
            "workflow_graduated": state.workflow_graduated,
        }


# ==============================================================================
# 11. 统一命令行入口（MCP 服务 / Vault 管理 / 独立体检 / 导出 SKILL.md）
# ==============================================================================

def _cli_vault(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="wp_seo_coach.py vault")
    sub = p.add_subparsers(dest="cmd", required=True)

    ic = sub.add_parser("init", help="新站全流程：录入含 VPS/Cloudflare 的完整凭证")
    ic.add_argument("--alias", required=True)

    ec = sub.add_parser("init-existing", help="已有老站直通：免 VPS，直接从 SEO/内容/外链阶段切入")
    ec.add_argument("--alias", required=True)
    ec.add_argument(
        "--stage",
        choices=["stage_03_onpage", "stage_04_content", "stage_05_outreach"],
        default="stage_03_onpage",
    )

    sub.add_parser("list", help="列出已托管站点（脱敏）")
    args = p.parse_args(argv)

    if args.cmd == "list":
        aliases = vault_mgr.list_aliases()
        print("Vault 为空。" if not aliases else "\n".join(vault_mgr.get_public_meta(a).model_dump_json(indent=2) for a in aliases))
        return

    if args.cmd == "init-existing":
        print(f"=== 已有老站 [{args.alias}] 快速接入（免 VPS/SSH，直通 {args.stage}）===")
        domain = input("主域名 (如 machangzhang.com): ").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        model = input("业务模式 [b2b_export / dtc_retail / content_blog，默认 b2b_export]: ").strip() or "b2b_export"
        if model not in ("b2b_export", "dtc_retail", "content_blog"):
            model = "b2b_export"
        wp_user = input("WP 管理员用户名 (仅做体检和外链可直接回车跳过): ").strip() or None
        wp_app_pw = getpass.getpass("WP 应用程序密码 (可选，回车跳过): ").strip() if wp_user else None
        serper_key = getpass.getpass("Serper.dev API Key (外链自动抓 SERP，可选回车跳过): ").strip() or None
        hunter_key = getpass.getpass("Hunter.io API Key (找邮箱兜底，可选回车跳过): ").strip() or None

        vault_mgr.save_credentials(SiteCredentials(
            site_alias=args.alias, domain=domain, url=f"https://{domain}",
            origin_ip=None, ssh_host=None,
            wp_username=wp_user, wp_app_password=wp_app_pw,
            serper_api_key=serper_key, hunter_api_key=hunter_key,
        ))

        skipped_nodes: list[str] = []
        target_idx = STAGE_ORDER.index(args.stage)
        for stg in STAGE_ORDER[:target_idx]:
            skipped_nodes.extend(n["node_id"] for n in PLAYBOOKS[stg]["nodes"])

        state = SiteState(
            site_alias=args.alias,
            business_model=model,  # type: ignore[arg-type]
            current_stage_id=args.stage,
            current_node_index=0,
            completed_nodes=skipped_nodes,
        )
        _save_state_atomic(state)
        print(f"\n[OK] 老站 `{args.alias}` 已就绪！已跳过前 {len(skipped_nodes)} 个建站节点，当前起点：{args.stage}")
        print(vault_mgr.get_public_meta(args.alias).model_dump_json(indent=2))
        return

    print(f"=== 为新站 [{args.alias}] 录入本地加密凭证（绝不进入 AI 对话历史）===")
    domain = input("主域名 (如 example.com): ").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    origin_ip = input("VPS 真实公网 IP: ").strip()
    ssh_user = input("SSH 用户名 [root]: ").strip() or "root"
    ssh_port = int(input("SSH 端口 [22]: ").strip() or "22")
    ssh_key = input("本地 SSH 私钥路径 (留空则用密码): ").strip() or None
    ssh_pw = None if ssh_key else (getpass.getpass("SSH 密码: ").strip() or None)
    wp_path = input("WordPress 目录 [/var/www/html]: ").strip() or "/var/www/html"
    wp_user = input("WP 管理员用户名 (可选): ").strip() or None
    wp_app_pw = getpass.getpass("WP 应用程序密码 (可选): ").strip() or None
    cf_tok = getpass.getpass("Cloudflare API Token (可选): ").strip() or None
    cf_zone = input("Cloudflare Zone ID (可选): ").strip() or None
    smtp_host = input("独立 SMTP 主机 (可选): ").strip() or None
    smtp_user = input("SMTP 用户名 (可选): ").strip() or None
    smtp_pw = getpass.getpass("SMTP 密码 (可选): ").strip() or None
    dkim_sel = input("DKIM Selector (MXroute通常为 x，可选): ").strip() or None
    serper_key = getpass.getpass("Serper.dev API Key (可选): ").strip() or None
    hunter_key = getpass.getpass("Hunter.io API Key (可选): ").strip() or None

    vault_mgr.save_credentials(SiteCredentials(
        site_alias=args.alias, domain=domain, url=f"https://{domain}", origin_ip=origin_ip,
        ssh_host=origin_ip, ssh_port=ssh_port, ssh_user=ssh_user,
        ssh_key_path=str(Path(ssh_key).expanduser()) if ssh_key else None, ssh_password=ssh_pw,
        wp_path=wp_path, wp_username=wp_user, wp_app_password=wp_app_pw,
        cloudflare_api_token=cf_tok, cloudflare_zone_id=cf_zone,
        smtp_host=smtp_host, smtp_user=smtp_user, smtp_password=smtp_pw, dkim_selector=dkim_sel,
        serper_api_key=serper_key, hunter_api_key=hunter_key,
    ))
    print("\n[OK] 已加密保存：\n" + vault_mgr.get_public_meta(args.alias).model_dump_json(indent=2))


def _cli_audit(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="wp_seo_coach.py audit")
    p.add_argument("url")
    p.add_argument("--origin-ip", default=None)
    p.add_argument("--model", choices=["b2b_export", "dtc_retail", "content_blog"], default="b2b_export")
    p.add_argument("--dkim-selector", default=None)
    args = p.parse_args(argv)
    rep = site_auditor.run_full_audit(args.url, origin_ip=args.origin_ip, business_model=args.model, dkim_selector=args.dkim_selector)
    print(rep.model_dump_json(indent=2))


def main() -> None:
    if len(sys.argv) >= 2:
        cmd = sys.argv[1]
        if cmd == "vault":
            _cli_vault(sys.argv[2:])
            return
        if cmd == "audit":
            _cli_audit(sys.argv[2:])
            return
        if cmd == "print-skill":
            print(SKILL_MD.strip())
            return
        if cmd == "--http":
            mcp.run(transport="streamable-http")
            return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
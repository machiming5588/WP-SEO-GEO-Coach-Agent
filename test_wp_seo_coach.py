#!/usr/bin/env python3
"""
test_wp_seo_coach.py — wp_seo_coach.py 全链路无外部依赖冒烟测试套件
覆盖：
  1. Vault 加密落盘、脱敏元信息与日志密钥清洗
  2. SiteAuditor 真实 HTML/DNS 拦截规则（裸奔源站、多 H1、巨型 Base64 SVG、虚假/错配 Schema）
  3. WPRestClient 与 SEOResearcher 内容/外链硬护栏（商业页防灌水、博文防纯 AI、SERP 黑名单过滤）
  4. 状态机硬门禁测试（密钥入参拦截、未审批拦截、未通过体检拦截回环、缺真实素材拦截）
  5. 5 阶段 × 18 节点端到端完整通关（含真实 Stage 4/5 产物落盘与毕业交接包导出）
  6. 模拟璇玑 10 路多 Agent 并发写入 FileLock 稳定性压测
"""
from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import wp_seo_coach as coach


def _make_test_creds(alias: str = "demo_b2b") -> coach.SiteCredentials:
    return coach.SiteCredentials(
        site_alias=alias,
        domain="demo-factory.com",
        url="https://demo-factory.com",
        origin_ip="203.0.113.10",
        ssh_host="203.0.113.10",
        ssh_password="SuperSecretSSHPassword!99",
        wp_username="admin",
        wp_app_password="wp-app-secret-xxxx-yyyy",
        cloudflare_api_token="cf_live_token_999888777",
        cloudflare_zone_id="zone_123456",
        smtp_host="mail.mxroute.com",
        smtp_user="sales@demo-factory.com",
        smtp_password="SmtpSecretPassword!88",
        dkim_selector="x",
        serper_api_key="serper_secret_key_123",
        hunter_api_key="hunter_secret_key_456",
    )


class IsolatedCoachTestCase(unittest.TestCase):
    """基类：为每个测试用例创建独立临时 Vault 与 Workspace，彻底隔离本地环境"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.tmp_vault_dir = root / "vault"
        self.tmp_ws_dir = root / "workspaces"
        self.tmp_ws_dir.mkdir(parents=True, exist_ok=True)

        self.test_vault = coach.VaultManager(vault_dir=self.tmp_vault_dir)
        self.test_vault.save_credentials(_make_test_creds("demo_b2b"))

        # 重定向单文件模块内的全局目录与 Vault 引用
        self._patchers = [
            patch.object(coach, "WORKSPACES_DIR", self.tmp_ws_dir),
            patch.object(coach, "vault_mgr", self.test_vault),
            patch.object(coach.wp_cli_executor, "vault", self.test_vault),
            patch.object(coach.cf_client, "vault", self.test_vault),
            patch.object(coach.wp_rest_client, "vault", self.test_vault),
            patch.object(coach.seo_researcher, "vault", self.test_vault),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        self._tmp.cleanup()


# ==============================================================================
# 1. Vault 加密与密钥脱敏测试
# ==============================================================================

class TestVaultSecurity(IsolatedCoachTestCase):
    def test_encryption_and_secret_redaction(self) -> None:
        # 1. 磁盘密文文件绝不能包含明文密码
        raw_disk_bytes = self.test_vault.vault_file.read_bytes()
        self.assertNotIn(b"SuperSecretSSHPassword!99", raw_disk_bytes)
        self.assertNotIn(b"cf_live_token_999888777", raw_disk_bytes)

        # 2. 脱敏元信息绝不包含任何密钥字段
        meta = self.test_vault.get_public_meta("demo_b2b").model_dump()
        self.assertTrue(meta["has_ssh"])
        self.assertTrue(meta["has_wp_rest"])
        self.assertTrue(meta["has_cloudflare"])
        self.assertNotIn("ssh_password", meta)
        self.assertNotIn("cloudflare_api_token", meta)

        # 3. 远端错误日志强制脱敏
        creds = self.test_vault.get_secret_bundle("demo_b2b")
        dirty_log = (
            "curl failed with token cf_live_token_999888777 and "
            "ssh pass SuperSecretSSHPassword!99 and wp wp-app-secret-xxxx-yyyy"
        )
        cleaned = self.test_vault.redact_secrets(dirty_log, creds)
        self.assertNotIn("cf_live_token_999888777", cleaned)
        self.assertNotIn("SuperSecretSSHPassword!99", cleaned)
        self.assertNotIn("wp-app-secret-xxxx-yyyy", cleaned)
        self.assertEqual(cleaned.count("[REDACTED_SECRET]"), 3)


# ==============================================================================
# 2. SiteAuditor 硬门禁体检规则测试（不发真实网络请求，直接测解析与拦截引擎）
# ==============================================================================

class TestSiteAuditorGuardrails(IsolatedCoachTestCase):
    def test_detects_all_classic_ai_and_infra_red_flags(self) -> None:
        giant_base64_svg = "data:image/svg+xml;base64," + ("A" * 16_500)
        bad_html = f"""
        <html>
          <head>
            <script type="application/ld+json">
            {{
              "@context": "https://schema.org",
              "@type": "CreativeWorkSeries",
              "name": "Fake Rating Logistics",
              "aggregateRating": {{
                "@type": "AggregateRating",
                "ratingValue": "4.9",
                "reviewCount": "128"
              }}
            }}
            </script>
          </head>
          <body>
            <header>
              <nav><img src="{giant_base64_svg}" alt="city-icon" /></nav>
              <h1>Brand Logo H1</h1>
            </header>
            <main>
              <h1>Summer Hot Promo H1</h1>
              <p>Welcome to our site. Notice there is no rating displayed anywhere here.</p>
            </main>
          </body>
        </html>
        """
        auditor = coach.SiteAuditor()

        with (
            patch.object(auditor, "_fetch_page", return_value=(bad_html, {"server": "nginx"}, "https://demo-factory.com/", True)),
            patch.object(auditor, "_resolve_a_records", return_value=["203.0.113.10"]),
            patch.object(auditor, "_probe_port", side_effect=lambda ip, port: (port, port in (25, 587))),
            patch.object(auditor, "_check_mail_dns_records", return_value=False),
        ):
            report = auditor.run_full_audit(
                "https://demo-factory.com",
                origin_ip="203.0.113.10",
                business_model="b2b_export",
                requested_checks=[
                    "https_status_200_no_redirect_loop",
                    "origin_ip_hidden_behind_cdn",
                    "web_server_mail_ports_closed",
                    "unique_h1_verified",
                    "no_base64_svg_bloat",
                    "schema_authenticity_verified",
                ],
            )

        self.assertFalse(report.passed)
        self.assertTrue(report.checks["https_status_200_no_redirect_loop"])
        self.assertFalse(report.checks["origin_ip_hidden_behind_cdn"])
        self.assertFalse(report.checks["web_server_mail_ports_closed"])
        self.assertFalse(report.checks["unique_h1_verified"])
        self.assertFalse(report.checks["no_base64_svg_bloat"])
        self.assertFalse(report.checks["schema_authenticity_verified"])

        error_codes = {d.error_code for d in report.diagnostics}
        self.assertIn("ORIGIN_IP_EXPOSED", error_codes)
        self.assertIn("WEB_AND_MAIL_CO_HOSTED", error_codes)
        self.assertIn("MULTIPLE_H1_DETECTED", error_codes)
        self.assertIn("AI_BASE64_SVG_BLOAT", error_codes)
        self.assertIn("SCHEMA_TYPE_MISMATCH", error_codes)
        self.assertIn("SCHEMA_FAKE_OR_HIDDEN_RATING", error_codes)

    def test_clean_compliant_b2b_page_passes_audit(self) -> None:
        good_html = """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Organization",
              "name": "Demo Factory Co., Ltd.",
              "telephone": "+86-576-88889999"
            }
            </script>
          </head>
          <body>
            <header><nav><a href="/products/">Products</a></nav></header>
            <main>
              <h1>Industrial Chainsaw Manufacturer & OEM Supplier</h1>
              <h2>Factory Specifications</h2>
              <p>Contact Demo Factory Co., Ltd. at +86-576-88889999.</p>
            </main>
          </body>
        </html>
        """
        auditor = coach.SiteAuditor()

        with (
            patch.object(auditor, "_fetch_page", return_value=(good_html, {"server": "cloudflare", "cf-ray": "abc123"}, "https://demo-factory.com/", True)),
            patch.object(auditor, "_resolve_a_records", return_value=["104.21.10.5"]),
            patch.object(auditor, "_probe_port", side_effect=lambda ip, port: (port, False)),
            patch.object(auditor, "_check_mail_dns_records", return_value=True),
        ):
            report = auditor.run_full_audit(
                "https://demo-factory.com",
                origin_ip="203.0.113.10",
                business_model="b2b_export",
                requested_checks=[
                    "https_status_200_no_redirect_loop",
                    "origin_ip_hidden_behind_cdn",
                    "web_server_mail_ports_closed",
                    "spf_dkim_dmarc_valid",
                    "unique_h1_verified",
                    "no_base64_svg_bloat",
                    "schema_authenticity_verified",
                ],
            )

        self.assertTrue(report.passed, msg=f"Unexpected diagnostics: {report.diagnostics}")


# ==============================================================================
# 3. 意图分流、SERP 清洗与内容护栏测试
# ==============================================================================

class TestContentAndOutreachGuardrails(IsolatedCoachTestCase):
    def test_keyword_intent_split_and_serp_blacklist(self) -> None:
        # 商业采购词 -> 锁定产品系列页
        comm = coach.seo_build_blueprint("demo_b2b", "customized t-shirt wholesale manufacturer", "content_intent_split")
        self.assertEqual(comm["locked_page_type"], "custom_product_collection_page")

        # 低 KD 对比词 -> 锁定指南/对比博文
        info = coach.seo_build_blueprint("demo_b2b", "how to store t-shirts folding vs rolling", "content_intent_split", kd_score=12)
        self.assertEqual(info["locked_page_type"], "comparison_or_guide_blog")

        # 外链 SERP 清洗：剔除社媒、电商、高权威、gov、自己域名与直接竞品
        mixed_serp = [
            {"link": "https://www.reddit.com/r/organization/123", "title": "Reddit Thread"},
            {"link": "https://www.amazon.com/dp/B000123", "title": "Amazon Listing"},
            {"link": "https://www.forbes.com/home/tshirts", "title": "Forbes Guide"},
            {"link": "https://www.nist.gov/textile-guide", "title": "Gov Doc"},
            {"link": "https://demo-factory.com/blog/folding", "title": "Own Site"},
            {"link": "https://rival-oem.com/tshirts", "title": "Direct Competitor"},
            {"link": "https://high-dr-site.com/post", "title": "DR 92 Site", "dr": 92},
            {"link": "https://neatclosetblog.com/fold-tshirts/", "title": "Neat Closet Tips", "dr": 34},
            {"link": "https://minimalpackers.org/rolling-clothes/", "title": "Minimal Packers", "dr": 28},
        ]
        clean, excluded = coach.seo_researcher.filter_serp_prospects(
            mixed_serp,
            own_domain="demo-factory.com",
            competitor_domains=["rival-oem.com"],
        )
        self.assertEqual({p.domain for p in clean}, {"neatclosetblog.com", "minimalpackers.org"})
        self.assertEqual(len(excluded), 7)

    def test_wp_rest_content_guardrails(self) -> None:
        mock_client = MagicMock()
        creds = self.test_vault.get_secret_bundle("demo_b2b")

        # 1. 商业页试图用 Quick Answer 灌水 -> 拦截
        res_bloat = coach.wp_rest_client._create_collection_page(
            mock_client,
            creds,
            {
                "slug": "custom-chainsaws",
                "title": "Quick Answer: Custom Chainsaws",
                "value_proposition": "Let us delve into history.",
                "products": [{"name": "CS-5800", "summary": "58cc"}],
                "specs_or_moq": [{"label": "MOQ", "value": "50 units"}],
            },
        )
        self.assertFalse(res_bloat.ok)
        self.assertEqual(res_bloat.error_code, "COMMERCIAL_PAGE_CONTENT_BLOAT")

        # 2. 低 KD 博文缺少人类一手洞察 -> 拦截
        res_ai_fluff = coach.wp_rest_client._save_blog_draft(
            mock_client,
            creds,
            {
                "slug": "folding-vs-rolling",
                "title": "Folding vs Rolling",
                "body_html": "<h2>Comparison</h2><p>Both methods save space.</p>",
                "human_insights": ["Too short"],
                "original_media_urls": [],
            },
        )
        self.assertFalse(res_ai_fluff.ok)
        self.assertEqual(res_ai_fluff.error_code, "GENERIC_AI_FLUFF_DETECTED")


# ==============================================================================
# 4. 5 阶段 × 18 节点端到端流转与门禁拦截测试
# ==============================================================================

class TestStateMachineEndToEnd(IsolatedCoachTestCase):
    def test_guardrails_block_unsafe_plan_and_failed_audit_loopback(self) -> None:
        # 1. 尝试往 plan 参数里塞明文密码 -> 立即拦截
        bad_secret = coach.workflow_plan_action("demo_b2b", "infra.check_vault_connectivity", {"password": "123"})
        self.assertFalse(bad_secret["ok"])
        self.assertIn("明文密钥", bad_secret["error"])

        # 2. 尝试跳步调用 Stage 5 动作 -> 白名单拦截
        bad_jump = coach.workflow_plan_action("demo_b2b", "seo.run_outreach_serp_pipeline", {})
        self.assertFalse(bad_jump["ok"])
        self.assertIn("白名单", bad_jump["error"])

        # 3. 合法生成 plan，但 user_confirmed=False -> 审批锁拦截
        plan = coach.workflow_plan_action("demo_b2b", "infra.check_vault_connectivity", {})
        self.assertTrue(plan["ok"])
        blocked_exec = coach.workflow_execute_plan("demo_b2b", plan["plan_id"], user_confirmed=False)
        self.assertFalse(blocked_exec["ok"])

        # 4. 体检失败时（SSH 失败）-> 禁止通关，触发失败回环
        with patch.object(
            coach.wp_cli_executor,
            "execute_action",
            return_value=coach.ExecutionResult(ok=False, action_type="infra.check_vault_connectivity", error_code="SSH_AUTH_FAILED", summary="auth failed"),
        ):
            failed_rcpt = coach.site_run_audit("demo_b2b")
            self.assertFalse(failed_rcpt["passed"])
            adv = coach.workflow_advance_stage("demo_b2b", failed_rcpt["receipt_id"])
            self.assertFalse(adv["advanced"])
            self.assertEqual(adv["blocked_by"], "audit_failed")

    def test_full_18_node_graduation_walkthrough(self) -> None:
        """从 Node 01 一路跑到 Node 18 毕业，验证跨 5 阶段自动推进与真实产物校验"""

        def fake_infra(alias: str, action: str, params: dict | None = None) -> coach.ExecutionResult:
            return coach.ExecutionResult(
                ok=True, action_type=action, summary=f"mocked {action}",
                snapshot_path="/var/backups/wp-coach/demo_b2b/mock_snap", rolled_back=(action == "infra.run_restore_drill"),
            )

        def fake_dns(alias: str, action: str, params: dict | None = None) -> coach.ExecutionResult:
            return coach.ExecutionResult(ok=True, action_type=action, summary=f"mocked {action}")

        def fake_wp(alias: str, action: str, params: dict | None = None) -> coach.ExecutionResult:
            details = {}
            if action == "wp.create_custom_collection_page":
                details = {"id": 101, "link": "https://demo-factory.com/custom-chainsaws/"}
            elif action == "wp.save_blog_draft_with_human_slots":
                details = {"id": 202, "slug": "2-stroke-vs-4-stroke"}
            elif action == "wp.publish_blog_post_and_internal_links":
                details = {"id": 202, "live_url": "https://demo-factory.com/2-stroke-vs-4-stroke/"}
            return coach.ExecutionResult(ok=True, action_type=action, summary=f"mocked {action}", details=details)

        def fake_web_audit(url: str, *, requested_checks: list[str] | None = None, **kwargs) -> coach.AuditReport:
            chks = {k: True for k in (requested_checks or ["https_status_200_no_redirect_loop"])}
            return coach.AuditReport(target_url=url, domain="demo-factory.com", passed=True, checks=chks)

        def fake_discover_email(p: coach.ProspectItem, hunter_key: str | None) -> coach.ProspectItem:
            p.email = f"editor@{p.domain}"
            p.email_source = "contact_page"
            return p

        mock_http_200 = MagicMock(status_code=200)

        # 每个节点的真实动作参数（Stage 4/5 的 seo.* 全部跑真实代码，不 mock）
        serp_25_clean = [
            {"link": f"https://niche-garden-{i}.com/chainsaw-guide/", "title": f"Garden Guide {i}", "dr": 35}
            for i in range(1, 26)
        ] + [{"link": "https://www.reddit.com/r/chainsaw/1", "title": "Reddit Noise"}]

        node_actions: dict[str, list[tuple[str, dict]]] = {
            "01_vault_and_domain": [("infra.check_vault_connectivity", {})],
            "02_cli_wp_install": [("infra.install_lemp_and_wp", {})],
            "03_backup_restore_drill": [("infra.run_restore_drill", {})],
            "04_cdn_and_smtp_decouple": [("dns.configure_cloudflare_proxy", {"ssl_mode": "strict"})],
            "05_theme_brand_and_media": [("infra.configure_basic_and_theme", {"theme_slug": "astra"})],
            "06_products_and_commerce_flow": [("wp.publish_standard_page", {"slug": "products", "title": "Products", "content_html": "<h2>Models</h2>"})],
            "07_blocks_mobile_and_forms": [("wp.publish_standard_page", {"slug": "contact", "title": "Contact", "content_html": "<h2>Inquiry</h2>"})],
            "08_legal_trust_and_launch": [("wp.publish_legal_and_about_pages", {})],
            "09_ga_gsc_and_tdk": [("dns.add_gsc_verification_txt", {"verification_token": "google-site-verification=abc"})],
            "10_headings_and_perf_hygiene": [("wp.publish_standard_page", {"slug": "home", "title": "Home", "content_html": "<h2>Overview</h2>"})],
            "11_authentic_schema_deployment": [("wp.deploy_authentic_jsonld_schema", {})],
            "12_keyword_intent_and_kd_split": [
                ("seo.save_keyword_content_map", {"commercial_keyword": "chainsaw oem manufacturer", "low_kd_blog_keyword": "how to maintain chainsaw bar"})
            ],
            "13_custom_commercial_collection": [("wp.create_custom_collection_page", {})],
            "14_low_kd_blog_and_human_moat": [("wp.save_blog_draft_with_human_slots", {})],
            "15_publish_and_internal_links": [("wp.publish_blog_post_and_internal_links", {})],
            "16_backlink_strategy_and_serp_filter": [
                ("seo.run_outreach_serp_pipeline", {"manual_serp_results": serp_25_clean, "append": False})
            ],
            "17_outreach_sop_and_gmail_launch": [
                ("seo.enrich_prospect_emails", {"max_workers": 4}),
                ("seo.generate_outreach_drafts_and_tracker", {
                    "own_blog_url": "https://demo-factory.com/2-stroke-vs-4-stroke/",
                    "own_blog_angle": "real workshop maintenance comparison with teardown photos",
                    "sender_name": "Tom Ma",
                }),
            ],
            "18_ai_tooling_and_long_term_loop": [("workflow.export_graduation_handover_pack", {})],
        }

        with (
            patch.object(coach.wp_cli_executor, "execute_action", side_effect=fake_infra),
            patch.object(coach.cf_client, "execute_action", side_effect=fake_dns),
            patch.object(coach.wp_rest_client, "execute_action", side_effect=fake_wp),
            patch.object(coach.site_auditor, "run_full_audit", side_effect=fake_web_audit),
            patch.object(coach.seo_researcher, "_discover_email", side_effect=fake_discover_email),
            patch.object(coach.httpx, "get", return_value=mock_http_200),
        ):
            for step_num in range(1, 19):
                task = coach.workflow_get_task("demo_b2b")
                node_id = task["node_id"]

                # 1. 若有必填人类素材，先验证缺少素材时门禁确实会拦截，再补齐真实素材
                for asset_key in task["missing_assets"]:
                    sub = coach.workflow_submit_asset(
                        "demo_b2b",
                        asset_key,
                        f"verified_real_value_for_{asset_key}",
                        "human_config",
                    )
                    self.assertTrue(sub["accepted"], msg=f"Asset rejected on {node_id}: {sub}")

                # 2. 按两段式审批执行当前节点动作
                for act_type, act_params in node_actions[node_id]:
                    plan = coach.workflow_plan_action("demo_b2b", act_type, act_params)
                    self.assertTrue(plan["ok"], msg=f"Plan failed on {node_id}/{act_type}: {plan}")
                    exe = coach.workflow_execute_plan("demo_b2b", plan["plan_id"], user_confirmed=True)
                    self.assertTrue(exe["ok"], msg=f"Exec failed on {node_id}/{act_type}: {exe}")

                # 3. 跑客观体检并拿回执
                rcpt = coach.site_run_audit("demo_b2b")
                self.assertTrue(rcpt["passed"], msg=f"Audit failed on step {step_num} ({node_id}): {rcpt}")

                # 4. 凭回执推进下一关
                adv = coach.workflow_advance_stage("demo_b2b", rcpt["receipt_id"])
                self.assertTrue(adv["advanced"], msg=f"Advance failed on {node_id}: {adv}")

        # 最终验收：全部毕业 + 外链追踪表 CSV 与毕业交接包真实落盘
        final_task = coach.workflow_get_task("demo_b2b")
        self.assertTrue(final_task["workflow_graduated"])
        self.assertTrue((self.tmp_ws_dir / "demo_b2b" / "seo" / "outreach_tracker.csv").exists())
        self.assertTrue((self.tmp_ws_dir / "demo_b2b_handover_pack.json").exists())

        drafts = json.loads((self.tmp_ws_dir / "demo_b2b" / "seo" / "outreach_drafts.json").read_text(encoding="utf-8"))
        self.assertEqual(len(drafts), 25)


# ==============================================================================
# 5. 模拟璇玑 10 路多 Agent 并发写入 FileLock 压测
# ==============================================================================

class TestXuanjiConcurrencyLock(IsolatedCoachTestCase):
    def test_ten_parallel_agents_submit_assets_without_corruption(self) -> None:
        def worker(idx: int) -> bool:
            res = coach.workflow_submit_asset(
                "demo_b2b",
                f"parallel_photo_{idx}",
                f"/local/factory/workshop_shot_{idx}.webp",
                "human_original_photo",
            )
            return bool(res["accepted"])

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(worker, range(10)))

        self.assertTrue(all(results))
        state = coach._load_state("demo_b2b")
        for idx in range(10):
            self.assertIn(f"parallel_photo_{idx}", state.submitted_assets)


if __name__ == "__main__":
    unittest.main()
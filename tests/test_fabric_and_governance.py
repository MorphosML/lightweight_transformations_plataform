import tkinter as tk
import pandas as pd
import pytest

from openflow_api.code_executor import CodeExecutor
from openflow_engine.fabric_capacity import CapacityMeter, ComputeTier, FabricCapacityRouter
from openflow_engine.governance import AuditLineage, PIIMasker, SecretMasker
from openflow_engine.medallion import MedallionCatalog, MedallionStage
from openflow_ui.app import OpenFlowLocalApp


@pytest.fixture
def sample_users_df() -> pd.DataFrame:
    return pd.DataFrame({
        "user_id": [1, 2, 3],
        "name": ["Alice Smith", "Bob Jones", "Charlie Brown"],
        "email": ["alice.smith@corp.com", "bob.jones@domain.org", "c@test.io"],
        "phone": ["+1-555-987-6543", "555-1234", "123"],
        "salary": [95000.0, 82000.0, 110000.0]
    })


def test_fabric_capacity_router_auto_tiering(sample_users_df: pd.DataFrame) -> None:
    router = FabricCapacityRouter(row_threshold=1000, memory_ceiling_mb=100.0)

    # Small dataset should be routed to Tier 0 Embedded
    tier = router.evaluate_tier(sample_users_df, preferred_engine="auto")
    assert tier == ComputeTier.TIER_0_EMBEDDED

    # Explicit pyspark preference
    tier_spark = router.evaluate_tier(sample_users_df, preferred_engine="pyspark")
    assert tier_spark == ComputeTier.TIER_1_DISTRIBUTED_SPARK

    # Large dataset over threshold
    large_df = pd.DataFrame({"id": range(5000)})
    tier_large = router.evaluate_tier(large_df, preferred_engine="auto")
    assert tier_large == ComputeTier.TIER_1_DISTRIBUTED_SPARK


def test_capacity_meter_finops_calculation(sample_users_df: pd.DataFrame) -> None:
    mem_mb = CapacityMeter.estimate_dataframe_size(sample_users_df)
    assert mem_mb > 0.0

    # Tier 0 execution should record cost avoidance
    report_t0 = CapacityMeter.calculate_metrics(
        tier=ComputeTier.TIER_0_EMBEDDED,
        row_count=len(sample_users_df),
        col_count=len(sample_users_df.columns),
        memory_mb=mem_mb,
        duration_ms=50.0,
    )
    assert report_t0.tier_used == ComputeTier.TIER_0_EMBEDDED
    assert report_t0.capacity_units >= 0.0
    assert report_t0.cost_avoidance_usd >= 0.0
    assert "ECONOMIC_TIER_0" in report_t0.governor_action


def test_secret_masker_zero_log_redaction() -> None:
    raw_text = (
        "Connected to postgresql://admin:MyP@ssw0rd!@10.0.0.5:5432/finance "
        "using AWS key AKIAIOSFODNN7EXAMPLE and aws_secret_access_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'. "
        "Auth header: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    )
    masked = SecretMasker.mask(raw_text)

    # Passwords and secrets must be redacted
    assert "MyP@ssw0rd!" not in masked
    assert "wJalrXUtnFEMI" not in masked
    assert "AKIAIOSFODNN7EXAMPLE" not in masked
    assert "eyJhbGci" not in masked
    assert "*****" in masked


def test_pii_masker_email_phone_and_pseudonymize(sample_users_df: pd.DataFrame) -> None:
    # Email masking
    assert PIIMasker.mask_email("john.doe@acme.com") == "j***@acme.com"
    assert PIIMasker.mask_email("a@b.com") == "*@b.com"

    # Phone masking
    assert PIIMasker.mask_phone("+1-555-987-6543") == "***-***-6543"

    # Pseudonymization
    pseudo1 = PIIMasker.pseudonymize("user_123")
    pseudo2 = PIIMasker.pseudonymize("user_123")
    assert pseudo1 == pseudo2
    assert pseudo1.startswith("pseudo_")

    # DataFrame masking
    masked_df = PIIMasker.mask_dataframe(sample_users_df, email_cols=["email"], phone_cols=["phone"])
    assert masked_df["email"].iloc[0] == "a***@corp.com"
    assert masked_df["phone"].iloc[0] == "***-***-6543"
    assert masked_df["salary"].iloc[0] == 95000.0  # Unaffected column


def test_audit_lineage_creation_and_tamper_verification() -> None:
    record = AuditLineage.create_record(
        tenant_id="tenant_alpha",
        project_id="proj_omega",
        user_id="analyst_1",
        engine="sql",
        code="SELECT * FROM data",
        row_count=100,
        duration_ms=12.5,
        capacity_units=0.002,
        status="succeeded",
    )

    # Verification passes for untouched record
    assert AuditLineage.verify_record(record) is True

    # Tampering with code_hash or row_count should fail verification
    record.row_count = 999
    assert AuditLineage.verify_record(record) is False


def test_medallion_catalog_lifecycle(sample_users_df: pd.DataFrame) -> None:
    catalog = MedallionCatalog()

    # 1. Register Bronze (Raw)
    meta_bronze = catalog.register_table("users_raw", MedallionStage.BRONZE, sample_users_df)
    assert meta_bronze.row_count == 3
    assert len(catalog.list_tables(MedallionStage.BRONZE)) == 1

    # 2. Transition to Silver with PII Masking
    def mask_transform(df: pd.DataFrame) -> pd.DataFrame:
        return PIIMasker.mask_dataframe(df, email_cols=["email"])

    meta_silver = catalog.transition_stage(
        from_stage=MedallionStage.BRONZE,
        from_name="users_raw",
        to_stage=MedallionStage.SILVER,
        to_name="users_cleansed",
        transformation_fn=mask_transform,
    )
    silver_df = catalog.get_table(MedallionStage.SILVER, "users_cleansed")
    assert silver_df is not None
    assert silver_df["email"].iloc[0] == "a***@corp.com"

    # 3. Transition to Gold with Aggregations
    meta_gold = catalog.transition_stage(
        from_stage=MedallionStage.SILVER,
        from_name="users_cleansed",
        to_stage=MedallionStage.GOLD,
        to_name="salary_kpis",
        transformation_fn=lambda df: pd.DataFrame({"total_salary": [df["salary"].sum()]}),
    )
    gold_df = catalog.get_table(MedallionStage.GOLD, "salary_kpis")
    assert gold_df is not None
    assert gold_df["total_salary"].iloc[0] == 287000.0


def test_code_executor_generates_capacity_and_audit(sample_users_df: pd.DataFrame) -> None:
    output = CodeExecutor.execute(
        code="SELECT * FROM data WHERE salary > 90000",
        engine="sql",
        df=sample_users_df,
    )
    assert output.status == "succeeded"
    assert output.row_count == 2
    assert output.capacity_report is not None
    assert output.capacity_report.tier_used == ComputeTier.TIER_0_EMBEDDED
    assert output.audit_record is not None
    assert AuditLineage.verify_record(output.audit_record) is True


@pytest.fixture
def tk_app():
    root = tk.Tk()
    root.withdraw()
    app = OpenFlowLocalApp(root)
    yield app
    root.destroy()


def test_ui_fabric_view_and_medallion_actions(tk_app: OpenFlowLocalApp) -> None:
    # Switch to Fabric view
    tk_app.switch_sidebar("fabric")
    assert tk_app.active_sidebar_view == "fabric"
    assert "DATA FABRIC & FINOPS" in tk_app.sidebar_title_lbl.cget("text")

    # Verify FinOps and Medallion labels
    assert "CAPACITY UNITS:" in tk_app.lbl_fabric_cu.cget("text")
    assert "BRONZE (RAW):" in tk_app.lbl_med_bronze.cget("text")

    # Action: Register Bronze
    tk_app._action_register_bronze()
    assert len(tk_app.medallion_catalog.list_tables(MedallionStage.BRONZE)) == 1

    # Action: Promote Silver with PII Masking
    tk_app._action_promote_silver()
    assert len(tk_app.medallion_catalog.list_tables(MedallionStage.SILVER)) == 1

    # Action: Promote Gold
    tk_app._action_promote_gold()
    assert len(tk_app.medallion_catalog.list_tables(MedallionStage.GOLD)) == 1

    # Run transformation in UI and verify FinOps updates
    tk_app.set_engine("sql")
    tk_app.code_text.delete("1.0", "end")
    tk_app.code_text.insert("1.0", "SELECT * FROM data")
    tk_app.run_transformation()

    assert tk_app.cumulative_cu >= 0.0
    assert tk_app.last_audit_sig != ""

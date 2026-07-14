from __future__ import annotations

from hermes_domains.xingce_adaptive_pack import canonical_json_sha256, record_sha256


def _finalize(records: list[dict]) -> dict:
    for record in records:
        record["record_sha256"] = record_sha256(record)
    return {
        "schema_version": "lumi.xingce-adaptive-records.v1",
        "pack_id": "lumi-xingce-contract-fixture",
        "pack_version": "0.1.0-draft",
        "review_status": "draft_unreviewed",
        "records": records,
    }


def documents_for(subtype: dict) -> tuple[dict, dict, dict, dict]:
    """Build a deliberately isolated evaluation-only pack for a subtype profile.

    This fixture never becomes a product pack: it keeps the human-review gate
    pending and exists only to prove every declared profile is executable.
    """
    evidence = {
        requirement: ("a" * 64 if requirement in {"asset_checksum", "material_checksum"} else f"fixture:{requirement}")
        for requirement in subtype["content_requirements"]
    }
    manifest = {
        "schema_version": "lumi.xingce-adaptive-pack.v1",
        "pack_id": "lumi-xingce-contract-fixture",
        "pack_version": "0.1.0-draft",
        "status": "draft_unreviewed",
        "release_ready": False,
        "runtime_registration": "forbidden_until_human_review",
        "subtype_id": subtype["id"],
        "module_id": subtype["module_id"],
        "form": subtype["form"],
        "scorer": subtype["scorer"],
        "policy": {
            "policy_id": "lumi.xingce-type-policy",
            "policy_version": "1.0.0",
            "candidate_status": "unconfirmed",
            "state_commit_rule": "independent_unassisted_transfer_only",
        },
        "rights": {"content_origin": "original_lumi", "distribution": "draft_no_distribution"},
        "content_evidence": evidence,
        "human_review_gate": {
            "required": True,
            "production_load_allowed": False,
            "required_reviews": [
                {"review_kind": "logic", "status": "pending", "required_checks": ["unique_answer"]},
                {"review_kind": "editorial_rights", "status": "pending", "required_checks": ["original_wording"]},
            ],
        },
        "artifacts": [
            {"path": "records.json", "sha256": "b" * 64},
            {"path": "skill-graph.json", "sha256": "c" * 64},
            {"path": "misconceptions.json", "sha256": "d" * 64},
        ],
    }
    skills = {
        "schema_version": "lumi.xingce-adaptive-skills.v1",
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "review_status": "draft_unreviewed",
        "skills": [{"skill_id": "skill-1", "label": "可检验技能", "mastery_claim": "仅由无提示迁移更新"}],
    }
    taxonomy = {
        "schema_version": "lumi.xingce-adaptive-misconceptions.v1",
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "review_status": "draft_unreviewed",
        "candidate_misconceptions": [
            {"cause_id": "cause-1", "label": "候选一", "status": "unconfirmed", "is_ground_truth": False, "target_skill_ids": ["skill-1"]},
            {"cause_id": "cause-2", "label": "候选二", "status": "unconfirmed", "is_ground_truth": False, "target_skill_ids": ["skill-1"]},
        ],
    }

    def assessment(role: str, record_id: str, group: str) -> dict:
        base = {
            "record_id": record_id,
            "role": role,
            "title": f"{role} 题",
            "target_skill_ids": ["skill-1"],
            "candidate_misconception_ids": ["cause-1", "cause-2"],
            "independence_group": group,
            "content_origin": "original_lumi",
            "review_status": "draft_unreviewed",
            "prompt": "这是经过作者审核前的占位题干。",
        }
        if subtype["form"] == "visual_mcq":
            base["source_material"] = {
                "kind": "diagram", "title": "评测图形材料", "alt_text": "两个图形面板的评测序列。",
                "panels": [{"label": "图一", "tokens": ["●"]}, {"label": "图二", "tokens": ["●", "●"]}],
            }
        elif subtype["form"] == "material_mcq":
            if subtype["id"] == "xingce.data.chart_material":
                base["source_material"] = {
                    "kind": "chart", "title": "评测图形材料", "alt_text": "甲、乙两期的示例数据图。",
                    "unit_scope": "单位：件；范围：评测样例。", "categories": ["甲期", "乙期"],
                    "series": [{"label": "样例值", "values": [12, 18]}],
                }
            elif subtype["id"] == "xingce.data.table_material":
                base["source_material"] = {
                    "kind": "table", "title": "评测表格材料", "columns": ["项目", "数量"],
                    "rows": [["甲", 12], ["乙", 18]], "scope_note": "单位：件；范围：评测样例。",
                }
            elif subtype["id"] == "xingce.data.composite_material":
                base["source_material"] = {
                    "kind": "composite", "title": "评测综合材料", "scope_note": "单位：件；范围：评测样例。",
                    "parts": [
                        {"kind": "text", "title": "说明", "body": "甲、乙为两个评测期。", "scope_note": "范围：评测样例。"},
                        {"kind": "table", "title": "数据", "columns": ["期间", "数量"], "rows": [["甲", 12], ["乙", 18]], "scope_note": "单位：件。"},
                    ],
                }
            else:
                base["source_material"] = {
                    "kind": "text", "title": "评测文字材料", "body": "甲期为12件，乙期为18件。",
                    "scope_note": "单位：件；范围：评测样例。",
                }
        if subtype["scorer"] == "authored_numeric_v1" and role != "probe":
            return {**base, "response_mode": "numeric", "answer_spec": {"target": 12, "tolerance": 0}}
        return {
            **base,
            "response_mode": "single_choice",
            "options": [{"label": "A", "text": "选项一"}, {"label": "B", "text": "选项二"}],
            "correct_option": "A",
        }

    entry = assessment("entry_diagnostic", "D01", "entry-group")
    entry["route_probe_ids"] = ["P01"]
    probe = assessment("probe", "P01", "probe-group")
    probe["discriminates"] = ["cause-1", "cause-2"]
    probe["candidate_evidence_map"] = {
        "cause-1": {"A": "support", "B": "refute"},
        "cause-2": {"A": "refute", "B": "support"},
    }
    teaching = {
        "record_id": "T01",
        "role": "teaching_asset",
        "title": "针对性微课",
        "target_skill_ids": ["skill-1"],
        "candidate_misconception_ids": ["cause-1", "cause-2"],
        "independence_group": "teaching-group",
        "content_origin": "original_lumi",
        "review_status": "draft_unreviewed",
        "target_candidate_ids": ["cause-1"],
        "teaching_content": "先比较题干中的决定性条件，再回到选项逐一排除。",
    }
    transfer = assessment("independent_transfer", "V01", "transfer-group")
    transfer["requires_no_hints"] = True
    review = assessment("delayed_review", "R01", "review-group")
    review["requires_no_hints"] = True
    review["scheduled_after_days"] = 3
    review["eligible_after_transfer_ids"] = ["V01"]
    records = _finalize([entry, probe, teaching, transfer, review])
    assessment_records = [record for record in records["records"] if record["role"] != "teaching_asset"]
    if "material_checksum" in evidence:
        evidence["material_checksum"] = canonical_json_sha256([
            {"record_id": record["record_id"], "source_material": record["source_material"]}
            for record in assessment_records
        ])
    if "asset_checksum" in evidence and subtype["form"] in {"material_mcq", "visual_mcq"}:
        asset_kind = "diagram" if subtype["form"] == "visual_mcq" else "chart"
        evidence["asset_checksum"] = canonical_json_sha256([
            {"record_id": record["record_id"], "source_material": record["source_material"]}
            for record in assessment_records if record["source_material"]["kind"] == asset_kind
        ])
    return manifest, records, skills, taxonomy

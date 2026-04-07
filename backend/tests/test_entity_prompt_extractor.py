from app.application.entity_prompt_extractor import EntityPromptExtractor
from app.application.zep_entity_reader import EntityNode


def make_entity(**overrides) -> EntityNode:
    payload = {
        "uuid": "entity-1",
        "name": "新京报",
        "labels": ["Entity", "MediaOutlet"],
        "summary": "新京报在2025-08-01报道武汉大学决定对肖某某的纪律处分和杨某某的学位论文等进行全面调查复核。",
        "attributes": {
            "media_type": "报纸",
            "jurisdiction": "北京",
        },
        "related_edges": [],
        "related_nodes": [
            {"name": "武汉大学"},
            {"name": "肖某某"},
        ],
    }
    payload.update(overrides)
    return EntityNode(**payload)


def test_fallback_keywords_filter_schema_noise_and_dates():
    extractor = EntityPromptExtractor(use_llm=False)
    result = extractor.extract_prompt_for_entity(make_entity())

    keywords = result["keywords"]
    assert "新京报" in keywords
    assert any(item in keywords for item in ("报纸", "北京", "武汉大学"))
    assert "null" not in keywords
    assert "name" not in keywords
    assert "media_type" not in keywords
    assert "08" not in keywords
    assert "2025" not in keywords


def test_normalize_cleans_llm_noise_and_backfills_heuristic_keywords():
    extractor = EntityPromptExtractor(use_llm=False)
    entity = make_entity(
        name="涉事男生代理律师",
        labels=["Entity", "LegalProfessional"],
        summary="涉事男生代理律师围绕程序正义、听证程序和高校问责持续公开发声。",
        attributes={
            "case_role": "肖某某代理律师",
            "bar_association": "湖北省律师协会",
        },
        related_nodes=[{"name": "肖某某"}, {"name": "武汉大学"}],
    )

    result = extractor._normalize(
        entity,
        {
            "keywords": ["null", "name", "case_role", "08", "程序正义"],
            "topic_tags": ["2025", "高校问责", "bar_association"],
            "description": "",
            "semantic_prompt": "",
        },
    )

    keywords = result["keywords"]
    assert keywords[0] == "涉事男生代理律师"
    assert "程序正义" in keywords
    assert any(item in keywords for item in ("高校问责", "肖某某代理律师", "湖北省律师协会"))
    assert "null" not in keywords
    assert "name" not in keywords
    assert "case_role" not in keywords
    assert "08" not in keywords
    assert "2025" not in result["topic_tags"]

from app.application.simulation_population import SimulationPopulationBuilder
from app.application.zep_entity_reader import EntityNode


def make_entity(name: str, label: str, summary: str = "", attributes=None, related_nodes=None):
    return EntityNode(
        uuid=f"uuid_{name}",
        name=name,
        labels=["Entity", label],
        summary=summary,
        attributes=attributes or {},
        related_edges=[],
        related_nodes=related_nodes or [],
    )


def test_merge_alias_entities_merges_university_aliases():
    builder = SimulationPopulationBuilder()
    entities = [
        make_entity("武汉大学", "University", "学校官方主体"),
        make_entity("武大", "University", "武汉大学的简称"),
        make_entity("新京报", "MediaOutlet", "媒体节点"),
    ]

    merged, alias_map, groups = builder.merge_alias_entities(entities)

    names = [entity.name for entity in merged]
    assert "武汉大学" in names
    assert "武大" not in names
    assert alias_map["uuid_武大"] == "uuid_武汉大学"
    assert any(group["canonical_name"] == "武汉大学" for group in groups)


def test_add_ordinary_users_increases_non_elite_population():
    builder = SimulationPopulationBuilder()
    entities = [
        make_entity(f"媒体{i}", "MediaOutlet", "媒体报道")
        for i in range(10)
    ] + [
        make_entity(f"学校{i}", "University", "官方说明")
        for i in range(4)
    ] + [
        make_entity("当事学生", "Student", "学生视角")
    ]

    augmented, synthetic = builder.add_ordinary_users(
        entities,
        simulation_requirement="围绕校园舆情、程序正义和事实核查进行模拟",
        ordinary_ratio_target=0.5,
        max_synthetic_entities=12,
    )

    assert len(synthetic) > 0
    assert len(augmented) > len(entities)
    assert all(item.attributes.get("synthetic_population") for item in synthetic)

from app.application.simulation_config_generator import AgentActivityConfig, SimulationConfigGenerator


def test_parse_event_config_supports_comment_and_thread_events():
    generator = SimulationConfigGenerator()
    event_config = generator._parse_event_config(
        {
            "hot_topics": ["程序正义"],
            "initial_posts": [{"content": "官方通报", "poster_type": "University"}],
            "scheduled_events": [
                {
                    "event_type": "create_comment",
                    "trigger_hour": 3,
                    "content": "这条通报还是没回答核心问题",
                    "poster_type": "Student",
                    "target_poster_type": "University",
                },
                {
                    "event_type": "create_thread",
                    "trigger_hour": 5,
                    "poster_type": "MediaOutlet",
                    "root_content": "时间线整理",
                    "replies": ["补充1", "补充2"],
                },
            ],
        }
    )

    assert len(event_config.scheduled_events) == 2
    assert event_config.scheduled_events[0]["event_type"] == "create_comment"
    assert event_config.scheduled_events[0]["target_post_strategy"] == "latest_post_by_type"
    assert event_config.scheduled_events[1]["event_type"] == "create_thread"
    assert event_config.scheduled_events[1]["replies"] == ["补充1", "补充2"]


def test_assign_initial_post_agents_maps_comment_targets():
    generator = SimulationConfigGenerator()
    agents = [
        AgentActivityConfig(
            agent_id=0,
            entity_uuid="u-1",
            entity_name="武汉大学",
            entity_type="University",
        ),
        AgentActivityConfig(
            agent_id=1,
            entity_uuid="u-2",
            entity_name="围观学生01",
            entity_type="Student",
        ),
    ]
    event_config = generator._parse_event_config(
        {
            "initial_posts": [{"content": "学校说明", "poster_type": "University"}],
            "scheduled_events": [
                {
                    "event_type": "create_comment",
                    "trigger_hour": 2,
                    "content": "我不认同这个解释",
                    "poster_type": "Student",
                    "target_poster_type": "University",
                }
            ],
        }
    )

    updated = generator._assign_initial_post_agents(event_config, agents)
    comment_event = updated.scheduled_events[0]
    assert comment_event["poster_agent_id"] == 1
    assert comment_event["target_poster_agent_id"] == 0

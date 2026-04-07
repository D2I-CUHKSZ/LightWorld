from app.modules.simulation.memory_keywords import MemoryKeywordExtractor


class DummyTopologyRuntime:
    def __init__(self):
        self.agent_id_by_name = {
            "930老友记": 0,
            "武汉大学": 1,
            "景容饮冰": 2,
        }
        self.agent_entity_name = {
            0: "930老友记",
            1: "武汉大学",
            2: "景容饮冰",
        }
        self.agent_semantic_keywords = {
            0: {"时间线", "事实核查", "程序正义"},
            1: {"官方通报", "学生权益", "高校治理"},
            2: {"视频证据", "校园安全", "程序正义"},
        }
        self.profile_by_agent_id = {
            0: {"interested_topics": ["媒体伦理", "公共事件"]},
            1: {"interested_topics": ["高校治理", "学生权益"]},
            2: {"interested_topics": ["校园安全", "证据链"]},
        }

    def _normalize_agent_name(self, value):
        return str(value or "").strip().lower()


def test_memory_keywords_use_structured_sources():
    extractor = MemoryKeywordExtractor(
        config={"event_config": {"hot_topics": ["武大图书馆性骚扰事件", "程序正义"]}},
        topology_runtime=DummyTopologyRuntime(),
    )
    action = {
        "agent_id": 0,
        "agent_name": "930老友记",
        "action_type": "CREATE_COMMENT",
        "action_args": {
            "content": "程序正义不能只靠通报，景容饮冰提交的视频证据也应公开核验。",
            "post_author_name": "武汉大学",
            "target_user_name": "景容饮冰",
        },
    }

    keywords = extractor.extract(action, summary="CREATE_COMMENT | content:程序正义不能只靠通报", target_agent_ids=[1, 2], max_count=8)

    assert "930老友记" in keywords
    assert "武汉大学" in keywords
    assert "景容饮冰" in keywords
    assert any(item in keywords for item in ("程序正义", "视频证据", "高校治理", "校园安全"))


def test_memory_keywords_filter_noise_tokens():
    extractor = MemoryKeywordExtractor(
        config={"event_config": {"hot_topics": ["程序正义"]}},
        topology_runtime=DummyTopologyRuntime(),
    )
    action = {
        "agent_id": 0,
        "agent_name": "930老友记",
        "action_type": "QUOTE_POST",
        "action_args": {
            "content": "请看 https://example.edu/report/2025/xx号 ，post_content 字段不能当关键词。",
            "quote_content": "www.hkbu.edu.hk 的页面和 2025 年 00:17 的时间戳都不该进关键词。",
            "original_author_name": "武汉大学",
        },
    }

    keywords = extractor.extract(action, summary="QUOTE_POST | post_content:请看 https://example.edu/report/2025/xx号", target_agent_ids=[1], max_count=10)

    assert "www" not in keywords
    assert "hk" not in keywords
    assert "2025" not in keywords
    assert "post_content" not in keywords
    assert "xx号" not in keywords
    assert "930老友记" in keywords
    assert "武汉大学" in keywords

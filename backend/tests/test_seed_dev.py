from types import SimpleNamespace

from scripts.seed_dev import remove_trigger_generated_leads


class _FakeSession:
    def __init__(self) -> None:
        self.statement = None

    def execute(self, statement) -> None:
        self.statement = statement


def test_remove_trigger_generated_leads_targets_only_seed_conversation_ids():
    session = _FakeSession()
    convos = [
        SimpleNamespace(zalo_chat_id="zalo_conv_seed_0000"),
        SimpleNamespace(zalo_chat_id="zalo_conv_seed_0001"),
    ]

    remove_trigger_generated_leads(session, convos)

    compiled = session.statement.compile()
    assert "DELETE FROM leads" in str(compiled)
    assert list(compiled.params.values()) == [
        ["zalo_conv_seed_0000", "zalo_conv_seed_0001"]
    ]

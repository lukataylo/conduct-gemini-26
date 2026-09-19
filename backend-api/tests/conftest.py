from datetime import timedelta

import pytest

import main


def _reset() -> None:
    main.REQUESTS.clear()
    main.GRANTS.clear()
    main.ESCALATIONS.clear()
    main.AUDIT_LOG.clear()
    main.WATCH_URLS.clear()
    main.CONVERSATIONS.clear()
    main.STREAM_SUBSCRIBERS.clear()
    main.CLOCK_OFFSET = timedelta(0)
    main._CLOCK_OVERRIDE = None
    main.PARSE_IMPL = None
    main.AGENT_TURN_IMPL = None
    main.EXECUTE_ENQUEUE_IMPL = None
    main.COMPOSE_IMPL = None
    main.LIVE_POLICY = main.policy_engine.DEFAULT_POLICY.model_copy(deep=True)
    main.KNOWN_REQUESTERS.clear()
    main.KNOWN_REQUESTERS.update(
        {
            r.id: r
            for r in (
                main.usecase_demo.REQUESTER,
                main.usecase_demo.MANAGER,
                main.usecase_demo.FINANCE_OWNER,
            )
        }
    )


@pytest.fixture(autouse=True)
def reset_store():
    _reset()
    yield
    _reset()

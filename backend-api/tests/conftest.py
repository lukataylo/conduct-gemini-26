import pytest

import main


@pytest.fixture(autouse=True)
def reset_store():
    main.REQUESTS.clear()
    main.GRANTS.clear()
    main.ESCALATIONS.clear()
    main.AUDIT_LOG.clear()
    main.WATCH_URLS.clear()
    main.CONVERSATIONS.clear()
    main.PARSE_IMPL = None
    main.AGENT_TURN_IMPL = None
    main.EXECUTE_ENQUEUE_IMPL = None
    main.COMPOSE_IMPL = None
    main.LIVE_POLICY = main.policy_engine.DEFAULT_POLICY.model_copy(deep=True)
    yield
    main.REQUESTS.clear()
    main.GRANTS.clear()
    main.ESCALATIONS.clear()
    main.AUDIT_LOG.clear()
    main.WATCH_URLS.clear()
    main.CONVERSATIONS.clear()
    main.PARSE_IMPL = None
    main.AGENT_TURN_IMPL = None
    main.EXECUTE_ENQUEUE_IMPL = None
    main.COMPOSE_IMPL = None
    main.LIVE_POLICY = main.policy_engine.DEFAULT_POLICY.model_copy(deep=True)

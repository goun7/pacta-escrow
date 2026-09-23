"""Unit tests for Framework Integrations (AgentKit, LangChain, CrewAI, MCP)."""

from pacta.client import PactaEscrowClient
from pacta.integrations.agentkit import PactaEscrowActionProvider
from pacta.integrations.langchain_tool import PactaEscrowTool
from pacta.integrations.crewai_tool import CrewAIEscrowTool
from pacta.integrations.mcp_server import PactaMCPServer


def test_agentkit_action_provider():
    client = PactaEscrowClient()
    provider = PactaEscrowActionProvider(client)
    actions = provider.get_actions()

    assert "pacta_pay_with_escrow" in actions
    res = actions["pacta_pay_with_escrow"](
        seller_address="0xSeller",
        amount_usdc=5.0,
        output_payload={"data": 123}
    )
    assert res["success"] is True
    assert res["status"] == "SETTLED"


def test_langchain_tool():
    client = PactaEscrowClient()
    tool = PactaEscrowTool(client)
    res = tool._run(
        seller_address="0xSeller",
        amount_usdc=8.0,
        output_payload={"status": "completed"}
    )
    assert "SUCCESS" in res


def test_crewai_tool():
    client = PactaEscrowClient()
    tool = CrewAIEscrowTool(client)
    res = tool.run(
        peer_agent_address="0xPeer",
        task_bounty_usdc=12.0,
        result_payload={"analysis": "done"}
    )
    assert res["success"] is True
    assert res["status"] == "SETTLED"


def test_mcp_server_flow():
    client = PactaEscrowClient()
    server = PactaMCPServer(client)
    tools = server.get_tool_definitions()
    assert len(tools) == 3

    # Create escrow via MCP
    create_res = server.execute_tool("pacta_create_and_lock_escrow", {
        "seller_address": "0xMerchant",
        "amount_usdc": 25.0
    })
    job_id = create_res["job_id"]
    assert create_res["status"] == "ESCROW_LOCKED"

    # Submit and verify via MCP
    verify_res = server.execute_tool("pacta_submit_and_verify", {
        "job_id": job_id,
        "output_payload": {"ack": True}
    })
    from decimal import Decimal
    assert verify_res["fee_usdc"] == Decimal("0.187500")

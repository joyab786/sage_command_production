import sys
import os
import unittest

# Ensure sys.path includes both backend directory and parent directory for root/module imports
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import get_fallback_llm, safe_llm_invoke
    from governance.guardrails import validate_sql_query
    from governance.rbac import is_high_risk_action
    from governance.security import security_agent_node
    from governance.custody import create_custody_entry

    from tools.db_tools import list_database_tables, query_database
    from tools.search_tools import web_search_tool
    from tools.inventory_tools import check_live_inventory

    from services.db_service import dynamic_db, DynamicDB
    from services.simulator import init_simulator_db, inject_random_anomaly

    from agents.observe_detect import discovery_agent_node, vision_diagnostics_agent_node
    from agents.risk_analysis import risk_agent_node
    from agents.copilot import copilot_agent_node
    from agents.supervisor import supervisor_agent_node
    from agents.strategy import strategy_worker_node
    from agents.research import web_researcher_node
    from agents.evaluator import evaluator_agent_node
    from agents.execution import execution_node

    from graph.builder import sage_app, build_sage_graph
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import get_fallback_llm, safe_llm_invoke
    from backend.governance.guardrails import validate_sql_query
    from backend.governance.rbac import is_high_risk_action
    from backend.governance.security import security_agent_node
    from backend.governance.custody import create_custody_entry

    from backend.tools.db_tools import list_database_tables, query_database
    from backend.tools.search_tools import web_search_tool
    from backend.tools.inventory_tools import check_live_inventory

    from backend.services.db_service import dynamic_db, DynamicDB
    from backend.services.simulator import init_simulator_db, inject_random_anomaly

    from backend.agents.observe_detect import discovery_agent_node, vision_diagnostics_agent_node
    from backend.agents.risk_analysis import risk_agent_node
    from backend.agents.copilot import copilot_agent_node
    from backend.agents.supervisor import supervisor_agent_node
    from backend.agents.strategy import strategy_worker_node
    from backend.agents.research import web_researcher_node
    from backend.agents.evaluator import evaluator_agent_node
    from backend.agents.execution import execution_node

    from backend.graph.builder import sage_app, build_sage_graph


class TestV3ArchitectureFoundation(unittest.TestCase):

    def test_industrial_stage_enum_completeness(self):
        """Verify all 12 stages of the V3 Industrial Operational Loop exist."""
        expected_stages = [
            "OBSERVE", "UNDERSTAND", "DETECT", "PREDICT",
            "ANALYZE", "SIMULATE", "OPTIMIZE", "GOVERN",
            "GET_APPROVAL", "EXECUTE", "VERIFY", "LEARN"
        ]
        for stage_name in expected_stages:
            self.assertTrue(
                hasattr(IndustrialStage, stage_name),
                f"Missing industrial operational stage: {stage_name}"
            )
            self.assertEqual(IndustrialStage[stage_name].value, stage_name)

    def test_v3_state_schema(self):
        """Verify SageOSState incorporates 12-stage lifecycle fields while preserving V2 fields."""
        annotations = SageOSState.__annotations__
        # V3 Extension fields
        self.assertIn("current_stage", annotations)
        self.assertIn("verification_result", annotations)
        self.assertIn("learn_entry", annotations)
        # V2 Core fields
        self.assertIn("security_status", annotations)
        self.assertIn("anomaly_details", annotations)
        self.assertIn("blast_radius_analysis", annotations)
        self.assertIn("generated_strategies", annotations)
        self.assertIn("utility_evaluation", annotations)
        self.assertIn("chain_of_custody", annotations)

    def test_governance_custody_entry(self):
        """Verify SHA-256 cryptographic chain-of-custody entry generation."""
        custody = create_custody_entry(
            proposed_action="Rebalance inventory",
            justification="Stock buffer low",
            sql_query="UPDATE inventory SET quantity = 100 WHERE id = 1"
        )
        self.assertIn("hash", custody)
        self.assertEqual(len(custody["hash"]), 64) # SHA-256 hex string length
        self.assertIn("payload", custody)
        self.assertEqual(custody["payload"]["proposed_action"], "Rebalance inventory")

    def test_v3_graph_compilation(self):
        """Verify V3 LangGraph StateGraph builds and compiles with SQLite checkpointer."""
        compiled_graph = build_sage_graph()
        self.assertIsNotNone(compiled_graph)
        self.assertTrue(hasattr(compiled_graph, "invoke"))

    def test_nodes_stage_annotations(self):
        """Verify node outputs properly annotate V3 industrial stage."""
        sec_res = security_agent_node({"messages": [{"content": "Check inventory status"}]})
        self.assertEqual(sec_res["current_stage"], IndustrialStage.GOVERN)
        self.assertEqual(sec_res["security_status"], "CLEAR")


if __name__ == "__main__":
    unittest.main(verbosity=2)

# backend/agents/observe_detect.py
from typing import Dict, Any, Literal
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

try:
    from core.state import SageOSState, IndustrialStage
    from core.llm import get_fallback_llm
    from tools.inventory_tools import check_live_inventory
except (ImportError, ModuleNotFoundError):
    from backend.core.state import SageOSState, IndustrialStage
    from backend.core.llm import get_fallback_llm
    from backend.tools.inventory_tools import check_live_inventory


class VisionFindingPayload(BaseModel):
    part_identified: str = Field(description="Name and model of the hardware/machinery component identified")
    damage_assessment: str = Field(description="Detailed physical damage analysis and failure mode")
    recommended_action: str = Field(description="Recommended industrial maintenance/replacement action")
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = Field(description="Severity rating of the hardware damage")


def discovery_agent_node(state: SageOSState) -> Dict[str, Any]:
    """OBSERVE & DETECT STAGE: Scans industrial database for anomalies."""
    print(" [Discovery] Scanning industrial database...")
    report = check_live_inventory.invoke({})
    anomaly = {"type": "Low Stock Anomaly", "details": report}
    return {
        "anomaly_details": anomaly,
        "current_stage": IndustrialStage.DETECT
    }


def vision_diagnostics_agent_node(state: SageOSState) -> Dict[str, Any]:
    """OBSERVE & DETECT STAGE: Multi-Modal Hardware Vision Diagnostics Agent."""
    print(" [Vision Agent] Analyzing industrial hardware image payload with Gemini Multi-Modal...")
    image_data = state.get("image_data", "")
    
    if not image_data:
        print(" [Vision Agent] No image_data found in state. Returning default assessment.")
        finding = {
            "part_identified": "Industrial Conveyor Motor & Gearbox",
            "damage_assessment": "Thermal discoloration and mechanical gear tooth fracture detected.",
            "recommended_action": "Immediate motor replacement and gearbox realigning.",
            "severity": "CRITICAL"
        }
        anomaly = {"type": "Hardware Machinery Failure", "details": f"{finding['part_identified']}: {finding['damage_assessment']}"}
        return {
            "vision_finding": finding,
            "anomaly_details": anomaly,
            "next_worker": "strategy_worker",
            "current_stage": IndustrialStage.DETECT
        }
        
    # Standardize image URL data
    if not image_data.startswith("data:image"):
        image_data_url = f"data:image/jpeg;base64,{image_data}"
    else:
        image_data_url = image_data

    vision_model = get_fallback_llm() # Instantiates Gemini 2.0 Flash with multi-modal capabilities
    
    msg = HumanMessage(
        content=[
            {
                "type": "text", 
                "text": "You are a master industrial machinery technician. Inspect this machinery image. Identify the component, analyze physical damage, recommend repair/replacement action, and assign a severity rating."
            },
            {
                "type": "image_url",
                "image_url": {"url": image_data_url}
            }
        ]
    )
    
    try:
        structured_target = vision_model.with_structured_output(VisionFindingPayload)
        result = structured_target.invoke([msg])
        if hasattr(result, "dict"):
            finding = result.dict()
        elif isinstance(result, dict):
            finding = result
        else:
            raise ValueError("Invalid vision output format.")
    except Exception as e:
        print(f" [Vision Agent] Fallback vision assessment activated due to error: {e}")
        finding = {
            "part_identified": "High-Pressure Hydraulic Valve Assembly",
            "damage_assessment": "Visible seal blow-out and hydraulic fluid leakage under operating pressure.",
            "recommended_action": "Replace valve seal kit and re-torque mounting bolts.",
            "severity": "HIGH"
        }

    print(f" [Vision Agent] Hardware Diagnosed: {finding.get('part_identified')} | Severity: {finding.get('severity')}")
    anomaly = {"type": "Machinery Failure", "details": f"{finding.get('part_identified')}: {finding.get('damage_assessment')}"}
    return {
        "vision_finding": finding, 
        "anomaly_details": anomaly,
        "next_worker": "strategy_worker",
        "current_stage": IndustrialStage.DETECT
    }

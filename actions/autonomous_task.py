"""
autonomous_task.py — SAM Overnight Project Orchestrator
Spawns background autonomous agents that execute multi-step projects across tools,
checkpointing every step to survive restarts.
"""
from __future__ import annotations

import importlib
import threading
from typing import Optional

from core.autonomous_agent import AutonomousAgent
from core.brain_router import call_brain


def autonomous_task(parameters: dict = None, **kwargs) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    goal = (
        params.get("project")
        or params.get("goal")
        or params.get("task")
        or params.get("name")
        or params.get("description")
        or "Autonomous project"
    ).strip()
    
    agent = AutonomousAgent(goal=goal)
    
    def executor(step: dict) -> str:
        tool_name = step.get("tool", "dev_agent")
        args_dict = step.get("params") or step.get("args") or {}
        if not isinstance(args_dict, dict):
            args_dict = {}
            
        # Ensure dev_agent has context if step didn't set params
        if tool_name == "dev_agent" and not args_dict.get("goal"):
            args_dict["goal"] = step.get("description", goal)
            
        try:
            mod = importlib.import_module(f"actions.{tool_name}")
            func = getattr(mod, tool_name)
            return func(args_dict)
        except Exception as e:
            raise RuntimeError(f"Step execution failed in {tool_name}: {e}")

    def run_agent():
        try:
            print(f"[Autonomous] Task {agent.task_id} planning goal: {goal}")
            agent.plan(call_brain)
            print(f"[Autonomous] Task {agent.task_id} generated {len(agent.steps)} steps. Executing...")
            summary = agent.run(step_executor=executor)
            print(f"[Autonomous] Task {agent.task_id} complete: {summary}")
            
            # Auto-call / notify user's cell phone on completion
            try:
                from actions.phone_notifier import call_user_phone, _load_config
                cfg = _load_config()
                if cfg.get("user_phone_number"):
                    call_msg = (
                        f"Good day sir. This is SAM calling with an update on your overnight project: "
                        f"'{goal}'. The autonomous build has finished. "
                        f"{summary.get('completed', 0)} out of {summary.get('total', 0)} milestones were executed successfully."
                    )
                    call_user_phone(message=call_msg)
            except Exception as notify_err:
                print(f"[Autonomous] Phone update warning: {notify_err}")
                
        except Exception as e:
            print(f"[Autonomous] Task {agent.task_id} error: {e}")

    # Launch background thread
    t = threading.Thread(target=run_agent, daemon=True, name=f"Agent-{agent.task_id}")
    t.start()
    
    return (
        f"Overnight autonomous project initiated with ID '{agent.task_id}', sir. "
        f"Goal: '{goal}'. The agent is planning milestones and executing them in the background. "
        f"You can query progress anytime with 'background monitor'."
    )

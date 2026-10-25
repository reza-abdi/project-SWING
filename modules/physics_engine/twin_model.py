"""Factories and state for the IEEE transmission-grid digital twin."""

import copy

import pandapower as pp
import pandapower.networks as networks

from modules.physics_engine.scenario_engine import (
    ramp_down_renewables,
    simulate_generator_trip,
    simulate_weather_event,
)
from modules.physics_engine.grid_metrics import (
    get_electrical_metrics,
    get_observation_vector,
    get_resilience_index,
    get_security_metrics,
    get_topology_metrics,
)


class TwinModel:
    """Create an isolated pandapower network for a supported IEEE case."""

    def __init__(self, grid_type: str = "39") -> None:
        if grid_type == "39":
            self.net = networks.case39()
        elif grid_type == "118":
            self.net = networks.case118()
        else:
            raise ValueError("Unsupported grid type. Choose '39' or '118'.")
        self.grid_type = grid_type

        # Anchor absolute stress-test changes to the untouched IEEE case values.
        self.baseline_load_p_mw = self.net.load["p_mw"].copy()
        self.baseline_load_q_mvar = self.net.load["q_mvar"].copy()
        self.baseline_max_i_ka = self.net.line["max_i_ka"].copy()

        self.asset_registry = {
            "transformers": {
                index: {"fault_class": "NORMAL", "rul_days": 100.0, "dga_score": 0.0}
                for index in self.net.trafo.index
            },
            "generators": {
                index: {"fault_class": "NORMAL", "rul_days": 100.0, "vibration_amp": 0.0}
                for index in self.net.gen.index
            },
            "circuit_breakers": {
                index: {"fault_class": "NORMAL", "rul_days": 100.0, "tccs_delay_ms": 0.0}
                for index in self.net.line.index
            },
            "relays": {
                index: {"fault_class": "NORMAL", "logic_integrity": 100.0}
                for index in self.net.bus.index
            },
        }
        self.simulation_status = "NOT_STARTED"
        self.current_scenario = "Baseline"
        self.event_history: list[str] = []
        self.current_state: dict[str, object] | None = None
        self.previous_state: dict[str, object] | None = None
        self.time_step = 0
        self.state_history: dict[int, dict[str, object]] = {}

    def get_current_state(self) -> dict[str, object]:
        """Return a readable snapshot of the current network measurements."""
        summary: dict[str, object] = {
            "grid_type": self.grid_type,
            "simulation_status": self.simulation_status,
            "current_scenario": self.current_scenario,
            "last_event": self.event_history[-1] if self.event_history else "None",
            "asset_health": self.asset_registry,
            "ai_observation": get_observation_vector(self.net),
        }
        summary.update(get_topology_metrics(self.net))
        summary.update(get_electrical_metrics(self.net))
        summary.update(get_security_metrics(self.net))
        summary.update(get_resilience_index(self.net))
        return summary

    def update_state(
        self,
        simulation_summary: dict[str, object],
        simulation_status: str,
        event: str,
    ) -> dict[str, object]:
        """Advance the grid timeline and retain independent state snapshots."""
        self.previous_state = copy.deepcopy(self.current_state)
        self.time_step += 1
        self.simulation_status = simulation_status
        self.event_history.append(event)

        state = copy.deepcopy(simulation_summary)
        state.update(
            {
                "simulation_status": simulation_status,
                "last_event": event,
                "time_step": self.time_step,
                "event_history": copy.deepcopy(self.event_history),
            }
        )
        self.current_state = state
        self.state_history[self.time_step] = copy.deepcopy(state)
        return self.current_state

    def run_baseline_simulation(self) -> dict[str, object]:
        """Run Newton-Raphson power flow and return a state or failure snapshot."""
        self.simulation_status = "RUNNING"
        self.event_history.append("Baseline Simulation Started")
        try:
            pp.runpp(self.net, algorithm="nr")
        except pp.LoadflowNotConverged:
            event = "Baseline Simulation Failed"
            summary: dict[str, object] = {
                "grid_type": self.grid_type,
                "current_scenario": self.current_scenario,
                "grid_resilience_index": 0.0,
                "collapsed": True,
            }
            return self.update_state(summary, "FAILED", event)

        event = "Baseline Simulation Completed"
        summary = self.get_current_state()
        return self.update_state(summary, "COMPLETED", event)

    def trip_generator(self, gen_id: int, trip_type: str = "FORCED_OUTAGE") -> str:
        """Trip a generator, update its asset record, and rerun AC power flow."""
        self.net, self.asset_registry = simulate_generator_trip(
            self.net, self.asset_registry, gen_id, trip_type
        )
        event = f"Generator {gen_id} Tripped ({trip_type})"
        self.current_scenario = event
        self.simulation_status = "RUNNING"
        try:
            pp.runpp(self.net, algorithm="nr")
        except pp.LoadflowNotConverged:
            self.update_state(self.get_current_state(), "FAILED", event)
        else:
            self.update_state(self.get_current_state(), "COMPLETED", event)
        return self.simulation_status

    def apply_weather_event(self, event_type: str = "HEATWAVE", severity: float = 1.0) -> str:
        """Apply a weather stress event, then rerun power flow and track its status."""
        self.net, self.asset_registry = simulate_weather_event(
            self.net, self.asset_registry, event_type, severity
        )
        event = f"Weather Event: {event_type} ({severity}x)"
        self.current_scenario = event
        self.simulation_status = "RUNNING"
        try:
            pp.runpp(self.net, algorithm="nr")
        except pp.LoadflowNotConverged:
            self.update_state(self.get_current_state(), "FAILED", event)
        else:
            self.update_state(self.get_current_state(), "COMPLETED", event)
        return self.simulation_status

    def ramp_renewables(self, ramp_percent: float, renewable_gen_ids: list[int] | None = None) -> str:
        """Curtail selected generator output and rerun power flow."""
        self.net = ramp_down_renewables(self.net, ramp_percent, renewable_gen_ids)
        event = f"Renewables ramped down by {float(ramp_percent):g}%"
        self.current_scenario = event
        self.simulation_status = "RUNNING"
        try:
            pp.runpp(self.net, algorithm="nr")
        except pp.LoadflowNotConverged:
            self.update_state(self.get_current_state(), "FAILED", event)
        else:
            self.update_state(self.get_current_state(), "COMPLETED", event)
        return self.simulation_status

    def trip_line(self, line_id: int) -> str:
        """Take a valid transmission line out of service and solve the grid."""
        if line_id not in self.net.line.index:
            raise ValueError(f"Line {line_id} not found in network.")

        self.net.line.at[line_id, "in_service"] = False
        event = f"Line {line_id} Tripped"
        self.current_scenario = event
        self.simulation_status = "RUNNING"
        try:
            pp.runpp(self.net, algorithm="nr")
        except pp.LoadflowNotConverged:
            self.update_state(self.get_current_state(), "FAILED", event)
        else:
            self.update_state(self.get_current_state(), "COMPLETED", event)
        return self.simulation_status

    def restore_line(self, line_id: int) -> str:
        """Return a valid transmission line to service and solve the grid."""
        if line_id not in self.net.line.index:
            raise ValueError(f"Line {line_id} not found in network.")

        self.net.line.at[line_id, "in_service"] = True
        event = f"Line {line_id} Restored"
        self.current_scenario = event
        self.simulation_status = "RUNNING"
        try:
            pp.runpp(self.net, algorithm="nr")
        except pp.LoadflowNotConverged:
            self.update_state(self.get_current_state(), "FAILED", event)
        else:
            self.update_state(self.get_current_state(), "COMPLETED", event)
        return self.simulation_status

    def inject_line_fault(self, line_index: int) -> str:
        """Compatibility alias for the original line fault operation."""
        return self.trip_line(line_index)

"""Factories and state for the IEEE transmission-grid digital twin."""

import pandapower as pp
import pandapower.networks as networks

from modules.physics_engine.scenario_engine import simulate_generator_trip


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

    def trip_generator(self, gen_id: int, trip_type: str = "FORCED_OUTAGE") -> str:
        """Trip a generator, update its asset record, and rerun AC power flow."""
        self.net, self.asset_registry = simulate_generator_trip(
            self.net, self.asset_registry, gen_id, trip_type
        )
        event = f"Generator {gen_id} Tripped ({trip_type})"
        self.current_scenario = event
        self.event_history.append(event)
        self.simulation_status = "RUNNING"
        try:
            pp.runpp(self.net, algorithm="nr")
        except pp.LoadflowNotConverged:
            self.simulation_status = "FAILED"
            self.event_history.append("Simulation Failed")
        else:
            self.simulation_status = "COMPLETED"
        return self.simulation_status

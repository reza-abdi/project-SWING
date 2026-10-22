"""Scenario transformations for the pandapower digital twin."""

import math
import random


def apply_load_multiplier(net, multiplier: float):
    """Scale active and reactive load on every bus in place."""
    net.load["p_mw"] = net.load["p_mw"] * multiplier
    net.load["q_mvar"] = net.load["q_mvar"] * multiplier
    return net


def derate_lines(net, derate_multiplier: float):
    """Reduce line current capacity with a finite positive multiplier."""
    if not math.isfinite(derate_multiplier) or derate_multiplier <= 0:
        raise ValueError("derate_multiplier must be a finite positive number")
    net.line["max_i_ka"] = net.line["max_i_ka"] * derate_multiplier
    return net


def simulate_transformer_aging(asset_registry, trafo_id: int, severity: float = 1.0):
    """Increase transformer gas score and reduce useful life for one time step."""
    if trafo_id in asset_registry["transformers"]:
        transformer = asset_registry["transformers"][trafo_id]
        transformer["dga_score"] += random.uniform(0.5, 2.0) * severity
        transformer["rul_days"] -= random.uniform(1.0, 3.0) * severity

        if transformer["dga_score"] > 80.0:
            transformer["fault_class"] = "HIGH_ENERGY_ARCING"
        elif transformer["dga_score"] > 50.0:
            transformer["fault_class"] = "THERMAL_FAULT"
        transformer["rul_days"] = max(0.0, transformer["rul_days"])
    return asset_registry


def simulate_generator_wear(asset_registry, gen_id: int, wear_rate: float = 1.0):
    """Increase generator vibration and reduce useful life for one time step."""
    if gen_id in asset_registry["generators"]:
        generator = asset_registry["generators"][gen_id]
        generator["vibration_amp"] += random.uniform(0.1, 0.5) * wear_rate
        generator["rul_days"] -= random.uniform(0.8, 2.5) * wear_rate

        if generator["vibration_amp"] > 7.5:
            generator["fault_class"] = "CRITICAL_UNBALANCE"
        elif generator["vibration_amp"] > 4.5:
            generator["fault_class"] = "BEARING_WEAR"
        generator["rul_days"] = max(0.0, generator["rul_days"])
    return asset_registry


def simulate_breaker_degradation(asset_registry, breaker_id: int, friction_factor: float = 1.0):
    """Increase breaker trip-coil delay and reduce its remaining useful life."""
    if breaker_id in asset_registry["circuit_breakers"]:
        breaker = asset_registry["circuit_breakers"][breaker_id]
        breaker["tccs_delay_ms"] += random.uniform(1.0, 4.0) * friction_factor
        breaker["rul_days"] -= random.uniform(0.5, 2.0) * friction_factor

        if breaker["tccs_delay_ms"] > 50.0:
            breaker["fault_class"] = "MECHANICAL_JAM"
        elif breaker["tccs_delay_ms"] > 30.0:
            breaker["fault_class"] = "SLUGGISH_OPERATION"
        breaker["rul_days"] = max(0.0, breaker["rul_days"])
    return asset_registry


def simulate_relay_degradation(asset_registry, relay_id: int, noise_factor: float = 1.0):
    """Reduce relay logic integrity and map it to the source fault labels."""
    if relay_id in asset_registry["relays"]:
        relay = asset_registry["relays"][relay_id]
        relay["logic_integrity"] -= random.uniform(0.5, 2.0) * noise_factor

        if relay["logic_integrity"] < 50.0:
            relay["fault_class"] = "CRITICAL_LOGIC_FAILURE"
        elif relay["logic_integrity"] < 80.0:
            relay["fault_class"] = "MINOR_CALIBRATION_ERROR"
        relay["logic_integrity"] = max(0.0, relay["logic_integrity"])
    return asset_registry


def simulate_generator_trip(net, asset_registry, gen_id: int, trip_type: str = "FORCED_OUTAGE"):
    """Take a generator out of service and record its resulting asset state."""
    if gen_id not in net.gen.index:
        raise ValueError(f"Generator {gen_id} not found in network.")

    net.gen.at[gen_id, "in_service"] = False
    if gen_id in asset_registry["generators"]:
        generator = asset_registry["generators"][gen_id]
        generator["fault_class"] = trip_type
        generator["rul_days"] = 0.0
    return net, asset_registry


def simulate_weather_event(net, asset_registry, event_type: str = "HEATWAVE", severity: float = 1.0):
    """Apply heatwave, storm, or cold-snap load and asset stress."""
    if event_type == "HEATWAVE":
        derate_factor = max(0.5, 1.0 - 0.10 * severity)
        net = derate_lines(net, derate_factor)
        for trafo_id in asset_registry["transformers"]:
            simulate_transformer_aging(asset_registry, trafo_id, severity=1.5 * severity)
    elif event_type == "STORM":
        derate_factor = max(0.3, 1.0 - 0.25 * severity)
        net = derate_lines(net, derate_factor)
        for breaker_id in asset_registry["circuit_breakers"]:
            simulate_breaker_degradation(asset_registry, breaker_id, friction_factor=2.0 * severity)
    elif event_type == "COLD_SNAP":
        net = apply_load_multiplier(net, multiplier=1.0 + 0.20 * severity)
    else:
        raise ValueError(f"Unknown weather event_type: {event_type!r}. Use HEATWAVE, STORM, or COLD_SNAP.")
    return net, asset_registry

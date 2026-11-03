import csv
import json
import sqlite3

from scripts.evaluate_metrics import (
    evaluate_physics,
    evaluate_rag,
    evaluate_rl_logs,
    regression_metrics,
)


def test_empty_physics_events_return_empty_safe_report(tmp_path):
    database = tmp_path / 'events.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE events (event_type TEXT, payload TEXT)')
    report = evaluate_physics(database)
    assert report['total'] == 0
    assert report['physics_valid_fraction'] is None
    assert report['average_gri_improvement'] is None


def test_reward_csvs_summarize_convergence_and_reward_deciles(tmp_path):
    for grid in ('39', '118'):
        for action in ('shed_load', 'redispatch_gen'):
            with (tmp_path / f'rl_optimizer_{action}_{grid}_rewards.csv').open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=['reward', 'converged'])
                writer.writeheader()
                writer.writerows([
                    {'reward': -4, 'converged': 'True'},
                    {'reward': 2, 'converged': 'False'},
                    {'reward': 6, 'converged': 'True'},
                ])
    report = evaluate_rl_logs(tmp_path)
    assert report['39/shed_load']['convergence_fraction'] == 2 / 3
    assert report['39/shed_load']['first_decile_mean_reward'] == -4
    assert report['39/shed_load']['last_decile_mean_reward'] == 6


def test_quantile_regression_metrics_are_finite_and_skip_zero_mape():
    metrics = regression_metrics([0, 10, 20], [1, 12, 18])
    assert metrics['n'] == 3
    assert metrics['nrmse'] > 0
    assert metrics['nmae'] > 0
    assert metrics['mape'] == 0.2


def test_physics_report_handles_mixed_valid_invalid_and_zero_gri(tmp_path):
    database = tmp_path / 'events.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE events (event_type TEXT, payload TEXT)')
        payloads = [
            {'action': {'action_type': 'SHED_LOAD'}, 'validation': {'valid': True, 'gri_improvement': 0.0}},
            {'action': {'action_type': 'REDISPATCH_GEN'}, 'validation': {'valid': False, 'gri_improvement': -2.0}},
        ]
        connection.executemany('INSERT INTO events VALUES (?, ?)', [
            ('PROPOSAL_EXECUTED', json.dumps(payload)) for payload in payloads
        ])
    report = evaluate_physics(database)
    assert report['total'] == 2
    assert report['physics_valid_fraction'] == 0.5
    assert report['action_distribution'] == {'SHED_LOAD': 1, 'REDISPATCH_GEN': 1}
    assert report['average_gri_improvement'] == -1.0


def test_rag_without_event_database_returns_empty_report(tmp_path):
    report = evaluate_rag(tmp_path / 'missing.sqlite')
    assert report['evaluated'] == 0
    assert report['results'] == []

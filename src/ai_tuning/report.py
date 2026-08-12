"""週次AIチューニング結果のTelegramレポート用メッセージ組み立て。"""

from __future__ import annotations

from src.ai_tuning.apply import ProcessOutcome


def build_weekly_tuning_report(outcomes: list[ProcessOutcome]) -> str:
    """buy/sell_surge_threshold等、複数パラメータの結果を1通のメッセージにまとめる。"""
    sections = ["[週次AIチューニング] 結果報告"]

    for outcome in outcomes:
        lines = [f"■ {outcome.parameter_name} (mode: {outcome.mode})"]
        lines.append(f"  適用: {'あり' if outcome.applied else 'なし'}")
        if outcome.applied and outcome.old_value != outcome.new_value:
            lines.append(f"  変更: {outcome.old_value} → {outcome.new_value}")
        if outcome.reason:
            lines.append(f"  reason: {outcome.reason}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)

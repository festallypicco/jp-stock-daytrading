"""週次AIチューニングのLLM3役討議（Proposer→Skeptic→Moderator）用プロンプト構築。"""

from __future__ import annotations

from src.ai_tuning.summary import TuningReviewSummary, WindowStats


def _format_window(window: WindowStats) -> str:
    win_rate_str = f"{window.win_rate:.1%}" if window.win_rate is not None else "N/A"
    avg_pnl_str = f"{window.avg_pnl:.1f}" if window.avg_pnl is not None else "N/A"
    return (
        f"- {window.window_name}（{window.period_days}日窓、実カバー日数{window.actual_days_covered}日）: "
        f"トレード数={window.trade_count}, 勝率={win_rate_str}, 平均pnl={avg_pnl_str}"
    )


def _format_summary(summary: TuningReviewSummary) -> str:
    windows_text = "\n".join(_format_window(summary.windows[name]) for name in summary.windows)
    confidence_note = (
        "\n注意: 現在のconfidenceは'insufficient'です。データが少ないため、慎重に判断してください。"
        if summary.confidence == "insufficient"
        else ""
    )
    return (
        f"パラメータ名: {summary.parameter_name}\n"
        f"現在値: {summary.current_value}\n"
        f"ハードリミット: {summary.hard_limit_min} 〜 {summary.hard_limit_max}\n"
        f"現在値適用以降のトレード数: {summary.trade_count_since_effective}\n"
        f"データ信頼度(confidence): {summary.confidence}{confidence_note}\n"
        f"各ウィンドウの集計:\n{windows_text}"
    )


def build_proposer_prompt(summary: TuningReviewSummary) -> str:
    return (
        "あなたは日本株デイトレード自動売買システムのパラメータチューニング担当（Proposer）です。\n"
        "以下のトレード実績データに基づき、パラメータの変更が必要か検討し、"
        "変更が必要であれば具体的な提案値とその根拠を述べてください。\n"
        "変更が不要と判断した場合は、現在値を維持する提案としてその理由を述べてください。\n\n"
        f"{_format_summary(summary)}"
    )


def build_skeptic_prompt(summary: TuningReviewSummary, proposer_output: str) -> str:
    return (
        "あなたは日本株デイトレード自動売買システムのパラメータチューニング担当（Skeptic）です。\n"
        "以下はProposerによる提案です。データの十分性・過剰適合のリスク・"
        "提案根拠の妥当性を批判的に検証し、懸念点を具体的に指摘してください。\n\n"
        f"{_format_summary(summary)}\n\n"
        f"[Proposerの提案]\n{proposer_output}"
    )


def build_moderator_prompt(
    summary: TuningReviewSummary, proposer_output: str, skeptic_output: str
) -> str:
    return (
        "あなたは日本株デイトレード自動売買システムのパラメータチューニング担当（Moderator）です。\n"
        "ProposerとSkepticの議論を踏まえ、最終的な提案値を1つ決定してください。\n\n"
        f"{_format_summary(summary)}\n\n"
        f"[Proposerの提案]\n{proposer_output}\n\n"
        f"[Skepticの指摘]\n{skeptic_output}\n\n"
        "出力形式についての厳格な指示:\n"
        "JSON以外の文字列（説明文、コードブロックのバッククォート、前置き等）を"
        "一切含めず、以下の2つのキーのみを持つJSONオブジェクト1個だけを出力してください。\n"
        '{"proposed_value": <float>, "reasoning": "<短い日本語での根拠>"}'
    )

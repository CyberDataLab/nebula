import json
import logging
import os

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from nebula.core.utils.nebulalogger_tensorboard import NebulaTensorBoardLogger


logging.basicConfig(level=logging.INFO)

PILLAR_CONFIGS = [
    ("robustness", "#F8D3DF", -0.4, (10, 6), "Robustness"),
    ("privacy", "#DA8D8B", -0.2, (10, 6), "Privacy"),
    ("fairness", "#DDDDDD", -0.4, (10, 6), "Fairness"),
    ("explainability", "#FCEFC3", -0.4, (10, 6), "Explainability"),
    ("accountability", "#8FAADC", -0.3, (10, 6), "Accountability"),
    ("architectural_soundness", "#DBB9FA", -0.3, (10, 6), "Architectural Soundness"),
    ("sustainability", "#BBFDAF", -0.5, (12, 8), "Sustainability"),
]
TRUST_SCORE_COLOR = "#BF9000"


class Graphics:
    def __init__(
        self,
        scenario_start_time,
        scenario_name,
        participant_id=None,
    ):
        # Configure the TensorBoard logger used to store trustworthiness figures.
        self.scenario_start_time = scenario_start_time
        self.scenario_name = scenario_name
        log_dir = os.path.join(os.environ["NEBULA_LOGS_DIR"], scenario_name)
        version = "trust" if participant_id is None else f"trust_{participant_id}"
        self.nebulalogger = NebulaTensorBoardLogger(
            scenario_start_time,
            f"{log_dir}",
            name="metrics",
            version=version,
            log_graph=True,
        )

    def _trustworthiness_dir(self):
        # Return the directory where trustworthiness JSON reports are stored.
        return os.path.join(os.environ.get("NEBULA_LOGS_DIR"), self.scenario_name, "trustworthiness")

    def _trust_report_path(self, file_name):
        # Build the absolute path for one trustworthiness report file.
        return os.path.join(self._trustworthiness_dir(), file_name)

    def _load_trust_results(self, results_file):
        # Load one trustworthiness JSON report from disk.
        with open(results_file, "r") as f:
            return json.load(f)

    def _log_report_from_file(self, results_file, tag_root, all_pillars_tag, label_suffix=""):
        # Load a report and log all figures generated from it.
        results = self._load_trust_results(results_file)
        self._log_trust_report(results, tag_root, all_pillars_tag, label_suffix=label_suffix)

    def _format_report_dataframe(self, df, pillar):
        # Keep one pillar and format metric/notion names for plot labels.
        filtered_df = df[df["Pillar"] == pillar].copy()

        filtered_df.loc[:, "Metric"] = filtered_df["Metric"].astype(str).str.replace("_", " ")
        filtered_df.loc[:, "Metric"] = filtered_df["Metric"].apply(lambda x: str(x).title())

        filtered_df.loc[:, "Notion"] = filtered_df["Notion"].astype(str).str.replace("_", " ")
        filtered_df.loc[:, "Notion"] = filtered_df["Notion"].apply(lambda x: str(x).title())
        return filtered_df

    def _notion_ranges(self, filtered_df):
        # Compute the x-axis range occupied by each notion in a pillar plot.
        ranges = []
        x_positions = range(len(filtered_df))
        seen_notions = set()

        for i, notion in enumerate(filtered_df["Notion"]):
            if notion in seen_notions:
                continue

            metrics_for_notion = filtered_df[filtered_df["Notion"] == notion]["Metric"]
            start_pos = x_positions[i]
            end_pos = x_positions[i + len(metrics_for_notion) - 1]
            notion_x_pos = (start_pos + end_pos) / 2

            ranges.append((notion, start_pos, end_pos, notion_x_pos))
            seen_notions.add(notion)

        return ranges

    def _draw_notion_score_lines(self, ax, filtered_df):
        # Draw dashed horizontal notion score lines over the metrics they group.
        x_count = len(filtered_df)
        if x_count == 0:
            return

        for notion, start_pos, end_pos, notion_x_pos in self._notion_ranges(filtered_df):
            notion_score = filtered_df[filtered_df["Notion"] == notion]["Notion Score"].iloc[0]
            ax.axhline(
                notion_score,
                ls="--",
                color="black",
                lw=0.5,
                xmin=start_pos / x_count,
                xmax=(end_pos + 1) / x_count,
            )
            ax.text(
                notion_x_pos,
                notion_score + 0.01,
                f"{notion_score:.2f}",
                ha="center",
                va="bottom",
                fontsize=10,
                color="black",
            )

    def _draw_notion_labels(self, ax, filtered_df, notion_y_pos):
        # Add notion labels below the metric labels.
        for notion, _, _, notion_x_pos in self._notion_ranges(filtered_df):
            ax.text(
                notion_x_pos,
                notion_y_pos,
                notion,
                ha="center",
                va="center",
                fontsize=10,
                color="black",
            )

    def _draw_metric_score_labels(self, ax, filtered_df):
        # Add numeric metric scores above each bar.
        for i, value in enumerate(filtered_df["Metric Score"]):
            ax.text(i, value + 0.01, f"{value:.2f}", ha="center", va="bottom", fontsize=10, color="black")

    def _log_pillar_figure(self, df, pillar, color, tag_root, notion_y_pos=-0.4, figsize=(10, 6)):
        # Generate and log the metric/notion bar chart for one pillar.
        filtered_df = self._format_report_dataframe(df, pillar)
        unique_notion_count = filtered_df["Notion"].nunique()
        palette = [color] * unique_notion_count

        plt.figure(figsize=figsize)
        ax = sns.barplot(data=filtered_df, x="Metric", y="Metric Score", hue="Notion", palette=palette, dodge=False)

        x_positions = range(len(filtered_df))
        ax.set_xticks(x_positions)
        ax.set_xticklabels(filtered_df["Metric"], rotation=45, ha="right", fontsize=10)

        self._draw_notion_score_lines(ax, filtered_df)
        self._draw_notion_labels(ax, filtered_df, notion_y_pos)
        self._draw_metric_score_labels(ax, filtered_df)

        plt.xlabel("Metrics and notions", labelpad=35)
        plt.ylabel("Score")
        plt.title(f"Metrics and notion scores for the {pillar} pillar")

        if ax.legend_ is not None:
            ax.legend_.remove()

        plt.tight_layout()

        self.nebulalogger.log_figure(ax.get_figure(), 0, f"{tag_root}/Pillar/{pillar}")
        plt.close()

    def _trust_report_rows(self, results):
        # Flatten the nested trust report into rows that pandas can plot.
        rows = []
        for pillar in results["pillars"]:
            for pillar_name, pillar_value in pillar.items():
                if "notions" not in pillar_value:
                    continue

                for notion in pillar_value["notions"]:
                    for notion_name, notion_value in notion.items():
                        for metric in notion_value["metrics"]:
                            for metric_name, metric_value in metric.items():
                                rows.append(
                                    {
                                        "Pillar": pillar_name,
                                        "Notion": notion_name,
                                        "Notion Score": notion_value["score"],
                                        "Metric": metric_name,
                                        "Metric Score": metric_value["score"],
                                    }
                                )
        return rows

    def _build_trust_report_dataframe(self, results):
        # Convert flattened report rows into a DataFrame for pillar plots.
        return pd.DataFrame(
            self._trust_report_rows(results),
            columns=["Pillar", "Notion", "Notion Score", "Metric", "Metric Score"],
        )

    def _pillar_scores(self, results):
        # Read pillar scores in the same order used by the all-pillars chart.
        categories = [config[0] for config in PILLAR_CONFIGS]
        scores = [results["pillars"][i][category]["score"] for i, category in enumerate(categories)]
        return categories, scores

    def _pillar_labels(self, label_suffix):
        # Build human-readable labels for the all-pillars chart.
        labels = [config[4] for config in PILLAR_CONFIGS]
        labels.append("Trust Score")
        return [f"{label}{label_suffix}" for label in labels]

    def _log_all_pillars_figure(self, results, all_pillars_tag, label_suffix=""):
        # Generate and log the summary chart with every pillar and the final trust score.
        categories, scores = self._pillar_scores(results)
        categories.append("trust_score")
        scores.append(results["trust_score"])

        palette = [config[1] for config in PILLAR_CONFIGS]
        palette.append(TRUST_SCORE_COLOR)

        plt.figure(figsize=(10, 8))
        ax = sns.barplot(x=categories, y=scores, palette=palette, hue=categories, legend=False)
        ax.set_xlabel("Pillar")
        ax.set_ylabel("Score")
        ax.set_title("Pillars and trust scores")

        for i, value in enumerate(scores):
            ax.text(i, value + 0.01, f"{value:.2f}", ha="center", va="bottom", fontsize=10)

        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels(self._pillar_labels(label_suffix), rotation=45)

        self.nebulalogger.log_figure(ax.get_figure(), 0, all_pillars_tag)
        plt.close()

    def _log_trust_report(self, results, tag_root, all_pillars_tag, label_suffix=""):
        # Log each pillar chart plus the all-pillars summary for a trust report.
        df = self._build_trust_report_dataframe(results)

        for pillar, color, notion_y_pos, figsize, _ in PILLAR_CONFIGS:
            self._log_pillar_figure(df, pillar, color, tag_root, notion_y_pos, figsize=figsize)

        self._log_all_pillars_figure(results, all_pillars_tag, label_suffix=label_suffix)

    def graphics(self):
        # Log centralized/global trustworthiness graphics.
        results_file = self._trust_report_path("nebula_trust_results.json")
        self._log_report_from_file(results_file, "Trust", "Trust/AllPillars")

    def graphics_dfl(self, participant_id):
        # Log local DFL graphics for one participant.
        results_file = self._trust_report_path(f"nebula_trust_results_{participant_id}.json")
        self._log_report_from_file(
            results_file,
            "Trust",
            f"Trust/AllPillars_{participant_id}",
            label_suffix=f"_{participant_id}",
        )

    def graphics_dfl_global(self, participant_id):
        # Log aggregated DFL global graphics for one participant.
        results_file = self._trust_report_path(f"nebula_trust_results_{participant_id}_global.json")
        self._log_report_from_file(
            results_file,
            "TrustGlobal",
            f"TrustGlobal/AllPillars_{participant_id}",
            label_suffix=f"_{participant_id}",
        )

    def graphics_sdfl_global(self, participant_id):
        # Log SDFL global graphics from the shared global report.
        results_file = self._trust_report_path("nebula_trust_results.json")
        self._log_report_from_file(
            results_file,
            "TrustGlobal",
            f"TrustGlobal/AllPillars_{participant_id}",
            label_suffix=f"_{participant_id}",
        )

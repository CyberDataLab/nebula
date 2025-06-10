from abc import ABC
import logging
import torch
import os
import pickle
import lightning as pl
from torchmetrics.classification import MulticlassAccuracy, MulticlassRecall, MulticlassPrecision, MulticlassF1Score, MulticlassConfusionMatrix
from torchmetrics import MetricCollection
import seaborn as sns
import matplotlib.pyplot as plt
import json
import pandas as pd

from nebula.core.utils.nebulalogger_tensorboard import NebulaTensorBoardLogger

logging.basicConfig(level=logging.INFO)

class Graphics():
    def __init__(
        self,
        scenario_start_time,
        scenario_name
    ):
        self.scenario_start_time = scenario_start_time
        self.scenario_name = scenario_name
        log_dir = os.path.join(os.environ["NEBULA_LOGS_DIR"], scenario_name)
        self.nebulalogger = NebulaTensorBoardLogger(scenario_start_time, f"{log_dir}", name="metrics", version=f"trust", log_graph=True)
        
    def __log_figure(self, df, pillar, color, notion_y_pos = -0.4, figsize=(10,6)):
        filtered_df = df[df['Pillar'] == pillar].copy()

        filtered_df.loc[:, 'Metric'] = filtered_df['Metric'].astype(str).str.replace('_', ' ')
        filtered_df.loc[:, 'Metric'] = filtered_df['Metric'].apply(lambda x: str(x).title())

        filtered_df.loc[:, 'Notion'] = filtered_df['Notion'].astype(str).str.replace('_', ' ')
        filtered_df.loc[:, 'Notion'] = filtered_df['Notion'].apply(lambda x: str(x).title())

        unique_notion_count = filtered_df['Notion'].nunique()
        palette = [color] * unique_notion_count 

        plt.figure(figsize=figsize)
        ax = sns.barplot(data=filtered_df, x='Metric', y='Metric Score', hue='Notion', palette=palette, dodge=False)

        x_positions = range(len(filtered_df))

        notion_scores = {}

        for i in range(len(filtered_df)):
            row = filtered_df.iloc[i]
            notion = row['Notion']
            notion_score = row['Notion Score']
            metric_score = row['Metric Score']
            
            if notion not in notion_scores:
                metrics_for_notion = filtered_df[filtered_df['Notion'] == notion]['Metric']
                start_pos = x_positions[i]
                end_pos = x_positions[i + len(metrics_for_notion) - 1]
                
                notion_x_pos = (start_pos + end_pos) / 2
                ax.axhline(notion_score, ls='--', color='black', lw=0.5, xmin=start_pos/len(x_positions), xmax=(end_pos+1)/len(x_positions))
                ax.text(notion_x_pos, notion_score + 0.01, f"{notion_score:.2f}", ha='center', va='bottom', fontsize=10, color='black')  # Color negro
                notion_scores[notion] = notion_score

        ax.set_xticks(x_positions)
        ax.set_xticklabels(filtered_df['Metric'], rotation=45, ha='right', fontsize=10)

        seen_notions = set()
        for i, (metric, notion) in enumerate(zip(filtered_df['Metric'], filtered_df['Notion'])):
            if notion not in seen_notions:
                metrics_for_notion = filtered_df[filtered_df['Notion'] == notion]['Metric']
                start_pos = x_positions[i]
                end_pos = x_positions[i + len(metrics_for_notion) - 1]
                
                notion_x_pos = (start_pos + end_pos) / 2
                
                ax.text(notion_x_pos, notion_y_pos, notion, ha='center', va='center', fontsize=10, color='black') 
                
                seen_notions.add(notion)  

        for i, v in enumerate(filtered_df['Metric Score']):
            ax.text(i, v + 0.01, f"{v:.2f}", ha='center', va='bottom', fontsize=10, color='black') 

        plt.xlabel('Metrics and notions', labelpad=35)
        plt.ylabel('Score')
        plt.title(f'Metrics and notion scores for the {pillar} pillar')

        ax.legend_.remove()

        plt.tight_layout()
        
        self.nebulalogger.log_figure(ax.get_figure(), 0, f"Trust/Pillar/{pillar}")
        plt.close()

    def graphics(self):
        results_file = os.path.join(os.environ.get("NEBULA_LOGS_DIR"), self.scenario_name, "trustworthiness", "nebula_trust_results.json")
        with open(results_file, 'r') as f:
            results = json.load(f)

        pillars_list = []
        notion_names = []
        notion_scores = []
        metric_names = []
        metric_scores = []

        for pillar in results["pillars"]:
            for key, value in pillar.items():
                pillar_name = key
                if "notions" in value:
                    for notion in value["notions"]:
                        for notion_key, notion_value in notion.items():
                            notion_name = notion_key
                            notion_score = notion_value["score"]
                            for metric in notion_value["metrics"]:
                                for metric_key, metric_value in metric.items():
                                    metric_name = metric_key
                                    metric_score = metric_value["score"]

                                    pillars_list.append(pillar_name)
                                    notion_names.append(notion_name)
                                    notion_scores.append(notion_score)
                                    metric_names.append(metric_name)
                                    metric_scores.append(metric_score)

        df = pd.DataFrame({
            "Pillar": pillars_list,
            "Notion": notion_names,
            "Notion Score": notion_scores,
            "Metric": metric_names,
            "Metric Score": metric_scores
        })

        self.__log_figure(df, 'robustness', "#F8D3DF")
        self.__log_figure(df, "privacy", "#DA8D8B", -0.2)
        self.__log_figure(df, "fairness", "#DDDDDD")
        self.__log_figure(df, "explainability", "#FCEFC3")
        self.__log_figure(df, "accountability", "#8FAADC", -0.3)
        self.__log_figure(df, "architectural_soundness", "#DBB9FA", -0.3)
        self.__log_figure(df, "sustainability", "#BBFDAF", -0.5, figsize=(12,8))

        categories = [
            "robustness",
            "privacy",
            "fairness",
            "explainability",
            "accountability",
            "architectural_soundness",
            "sustainability"
        ]

        scores = [results["pillars"][i][category]["score"] for i, category in enumerate(categories)]

        trust_score = results["trust_score"]
        categories.append("trust_score")
        scores.append(trust_score)

        palette = ["#F8D3DF", "#DA8D8B", "#DDDDDD", "#FCEFC3", "#8FAADC", "#DBB9FA", "#BBFDAF", "#BF9000"]

        plt.figure(figsize=(10, 8))
        ax = sns.barplot(x=categories, y=scores, palette=palette, hue=categories, legend=False)
        ax.set_xlabel("Pillar")
        ax.set_ylabel("Score")
        ax.set_title("Pillars and trust scores")

        for i, v in enumerate(scores):
            ax.text(i, v + 0.01, f"{v:.2f}", ha='center', va='bottom', fontsize=10)

        name_labels = [
            "Robustness",
            "Privacy",
            "Fairness",
            "Explainability",
            "Accountability",
            "Architectural Soundness",
            "Sustainability",
            "Trust Score"
        ]

        ax.set_xticks(range(len(categories)))
        ax.set_xticklabels(name_labels, rotation=45)

        self.nebulalogger.log_figure(ax.get_figure(), 0, f"Trust/AllPillars")
        plt.close()
"""Export g2pM fine-tuning data to CPP format.

Reads data/g2pm_training.jsonl (appended by /annotate/curate and
/annotate/dismiss when the frontend sends paragraph context) and writes
CPP-compatible files:

    <out>.sent   one paragraph per line, with U+2581 (▁) wrapped around the
                judged character, e.g. "他跑得▁快▁。" for a judgment on 快.
    <out>.lb     the correct pinyin for the judged character, one per line,
                aligned with the .sent lines (e.g. "de5").

Duplicate judgments for the same (text, index) keep the most recent row.

Usage:
    python manage.py export_training --out data/training_cpp/mine
"""

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand

MARK = "\u2581"  # ▁, the CPP target-character marker


class Command(BaseCommand):
    help = "Export data/g2pm_training.jsonl to CPP-format .sent/.lb files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out", default="data/training_cpp/curation",
            help="Output path prefix (default: data/training_cpp/curation). "
                 "Writes <out>.sent and <out>.lb.",
        )

    def handle(self, *args, **options):
        src = os.path.join(str(settings.BASE_DIR / "data"), "g2pm_training.jsonl")
        rows = []
        try:
            with open(src, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            self.stdout.write(f"No training data yet at {src}")
            return

        # Dedup on (text, index): the most recent judgment wins.
        latest = {}
        for row in rows:
            text, index = row.get("text"), row.get("index")
            char, pinyin = row.get("char"), row.get("pinyin")
            if not (isinstance(text, str) and isinstance(index, int)
                    and isinstance(char, str) and isinstance(pinyin, str)):
                continue
            if not (0 <= index < len(text) and text[index] == char):
                continue
            latest[(text, index)] = row

        out_prefix = options["out"]
        if not os.path.isabs(out_prefix):
            out_prefix = os.path.join(str(settings.BASE_DIR), out_prefix)
        os.makedirs(os.path.dirname(out_prefix) or ".", exist_ok=True)

        sent_path, lb_path = out_prefix + ".sent", out_prefix + ".lb"
        count = 0
        with open(sent_path, "w", encoding="utf-8") as sent_f, \
                open(lb_path, "w", encoding="utf-8") as lb_f:
            for (text, index), row in latest.items():
                char = row["char"]
                sent = text[:index] + MARK + char + MARK + text[index + 1:]
                sent_f.write(sent + "\n")
                lb_f.write(row["pinyin"] + "\n")
                count += 1

        self.stdout.write(
            f"Exported {count} examples -> {sent_path}, {lb_path}")

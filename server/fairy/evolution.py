"""Isolated deterministic experiment lab; it never deploys code or changes scoring."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .service import Service, fail
from .store import view


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=2000)
    required_terms: list[str] = Field(min_length=1, max_length=10)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=10)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    outputs: list[str] = Field(min_length=1, max_length=20)


class ExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    baseline: str = Field(min_length=1, max_length=80)
    cases: list[EvalCase] = Field(min_length=1, max_length=20)
    candidates: list[Candidate] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def valid(self):
        if self.baseline not in {candidate.name for candidate in self.candidates}:
            raise ValueError("baseline must name a candidate")
        if any(
            len(candidate.outputs) != len(self.cases) for candidate in self.candidates
        ):
            raise ValueError("each candidate needs one output per case")
        if len({candidate.name for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("candidate names must be unique")
        return self


def score_case(output, case):
    normalized = re.sub(r"\s+", " ", output.casefold())
    terms = [term.casefold() for term in case.required_terms]
    forbidden = [term.casefold() for term in case.forbidden_terms]
    covered = sum(term in normalized for term in terms)
    if any(term in normalized for term in forbidden):
        return 0.0, "forbidden_term"
    score = covered / len(terms)
    return score, "passed" if score == 1.0 else "missing_required_term"


class EvolutionService(Service):
    def create(self, body, key):
        payload = {"op": "evolution.create", **body.model_dump()}
        with self.db.tx() as session:
            cached = self.replay(session, key, payload)
            if cached is not None:
                return cached
            candidate_results = []
            for candidate in body.candidates:
                cases = []
                for case, output in zip(body.cases, candidate.outputs):
                    score, reason = score_case(output, case)
                    cases.append(
                        {
                            "input": case.input,
                            "output": output,
                            "score": score,
                            "reason": reason,
                        }
                    )
                candidate_results.append(
                    {
                        "name": candidate.name,
                        "score": sum(case["score"] for case in cases) / len(cases),
                        "passed_cases": sum(case["score"] == 1 for case in cases),
                        "total_cases": len(cases),
                        "cases": cases,
                    }
                )
            baseline = next(
                item for item in candidate_results if item["name"] == body.baseline
            )
            contrasts = {}
            composable = {}
            for item in candidate_results:
                if item["name"] == body.baseline:
                    continue
                gained, regressed, both_pass, both_fail = [], [], [], []
                gained_indices = set()
                for index, (case, baseline_case) in enumerate(zip(item["cases"], baseline["cases"])):
                    base = baseline_case["score"]
                    if case["score"] == 1.0 and base < 1.0:
                        gained.append(case["input"])
                        gained_indices.add(index)
                    elif case["score"] < 1.0 and base == 1.0:
                        regressed.append(case["input"])
                    elif case["score"] == 1.0:
                        both_pass.append(case["input"])
                    else:
                        both_fail.append(case["input"])
                contrasts[item["name"]] = {
                    "gained": gained,
                    "regressed": regressed,
                    "both_pass": both_pass,
                    "both_fail": both_fail,
                }
                if gained_indices and not regressed:
                    composable[item["name"]] = gained_indices

            # At most four non-baseline candidates. Check all combinations so
            # an early overlapping candidate cannot hide a stronger composition.
            picked, coverage = (), 0
            names = sorted(composable)
            for size in range(2, len(names) + 1):
                for group in combinations(names, size):
                    gains = [composable[name] for name in group]
                    covered = len(set.union(*gains))
                    if covered == sum(map(len, gains)) and covered > coverage:
                        picked, coverage = group, covered
            compose_suggestion = None
            if picked:
                compose_suggestion = {
                    "candidates": list(picked),
                    "case_sources": {name: contrasts[name]["gained"] for name in picked},
                    "rationale": "disjoint_gains_no_regressions",
                }
            prior_lessons = [
                view(r) for r in self.rows(session, "evolution_lesson")[-5:]
            ]
            best = max(candidate_results, key=lambda item: item["score"])
            improves = best["score"] > baseline["score"]
            winner = best if improves else baseline
            stable = not improves
            row = self.db.add(
                session,
                "owner",
                "evolution_experiment",
                {
                    "name": body.name,
                    "baseline": body.baseline,
                    "baseline_score": baseline["score"],
                    "winner": winner["name"],
                    "winner_score": winner["score"],
                    "recommendation": "keep_baseline" if stable else "review_candidate",
                    "results": candidate_results,
                    "contrasts": contrasts,
                    "compose_suggestion": compose_suggestion,
                    "prior_lessons": prior_lessons,
                    "status": "evaluated",
                    "runtime_changed": False,
                    "scoring_immutable": True,
                },
            )
            result = view(row)
            self.remember_result(session, key, payload, result)
            self.db.emit(
                session,
                "owner",
                "evolution.evaluated",
                {"id": row.id, "recommendation": result["recommendation"]},
            )
            return result

    def approve(self, experiment_id, candidate_name):
        with self.db.tx() as session:
            row = self.get(session, experiment_id, "evolution_experiment")
            data = json.loads(row.payload)
            if data["status"] != "evaluated":
                fail(409, "experiment_already_changed")
            if candidate_name != data["winner"]:
                fail(409, "only_evaluated_winner_can_be_reviewed")
            if candidate_name == data["baseline"]:
                fail(409, "candidate_did_not_improve_baseline")
            candidate = next(
                (
                    item
                    for item in data["results"]
                    if item["name"] == candidate_name
                ),
                None,
            )
            if candidate is None or candidate["score"] <= data["baseline_score"]:
                fail(409, "candidate_did_not_improve_baseline")
            data.update(
                status="approved_for_review",
                approved_candidate=candidate_name,
                runtime_changed=False,
            )
            row.payload = json.dumps(data)
            row.revision += 1
            self.db.emit(
                session,
                "owner",
                "evolution.approved_for_review",
                {"id": experiment_id, "candidate": candidate_name},
            )
            return view(row)

    def _by_status(self, session, status):
        rows = []
        for row in self.rows(session, "evolution_experiment"):
            data = json.loads(row.payload)
            if data.get("status") == status:
                rows.append((row, data))
        return rows

    def current_release(self):
        with self.db.sessions() as session:
            released = self._by_status(session, "released")
            if not released:
                return None
            row, _ = released[-1]
            return view(row)

    def release(self, experiment_id):
        """Mark this approved experiment as the current release record.

        The ledger never deploys code or changes scoring; it only tracks which
        evaluated candidate the owner has adopted, so rollback can restore the
        previous adoption in one step.
        """
        with self.db.tx() as session:
            row = self.get(session, experiment_id, "evolution_experiment")
            data = json.loads(row.payload)
            if data["status"] != "approved_for_review":
                fail(409, "experiment_not_releasable")
            now_iso = datetime.now(timezone.utc).isoformat()
            for previous, previous_data in self._by_status(session, "released"):
                previous_data.update(
                    status="superseded",
                    superseded_by=experiment_id,
                    superseded_at=now_iso,
                )
                previous.payload = json.dumps(previous_data)
                previous.revision += 1
            data.update(
                status="released",
                released_at=now_iso,
                runtime_changed=False,
            )
            row.payload = json.dumps(data)
            row.revision += 1
            contrast = data.get("contrasts", {}).get(data["approved_candidate"], {})
            gained = contrast.get("gained", [])
            regressed = contrast.get("regressed", [])
            self.db.add(
                session,
                "owner",
                "evolution_lesson",
                {
                    "experiment_id": experiment_id,
                    "candidate": data["approved_candidate"],
                    "kind": "adoption",
                    "lesson": (
                        f"实验「{data['name']}」采纳 {data['approved_candidate']}："
                        f"得分 {data['baseline_score']:.2f} → {data['winner_score']:.2f}，"
                        f"新增通过 {len(gained)} 例，回退 {len(regressed)} 例。"
                    ),
                    "evidence": {
                        "gained": gained,
                        "regressed": regressed,
                        "baseline_score": data["baseline_score"],
                        "winner_score": data["winner_score"],
                    },
                },
            )
            self.db.emit(
                session,
                "owner",
                "evolution.released",
                {"id": experiment_id, "candidate": data["approved_candidate"]},
            )
            return view(row)

    def rollback(self, experiment_id):
        with self.db.tx() as session:
            row = self.get(session, experiment_id, "evolution_experiment")
            data = json.loads(row.payload)
            if data["status"] not in ("approved_for_review", "released"):
                fail(409, "experiment_not_rollbackable")
            now_iso = datetime.now(timezone.utc).isoformat()
            restored_id = None
            if data["status"] == "released":
                superseded = self._by_status(session, "superseded")
                if superseded:
                    previous, previous_data = max(
                        superseded,
                        key=lambda item: item[1].get("superseded_at", ""),
                    )
                    previous_data.update(
                        status="released",
                        restored_at=now_iso,
                        restored_by=experiment_id,
                    )
                    previous.payload = json.dumps(previous_data)
                    previous.revision += 1
                    restored_id = previous.id
            data.update(
                status="rolled_back",
                rolled_back_at=now_iso,
                runtime_changed=False,
            )
            row.payload = json.dumps(data)
            row.revision += 1
            self.db.add(
                session,
                "owner",
                "evolution_lesson",
                {
                    "experiment_id": experiment_id,
                    "candidate": data.get("approved_candidate") or data.get("winner"),
                    "kind": "caution",
                    "lesson": (
                        f"实验「{data['name']}」的采纳已回滚；"
                        "后续提案应先复核该候选在失败样例上的表现。"
                    ),
                    "evidence": {"restored": restored_id, "rolled_back_at": now_iso},
                },
            )
            self.db.emit(
                session,
                "owner",
                "evolution.rolled_back",
                {"id": experiment_id, "restored": restored_id},
            )
            return view(row)

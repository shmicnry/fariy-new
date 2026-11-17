"""Isolated deterministic experiment lab; it never deploys code or changes scoring."""

from __future__ import annotations

import json
import re
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

    def rollback(self, experiment_id):
        with self.db.tx() as session:
            row = self.get(session, experiment_id, "evolution_experiment")
            data = json.loads(row.payload)
            data.update(status="rolled_back", runtime_changed=False)
            row.payload = json.dumps(data)
            row.revision += 1
            self.db.emit(
                session,
                "owner",
                "evolution.rolled_back",
                {"id": experiment_id},
            )
            return view(row)

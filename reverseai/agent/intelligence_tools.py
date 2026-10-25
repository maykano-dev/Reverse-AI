"""Agent tools for the engineering-intelligence layer.

These tools turn the structures in ``reverseai.intelligence`` into visible agent
actions. They are intentionally small: the agent builds a world model, asks it
questions, discovers opportunities, designs a twin simulation, compares
architectures, plans a product, and forges a tested tool. No tool here executes
target code except the forge, which uses the sandbox.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core import analyze_file
from ..intelligence.adapters import (
    CADAdapter, ComputerOperatorBoundary, HardwareAdapter, NetworkAdapter,
    RoboticsAdapter, SecurityAdapter,
)
from ..intelligence.design import ArchitectureSearch, Candidate, Objective
from ..intelligence.discovery import DiscoveryEngine
from ..intelligence.forge import ForgeError, ToolForge
from ..intelligence.learning import EvidenceReconstructor
from ..intelligence.orchestration import (
    Budget, CapabilityMap, HumanEscalation, IntelligenceCompressor,
    MissionPlanner, ModelProfile, ModelRouter, TrustEngine, export_manifests,
)
from ..intelligence.science import RealityEngine
from ..intelligence.product import build_product_plan, detect_languages, parse_spec
from ..intelligence.proof import build_proof_package
from ..intelligence.science import ExperimentEngine
from ..intelligence.twin import Contract, DigitalTwin, TwinChange
from ..intelligence.world import MemoryFabric, WorldModel, world_from_analysis
from ..sandbox import SandboxPolicy
from ..verify.report import build_report
from .tools import Permission, Tool, ToolContext, ToolResult


def _world(ctx: ToolContext) -> WorldModel:
    wm = ctx.extra.get("world_model")
    if isinstance(wm, WorldModel):
        return wm
    path = Path(ctx.workspace) / "world.json"
    try:
        wm = WorldModel.load(path)
    except Exception:
        if not ctx.target_path:
            wm = WorldModel()
        else:
            wm = world_from_analysis(analyze_file(ctx.target_path))
        wm.save(path)
    ctx.extra["world_model"] = wm
    return wm


def _save_world(ctx: ToolContext, wm: WorldModel) -> None:
    ctx.extra["world_model"] = wm
    wm.save(Path(ctx.workspace) / "world.json")


class BuildWorldModelTool(Tool):
    name = "build_world_model"
    description = (
        "Build an evidence-backed world model of the target: components, "
        "sections, functions, dependencies, symbols, strings, unresolved "
        "questions, and provenance. Saves it to the workspace and returns a "
        "summary. It does not claim runtime behavior."
    )
    parameters = {"type": "object", "properties": {
        "max_functions": {"type": "integer", "minimum": 1, "maximum": 200,
                          "default": 60}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        report = analyze_file(ctx.target_path)
        wm = world_from_analysis(report,
                                 max_functions=int(args.get("max_functions", 60)))
        _save_world(ctx, wm)
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"world model: {wm.summary()['nodes']} nodes, "
                f"{wm.summary()['edges']} edges, "
                f"{wm.summary()['unresolved']} unresolved item(s)",
                source=self.name)
        lines = [f"world model: {json.dumps(wm.summary(), sort_keys=True)}"]
        lines += [f"  {k}: {v}" for k, v in wm.summary()["node_kinds"].items()]
        return ToolResult.success("\n".join(lines), world=wm.to_dict(),
                                  summary=wm.summary())


class ProjectMemoryTool(Tool):
    name = "project_memory"
    description = (
        "Store, recall, invalidate, or list engineering memory by class "
        "(episodic, semantic, procedural, causal, project, temporal, "
        "evaluation). Project scope is enforced; a recall for one project does "
        "not leak another project's entries."
    )
    parameters = {"type": "object", "properties": {
        "action": {"type": "string",
                   "enum": ["store", "recall", "invalidate", "timeline"],
                   "default": "recall"},
        "kind": {"type": "string"},
        "text": {"type": "string"},
        "query": {"type": "string"},
        "scope": {"type": "string"},
        "confidence": {"type": "string"},
        "entry_id": {"type": "string"}}}
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        path = Path(ctx.workspace) / "memory_fabric.json"
        try:
            mf = MemoryFabric.load(path)
        except Exception:
            mf = MemoryFabric(str(Path(ctx.workspace).name))
        action = str(args.get("action") or "recall")
        if action == "store":
            try:
                row = mf.store(str(args.get("kind") or "project"),
                               str(args.get("text") or ""),
                               scope=str(args.get("scope") or "project"),
                               confidence=str(args.get("confidence") or "observed"))
            except Exception as exc:
                return ToolResult.failure(str(exc))
            mf.save(path)
            return ToolResult.success(json.dumps(row, indent=2), entry=row)
        if action == "invalidate":
            ok = mf.invalidate(str(args.get("entry_id") or ""),
                               str(args.get("text") or "invalidated"))
            mf.save(path)
            return ToolResult(ok=ok, content="invalidated" if ok else "entry not found",
                              data={"invalidated": ok})
        if action == "timeline":
            rows = mf.timeline()
            return ToolResult.success(json.dumps(rows, indent=2), entries=rows)
        rows = mf.recall(str(args.get("query") or ""),
                         kind=args.get("kind"), scope=args.get("scope"))
        return ToolResult.success(json.dumps(rows, indent=2), entries=rows)


class QueryWorldModelTool(Tool):
    name = "query_world_model"
    description = (
        "Query the saved world model: find components by kind/name, list "
        "unresolved questions, weak-evidence components, unverified "
        "requirements, or the next best tests."
    )
    parameters = {"type": "object", "properties": {
        "kind": {"type": "string"},
        "name": {"type": "string"},
        "query": {"type": "string",
                  "enum": ["summary", "unresolved", "weak", "requirements",
                           "next_tests", "stale"],
                  "default": "summary"}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        wm = _world(ctx)
        q = str(args.get("query") or "summary")
        if q == "unresolved":
            data = wm.unresolved()
        elif q == "weak":
            data = [n.to_dict() for n in wm.weak_components()]
        elif q == "requirements":
            data = [r.to_dict() for r in wm.unverified_requirements()]
        elif q == "next_tests":
            data = wm.next_best_tests()
        elif q == "stale":
            data = wm.stale()
        elif args.get("kind") or args.get("name"):
            data = [n.to_dict() for n in wm.find(args.get("kind"), args.get("name"))]
        else:
            data = wm.summary()
        body = json.dumps(data, indent=2, default=str)
        return ToolResult.success(body[:12000], result=data)


class DiscoverOpportunitiesTool(Tool):
    name = "discover_opportunities"
    description = (
        "Proactively inspect the target and propose ranked opportunities: "
        "possible hidden features, undocumented interfaces, architecture and "
        "dependency risks, missing tests, unlockable capabilities, and "
        "hypotheses worth testing. Every item points to observed evidence; this "
        "does not modify anything."
    )
    parameters = {"type": "object", "properties": {
        "use_world": {"type": "boolean", "default": True},
        "corpus_present": {"type": "boolean", "default": False},
        "tests_present": {"type": "boolean", "default": False}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        report = analyze_file(ctx.target_path)
        wm = _world(ctx) if args.get("use_world", True) else None
        engine = DiscoveryEngine(wm)
        opps = engine.discover(
            report, corpus_present=bool(args.get("corpus_present")),
            tests_present=bool(args.get("tests_present")))
        ctx.extra["discovery"] = [o.to_dict() for o in opps]
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"discovered {len(opps)} opportunity(ies); "
                f"top: {opps[0].title if opps else 'none'}",
                source=self.name)
        lines = [f"{len(opps)} opportunity(ies) (ranked):"]
        for o in opps[:10]:
            lines.append(f"- [{o.category}] {o.title} "
                         f"(score {o.score}, {o.confidence})")
            lines.append(f"  next: {o.proposed_action}")
        data = {"opportunities": [o.to_dict() for o in opps],
                "summary": engine.summary()}
        return ToolResult.success("\n".join(lines), **data)


class PlanDiscoveryMissionTool(Tool):
    name = "plan_discovery_mission"
    description = (
        "Turn discovered opportunities into a bounded investigation plan with "
        "an effort budget and a stopping rule. It is a plan, not permission to "
        "change the system."
    )
    parameters = {"type": "object", "properties": {
        "max_steps": {"type": "integer", "minimum": 1, "maximum": 20,
                      "default": 6},
        "max_effort": {"type": "integer", "minimum": 1, "maximum": 60,
                       "default": 15}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        opps = ctx.extra.get("discovery")
        if not opps:
            return ToolResult.failure(
                "run discover_opportunities first; there is no ranked list")
        engine = DiscoveryEngine(_world(ctx))
        engine.opportunities = []
        from ..intelligence.discovery import Opportunity
        for row in opps:
            try:
                engine.opportunities.append(Opportunity(**row))
            except TypeError:
                continue
        plan = engine.mission(max_steps=int(args.get("max_steps", 6)),
                              max_effort=int(args.get("max_effort", 15)))
        return ToolResult.success(json.dumps(plan, indent=2), plan=plan)


class FormHypothesesTool(Tool):
    name = "form_hypotheses"
    description = (
        "Turn ranked opportunities into falsifiable hypotheses with predictions "
        "and a clear distinction between observation and explanation."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        rows = ctx.extra.get("discovery") or []
        if not rows:
            return ToolResult.failure("run discover_opportunities first")
        engine = ExperimentEngine()
        out = []
        for row in rows[:10]:
            h = engine.hypothesize(
                str(row.get("hypothesis") or row.get("title")),
                {"changes_behavior": True}, scope=str(row.get("title")))
            out.append(h.to_dict())
        ctx.extra["hypotheses"] = out
        return ToolResult.success(json.dumps(out, indent=2), hypotheses=out)


class SimulateChangeTool(Tool):
    name = "simulate_change"
    description = (
        "Use the world model as a digital twin: identify affected components, "
        "predict contract failures, and list what must be tested live. A "
        "prediction is not a deployment guarantee."
    )
    parameters = {"type": "object", "properties": {
        "node": {"type": "string", "description": "component name or id"},
        "description": {"type": "string"},
        "removes": {"type": "array", "items": {"type": "string"}},
        "adds": {"type": "array", "items": {"type": "string"}},
        "modifies": {"type": "array", "items": {"type": "string"}},
        "contracts": {"type": "array", "items": {"type": "object"}}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        wm = _world(ctx)
        target = args.get("node") or ""
        node = wm.get(str(target))
        if node is None:
            matches = wm.find(name=str(target))
            if not matches:
                return ToolResult.failure(f"unknown component: {target}")
            node = matches[0]
        twin = DigitalTwin(wm)
        for raw in args.get("contracts") or []:
            if isinstance(raw, dict) and raw.get("component"):
                twin.add_contract(Contract(
                    str(raw["component"]), list(raw.get("requires") or []),
                    list(raw.get("provides") or []),
                    list(raw.get("invariants") or []),
                    list(raw.get("failure_modes") or []),
                    str(raw.get("evidence") or "")))
        sim = twin.simulate(TwinChange(
            node.id, str(args.get("description") or ""),
            list(args.get("removes") or []), list(args.get("adds") or []),
            list(args.get("modifies") or [])))
        ctx.extra["twin_simulation"] = sim.to_dict()
        return ToolResult.success(json.dumps(sim.to_dict(), indent=2),
                                  simulation=sim.to_dict())


class SearchArchitecturesTool(Tool):
    name = "search_architectures"
    description = (
        "Compare candidate architectures against measurable objectives. "
        "Returns weighted scores, the Pareto front, constraint violations, and "
        "the trade-offs. Unmeasured objectives are named."
    )
    parameters = {"type": "object", "properties": {
        "candidates": {"type": "array", "items": {"type": "object"}},
        "objectives": {"type": "array", "items": {"type": "object"}},
        "constraints": {"type": "array", "items": {"type": "string"}}},
        "required": ["candidates", "objectives"]}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        try:
            candidates = [Candidate(
                str(c.get("id") or f"cand_{i}"), str(c.get("name") or f"Candidate {i}"),
                str(c.get("description") or ""), dict(c.get("attributes") or {}),
                {k: float(v) for k, v in (c.get("measurements") or {}).items()
                 if isinstance(v, (int, float))},
                int(c.get("risk", 2)), int(c.get("complexity", 2)),
                float(c.get("cost", 0) or 0)) for i, c in enumerate(args["candidates"])]
            objectives = [Objective(str(o.get("name")), float(o.get("weight", 1)),
                                    str(o.get("direction", "max")),
                                    str(o.get("unit") or ""))
                          for o in args["objectives"]]
        except (TypeError, ValueError, KeyError) as exc:
            return ToolResult.failure(f"bad architecture input: {exc}")
        report = ArchitectureSearch().search(
            candidates, objectives, constraints=list(args.get("constraints") or []))
        return ToolResult.success(json.dumps(report.to_dict(), indent=2),
                                  architecture=report.to_dict())


class PlanProductTool(Tool):
    name = "plan_product"
    description = (
        "Turn a product goal into requirements, acceptance criteria, "
        "constraints, non-goals, a threat model, and a phased implementation "
        "plan. It is a plan, not a claim that the software exists."
    )
    parameters = {"type": "object", "properties": {
        "goal": {"type": "string"}, "detail": {"type": "string"}},
        "required": ["goal"]}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        spec = parse_spec(str(args.get("goal") or ""), str(args.get("detail") or ""))
        plan = build_product_plan(spec)
        return ToolResult.success(json.dumps(plan, indent=2), plan=plan)


class SelectModelTool(Tool):
    name = "select_model"
    description = (
        "Choose a model or tool profile for a task from capability, cost, "
        "latency, privacy, and measured success. Model agreement is never "
        "treated as verification."
    )
    parameters = {"type": "object", "properties": {
        "task": {"type": "string"},
        "required": {"type": "array", "items": {"type": "string"}},
        "max_cost": {"type": "number"},
        "max_latency_ms": {"type": "integer"},
        "privacy": {"type": "string", "enum": ["local", "cloud"]},
        "profiles": {"type": "array", "items": {"type": "object"}}},
        "required": ["task"]}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        profiles = []
        for p in args.get("profiles") or []:
            if not isinstance(p, dict):
                continue
            profiles.append(ModelProfile(
                str(p.get("name") or p.get("model") or "profile"),
                str(p.get("provider") or ""), str(p.get("model") or ""),
                list(p.get("capabilities") or []),
                float(p.get("cost_per_mtok", 0) or 0),
                int(p.get("latency_ms", 1000) or 1000),
                int(p.get("context_tokens", 8192) or 8192),
                bool(p.get("local")), str(p.get("privacy") or "cloud"),
                float(p.get("success_rate", 0.5) or 0.5),
                int(p.get("samples", 0) or 0),
                bool(p.get("available", True))))
        if not profiles:
            return ToolResult.failure("provide at least one model profile")
        router = ModelRouter(profiles)
        decision = router.select(
            str(args["task"]), required=list(args.get("required") or []),
            max_cost=args.get("max_cost"),
            max_latency=args.get("max_latency_ms"),
            privacy=args.get("privacy"))
        return ToolResult.success(json.dumps(decision.to_dict(), indent=2),
                                  decision=decision.to_dict())


class BuildProofPackageTool(Tool):
    name = "build_proof_package"
    description = (
        "Build a proof-carrying artifact: original and modified hashes, change, "
        "tools, versions, tests, measurements, limitations, reproduction, and "
        "the signed report. Writes proof.json and PROOF.md into the workspace."
    )
    parameters = {"type": "object", "properties": {
        "goal": {"type": "string"}, "change": {"type": "string"},
        "measurements": {"type": "object"}, "limitations": {"type": "array",
                                                            "items": {"type": "string"}},
        "directory": {"type": "string"}}}
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        modified = ctx.extra.get("modified_path")
        verification = ctx.extra.get("verification") or {}
        record = {
            "id": ctx.job_id, "goal": args.get("goal") or ctx.goal,
            "target_path": ctx.target_path,
            "artifact": Path(modified).name if modified else "",
            "artifact_meta": ({"name": Path(modified).name,
                               "path": modified,
                               "size": Path(modified).stat().st_size,
                               "sha256": ""}
                              if modified and Path(modified).is_file() else {}),
            "verification": verification,
            "delivery": ctx.extra.get("delivery") or {},
            "mode": ctx.extra.get("mode"), "modification_plan": ctx.extra.get("modification_plan") or {},
            "evidence": [], "finished_at": None,
        }
        report = build_report(record)
        pkg = build_proof_package(
            str(args.get("goal") or ctx.goal), ctx.target_path, modified,
            change=str(args.get("change") or verification.get("reason") or ""),
            tools=[e.tool for e in (ctx.extra.get("audit") or []) if getattr(e, "tool", None)],
            versions={"reverseai": "0.5.0"},
            tests=report.get("tests") or [],
            measurements=dict(args.get("measurements") or {}),
            limitations=list(args.get("limitations") or []),
            report=report)
        out = pkg.save(str(args.get("directory") or Path(ctx.workspace) / "proof"))
        return ToolResult.success(
            f"proof package: {pkg.id}\nmanifest: {out['manifest']}\n"
            f"summary: {out['markdown']}",
            proof=pkg.to_dict(), files=out)


class PlanMissionTool(Tool):
    name = "plan_mission"
    description = (
        "Plan a long-running engineering mission with acceptance criteria, "
        "constraints, budget, checkpoints, and approval gates. Planning is not "
        "permission to act."
    )
    parameters = {"type": "object", "properties": {
        "objective": {"type": "string"},
        "acceptance": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "budget_usd": {"type": "number"}, "deadline_s": {"type": "number"}},
        "required": ["objective"]}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        mission = MissionPlanner().plan(
            str(args["objective"]), acceptance=list(args.get("acceptance") or []),
            constraints=list(args.get("constraints") or []),
            budget_usd=float(args.get("budget_usd", 0) or 0),
            deadline_s=float(args.get("deadline_s", 0) or 0))
        return ToolResult.success(json.dumps(mission.to_dict(), indent=2),
                                  mission=mission.to_dict())


class AnalyzeDomainTool(Tool):
    name = "analyze_domain"
    description = (
        "Apply the hardware, robotics, CAD, network, or security adapter. Each "
        "adapter returns inventory, hypotheses, a simulation plan, and explicit "
        "refusals. No physical or live-system action is performed."
    )
    parameters = {"type": "object", "properties": {
        "domain": {"type": "string",
                   "enum": ["hardware", "robotics", "cad", "network", "security",
                            "computer"]},
        "data": {"type": "object"}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        domain = str(args.get("domain") or "")
        data = args.get("data") or {}
        try:
            if domain == "hardware":
                result = HardwareAdapter().inspect(
                    str(data.get("path") or ctx.target_path or ""))
            elif domain == "robotics":
                result = RoboticsAdapter().inspect(data)
            elif domain == "cad":
                result = CADAdapter().inspect(data)
            elif domain == "network":
                result = NetworkAdapter().inspect(data)
            elif domain == "security":
                if not ctx.target_path:
                    return ToolResult.failure("security adapter needs a target")
                result = SecurityAdapter().inspect(analyze_file(ctx.target_path))
            elif domain == "computer":
                return ToolResult.success(
                    json.dumps(ComputerOperatorBoundary().plan(
                        str(data.get("objective") or ctx.goal)), indent=2),
                    plan=ComputerOperatorBoundary().plan(
                        str(data.get("objective") or ctx.goal)))
            else:
                return ToolResult.failure(f"unknown domain: {domain}")
        except Exception as exc:
            return ToolResult.failure(f"{domain} adapter failed: {exc}")
        return ToolResult(ok=True, content=json.dumps(result.to_dict(), indent=2),
                          data={"adapter": result.to_dict()})


class ForgeToolTool(Tool):
    name = "forge_tool"
    description = (
        "Write a small Python tool into the workspace, then test it in the "
        "sandbox with declared cases. Nothing is promoted unless every test "
        "passes. The tool must expose run(payload) -> JSON-serializable mapping."
    )
    parameters = {"type": "object", "properties": {
        "name": {"type": "string"}, "description": {"type": "string"},
        "code": {"type": "string"},
        "cases": {"type": "array", "items": {"type": "object"}},
        "inputs": {"type": "object"}, "outputs": {"type": "object"}},
        "required": ["name", "code", "cases"]}
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        try:
            forge = ToolForge(ctx.workspace)
            tool = forge.create(str(args["name"]), str(args.get("description") or ""),
                                str(args["code"]), inputs=args.get("inputs"),
                                outputs=args.get("outputs"))
            tool = forge.test(tool, list(args.get("cases") or []),
                              policy=ctx.sandbox_policy or
                              SandboxPolicy(allow_untrusted_execution=True))
        except ForgeError as exc:
            return ToolResult.failure(str(exc))
        if tool.status != "tested":
            return ToolResult(ok=False, content=json.dumps(tool.to_dict(), indent=2),
                              data={"tool": tool.to_dict()},
                              error="forged tool failed its tests")
        ctx.extra["forged_tool"] = tool.to_dict()
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"forged tool {tool.name}: {tool.passed} test(s) passed in the sandbox",
                source=self.name)
        return ToolResult.success(json.dumps(tool.to_dict(), indent=2),
                                  tool=tool.to_dict())


class ExportToolManifestsTool(Tool):
    name = "export_tool_manifests"
    description = (
        "Export the universal tool protocol: name, permission, parameters, "
        "resources, side effects, and security boundary for every registered "
        "tool. Read-only."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        tools = ctx.extra.get("all_tools") or []
        if not tools:
            return ToolResult.failure("no tool registry is attached to this context")
        manifests = export_manifests(list(tools))
        return ToolResult.success(json.dumps(manifests, indent=2),
                                  manifests=manifests)


class RealityCheckTool(Tool):
    name = "reality_check"
    description = (
        "Separate a prediction, a simulation, an observation, and an unknown. "
        "A simulation is not an observation, and a prediction is not a fact."
    )
    parameters = {"type": "object", "properties": {
        "claims": {"type": "array", "items": {"type": "object"}}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        engine = RealityEngine()
        for row in args.get("claims") or []:
            if isinstance(row, dict) and row.get("claim"):
                engine.add(str(row["claim"]), str(row.get("kind") or "unknown"),
                           source=str(row.get("source") or ""),
                           detail=str(row.get("detail") or ""),
                           scope=str(row.get("scope") or ""))
        return ToolResult.success(json.dumps(engine.summary(), indent=2),
                                  reality=engine.summary())


class HumanDecisionTool(Tool):
    name = "human_decision"
    description = (
        "Identify the exact decision that needs a human: physical safety, "
        "authorization, irreversible consequence, domain judgment, or legal "
        "ownership. It can say what work may continue without that decision."
    )
    parameters = {"type": "object", "properties": {
        "question": {"type": "string"}, "physical": {"type": "boolean"},
        "authorization": {"type": "boolean"}, "irreversible": {"type": "boolean"},
        "domain_expertise": {"type": "boolean"}, "legal": {"type": "boolean"},
        "options": {"type": "array", "items": {"type": "string"}}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        decision = HumanEscalation().identify(
            physical=bool(args.get("physical")),
            authorization=bool(args.get("authorization")),
            irreversible=bool(args.get("irreversible")),
            domain_expertise=bool(args.get("domain_expertise")),
            legal=bool(args.get("legal")),
            question=str(args.get("question") or "Approve this action?"),
            options=list(args.get("options") or []))
        if decision is None:
            return ToolResult.success("No human decision is required by the stated conditions.",
                                      decision=None)
        return ToolResult.success(json.dumps(decision.to_dict(), indent=2),
                                  decision=decision.to_dict())


class CompressionPlanTool(Tool):
    name = "compression_plan"
    description = (
        "Plan cheap-first execution: deterministic tool, small model, strong "
        "model, or human, with a quality check at every stage. Never trade a "
        "verified result for a cheaper unverified one."
    )
    parameters = {"type": "object", "properties": {
        "task": {"type": "string"},
        "ambiguity": {"type": "string", "enum": ["low", "medium", "high"]},
        "risk": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "needs_reasoning": {"type": "boolean"}}, "required": ["task"]}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        plan = IntelligenceCompressor().plan(
            str(args["task"]), ambiguity=str(args.get("ambiguity") or "low"),
            risk=str(args.get("risk") or "low"),
            needs_reasoning=bool(args.get("needs_reasoning")))
        return ToolResult.success(json.dumps(plan, indent=2), plan=plan)


class ReconstructionPlanTool(Tool):
    name = "reconstruction_plan"
    description = (
        "Given executors, screenshots, logs, traces, documentation, and "
        "behaviour examples, say what can be reconstructed, what is "
        "underdetermined, and which evidence would help most. It does not claim "
        "to recover internal source code from observations."
    )
    parameters = {"type": "object", "properties": {
        "evidence": {"type": "object"}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        plan = EvidenceReconstructor().plan(dict(args.get("evidence") or {}))
        return ToolResult.success(json.dumps(plan.to_dict(), indent=2),
                                  plan=plan.to_dict())


class CapabilityMapTool(Tool):
    name = "capability_map"
    description = (
        "Report measured capability by task class: attempts, verified rate, "
        "failure modes, cost, tools, and independent checks. It does not invent "
        "a percentage from a small sample."
    )
    parameters = {"type": "object", "properties": {
        "records": {"type": "array", "items": {"type": "object"}}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        cmap = CapabilityMap()
        for row in args.get("records") or []:
            if not isinstance(row, dict):
                continue
            for _ in range(int(row.get("attempts", 1) or 1)):
                cmap.record(str(row.get("task_class") or "unknown"),
                            verified=bool(row.get("verified")),
                            cost=float(row.get("cost", 0) or 0),
                            seconds=float(row.get("seconds", 0) or 0),
                            tools=list(row.get("tools") or []),
                            failure_mode=str(row.get("failure_mode") or ""),
                            independent=bool(row.get("independent")))
        return ToolResult.success(json.dumps(cmap.summary(), indent=2),
                                  capability=cmap.summary())


class TrustCheckTool(Tool):
    name = "trust_check"
    description = (
        "Classify an action as auto, notify, approve, or forbid from "
        "reversibility, blast radius, external effect, sensitive data, and "
        "financial impact. It does not grant approval."
    )
    parameters = {"type": "object", "properties": {
        "action": {"type": "string"}, "reversible": {"type": "boolean"},
        "blast_radius": {"type": "string", "enum": ["local", "service",
                                                    "organization", "production"]},
        "external": {"type": "boolean"}, "sensitive_data": {"type": "boolean"},
        "financial": {"type": "boolean"}}, "required": ["action"]}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        decision = TrustEngine().classify(
            str(args["action"]), reversible=bool(args.get("reversible", True)),
            blast_radius=str(args.get("blast_radius") or "local"),
            external=bool(args.get("external")),
            sensitive_data=bool(args.get("sensitive_data")),
            financial=bool(args.get("financial")))
        return ToolResult.success(json.dumps(decision.to_dict(), indent=2),
                                  trust=decision.to_dict())


def intelligence_tools() -> list[Tool]:
    return [
        BuildWorldModelTool(), QueryWorldModelTool(), ProjectMemoryTool(),
        DiscoverOpportunitiesTool(),
        PlanDiscoveryMissionTool(), FormHypothesesTool(), SimulateChangeTool(),
        SearchArchitecturesTool(), PlanProductTool(), SelectModelTool(),
        BuildProofPackageTool(), PlanMissionTool(), AnalyzeDomainTool(),
        ForgeToolTool(), ExportToolManifestsTool(), CapabilityMapTool(),
        TrustCheckTool(), RealityCheckTool(), HumanDecisionTool(),
        CompressionPlanTool(), ReconstructionPlanTool(),
    ]

"""Decision revision comparison and downstream routine impact mapping."""

from __future__ import annotations

from typing import Any

from .models import Decision, DecisionComparison, FieldChange, RoutineImpact


def _change(path: str, before: Any, after: Any) -> FieldChange:
    if before is None:
        change_type = "ADDED"
    elif after is None:
        change_type = "REMOVED"
    else:
        change_type = "CHANGED"
    return FieldChange(
        path=path,
        change_type=change_type,
        before=before,
        after=after,
    )


def _snapshot_changes(
    before: Any,
    after: Any,
    path: str = "context.snapshot",
) -> list[FieldChange]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[FieldChange] = []
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}.{key}"
            if key not in before:
                changes.append(_change(child_path, None, after[key]))
            elif key not in after:
                changes.append(_change(child_path, before[key], None))
            else:
                changes.extend(
                    _snapshot_changes(before[key], after[key], child_path)
                )
        return changes
    return [_change(path, before, after)]


def compare_decisions(prior: Decision, current: Decision) -> DecisionComparison:
    changes: list[FieldChange] = []
    if prior.summary != current.summary:
        changes.append(_change("summary", prior.summary, current.summary))

    prior_context = prior.context
    current_context = current.context
    if (prior_context is None) != (current_context is None):
        changes.append(
            _change(
                "context",
                prior_context.model_dump(mode="json") if prior_context else None,
                current_context.model_dump(mode="json") if current_context else None,
            )
        )
    elif prior_context and current_context:
        if prior_context.source != current_context.source:
            changes.append(
                _change(
                    "context.source",
                    prior_context.source,
                    current_context.source,
                )
            )
        if prior_context.tools != current_context.tools:
            changes.append(
                _change(
                    "context.tools",
                    prior_context.tools,
                    current_context.tools,
                )
            )
        if prior_context.fetched_at != current_context.fetched_at:
            changes.append(
                _change(
                    "context.fetched_at",
                    prior_context.fetched_at.isoformat(),
                    current_context.fetched_at.isoformat(),
                )
            )
        if prior_context.facts != current_context.facts:
            changes.append(
                _change(
                    "context.facts",
                    prior_context.facts,
                    current_context.facts,
                )
            )
        changes.extend(
            _snapshot_changes(
                prior_context.snapshot,
                current_context.snapshot,
            )
        )

    prior_dependencies = [
        dependency.model_dump(mode="json") for dependency in prior.dependencies
    ]
    current_dependencies = [
        dependency.model_dump(mode="json") for dependency in current.dependencies
    ]
    if prior_dependencies != current_dependencies:
        changes.append(
            _change(
                "dependencies",
                prior_dependencies,
                current_dependencies,
            )
        )

    prior_analysis = (
        prior.analysis.model_dump(mode="json") if prior.analysis else None
    )
    current_analysis = (
        current.analysis.model_dump(mode="json") if current.analysis else None
    )
    changes.extend(
        _snapshot_changes(
            prior_analysis,
            current_analysis,
            path="analysis",
        )
    )

    changed_paths = [change.path for change in changes]
    context_paths = [
        path for path in changed_paths if path.startswith("context")
    ]
    routine_impacts: list[RoutineImpact] = []
    if context_paths:
        routine_impacts.append(
            RoutineImpact(
                routine="retrieve_context",
                effect=(
                    "Use the refreshed governed metadata and schema snapshot "
                    "instead of the prior retrieval."
                ),
                triggered_by=context_paths,
            )
        )
    analysis_paths = [
        path for path in changed_paths if path.startswith("analysis")
    ]
    if analysis_paths:
        routine_impacts.append(
            RoutineImpact(
                routine="run_analytics_agent",
                effect=(
                    "Re-run the governed SQL analysis and replace prior result "
                    "rows, chart, and context-quality evidence."
                ),
                triggered_by=analysis_paths,
            )
        )
    if context_paths or analysis_paths:
        routine_impacts.append(
            RoutineImpact(
                routine="build_recommendation",
                effect=(
                    "Recompute the recommendation from the updated DataHub "
                    "context and Analytics Agent result."
                ),
                triggered_by=[*context_paths, *analysis_paths],
            )
        )
    dependency_paths = [
        path for path in changed_paths if path == "dependencies"
    ]
    if dependency_paths:
        routine_impacts.append(
            RoutineImpact(
                routine="monitor_dependencies",
                effect=(
                    "Update the assets and fields watched for future "
                    "invalidation signals."
                ),
                triggered_by=dependency_paths,
            )
        )
    routine_impacts.extend(
        [
            RoutineImpact(
                routine="request_human_approval",
                effect=(
                    "Require a fresh approval because the evidence-bearing "
                    "decision revision changed."
                ),
                triggered_by=changed_paths or ["revision_created"],
            ),
            RoutineImpact(
                routine="project_datahub_document",
                effect=(
                    "Keep the prior DataHub projection immutable and create a "
                    "new projection only after the updated revision is approved."
                ),
                triggered_by=["supersedes"],
            ),
        ]
    )
    return DecisionComparison(
        prior=prior,
        current=current,
        changes=changes,
        routine_impacts=routine_impacts,
    )
